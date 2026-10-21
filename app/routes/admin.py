import csv
import hmac
import io
import secrets
import uuid
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import select
from werkzeug.security import check_password_hash

from app.extensions import db, limiter
from app.models import AnimalAsset, GameSession, Participant, ParticipantConsent
from app.models.animal_asset import SPECIES, USAGES
from app.models.base import as_utc
from app.services.catalog_service import content_report
from app.services.game_service import expire_stale_sessions
from app.services.scoring_service import event_stats, ranking

bp = Blueprint("admin", __name__, url_prefix="/admin")

LOCAL_TZ = ZoneInfo("America/Guayaquil")
# Contraseña ficticia para que el tiempo de respuesta no revele si el usuario existe.
_DUMMY_HASH = "scrypt:32768:8:1$dummy$" + "0" * 128


@bp.app_template_filter("local_dt")
def local_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return as_utc(value).astimezone(LOCAL_TZ).strftime("%d/%m/%Y %H:%M:%S")


def _csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@bp.app_context_processor
def inject_csrf():
    return {"csrf_token": _csrf_token}


def _check_csrf():
    sent = request.form.get("csrf_token", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf_token", "")):
        abort(400)


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin.login", next=request.path))
        if request.method == "POST":
            _check_csrf()
        return view(*args, **kwargs)

    return wrapper


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute", methods=["POST"])
def login():
    cfg = current_app.config
    configured = bool(cfg["ADMIN_PASSWORD_HASH"])
    error = None
    if request.method == "POST":
        _check_csrf()
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        password_hash = cfg["ADMIN_PASSWORD_HASH"] if configured else _DUMMY_HASH
        try:
            password_ok = check_password_hash(password_hash, password)
        except ValueError:
            password_ok = False
        if configured and hmac.compare_digest(username, cfg["ADMIN_USERNAME"]) and password_ok:
            session.clear()
            session["is_admin"] = True
            session.permanent = True
            target = request.args.get("next", "")
            return redirect(target if target.startswith("/admin") else url_for("admin.dashboard"))
        error = "Usuario o contraseña incorrectos."
    return render_template("admin_login.html", error=error, configured=configured)


@bp.post("/logout")
@admin_required
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@bp.get("")
@admin_required
def dashboard():
    expire_stale_sessions()
    recent = db.session.execute(
        select(GameSession, Participant)
        .join(Participant, Participant.id == GameSession.participant_id)
        .where(GameSession.event_code == current_app.config["EVENT_CODE"])
        .order_by(GameSession.created_at.desc())
        .limit(40)
    ).all()
    return render_template(
        "admin_dashboard.html",
        stats=event_stats(),
        content=content_report(),
        ranking=ranking(limit=50, include_private=True),
        recent=recent,
    )


@bp.post("/sesiones/<session_id>/anular")
@admin_required
def invalidate_session(session_id):
    game = db.session.get(GameSession, _uuid(session_id))
    if game is None:
        abort(404)
    if game.status in ("completed", "expired"):
        game.status = "invalidated"
        db.session.commit()
        flash("Partida anulada: ya no cuenta para el ranking.", "ok")
    return redirect(url_for("admin.dashboard"))


@bp.post("/sesiones/<session_id>/restaurar")
@admin_required
def restore_session(session_id):
    game = db.session.get(GameSession, _uuid(session_id))
    if game is None:
        abort(404)
    if game.status == "invalidated":
        game.status = "completed"
        db.session.commit()
        flash("Partida restaurada en el ranking.", "ok")
    return redirect(url_for("admin.dashboard"))


# --------------------------------------------------------------------------- catálogo

@bp.get("/catalogo")
@admin_required
def catalog():
    status = request.args.get("estado", "pending")
    query = select(AnimalAsset).order_by(AnimalAsset.species, AnimalAsset.breed_name_es, AnimalAsset.created_at)
    if status in ("pending", "approved", "rejected"):
        query = query.where(AnimalAsset.license_status == status)
    assets = db.session.execute(query).scalars().all()
    return render_template(
        "admin_catalog.html", assets=assets, status=status, species_options=SPECIES, usage_options=USAGES, content=content_report()
    )


@bp.post("/catalogo/<asset_id>")
@admin_required
def update_asset(asset_id):
    asset = db.session.get(AnimalAsset, _uuid(asset_id))
    if asset is None:
        abort(404)
    action = request.form.get("action")
    species = request.form.get("species", asset.species)
    usage = request.form.get("usage", asset.usage)
    breed = (request.form.get("breed_name_es") or "").strip() or None
    if species not in SPECIES or usage not in USAGES:
        abort(400)
    asset.species, asset.usage, asset.breed_name_es = species, usage, breed
    if action == "approve":
        if usage in ("breed", "both") and (species == "other" or not breed):
            flash("Para preguntas de raza la foto debe ser de perro o gato y tener la raza verificada.", "error")
            db.session.rollback()
            return redirect(request.referrer or url_for("admin.catalog"))
        asset.license_status = "approved"
        asset.active = True
    elif action == "reject":
        asset.license_status = "rejected"
        asset.active = False
    elif action == "toggle":
        asset.active = not asset.active and asset.license_status == "approved"
    db.session.commit()
    flash("Imagen actualizada.", "ok")
    return redirect(request.referrer or url_for("admin.catalog"))


# --------------------------------------------------------------------------- exportación CSV

def _safe_cell(value) -> str:
    """Evita inyección de fórmulas al abrir el CSV en Excel."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not text.startswith("+593"):
        return "'" + text
    return text


def _csv_response(filename: str, header: list[str], rows) -> Response:
    out = io.StringIO()
    out.write("﻿")  # BOM para que Excel respete tildes
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_safe_cell(v) for v in row])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


@bp.get("/export/participantes.csv")
@admin_required
def export_participants():
    event_code = current_app.config["EVENT_CODE"]
    participants = db.session.execute(
        select(Participant).where(Participant.event_code == event_code).order_by(Participant.player_number)
    ).scalars().all()
    rows = []
    for p in participants:
        latest: ParticipantConsent | None = p.consents[-1] if p.consents else None
        best = max((s.total_score for s in p.sessions if s.status in ("completed", "expired")), default=None)
        rows.append(
            [
                p.player_number, p.full_name, p.email, p.phone_e164, local_dt(p.created_at),
                latest.terms_version if latest else "", local_dt(latest.terms_accepted_at) if latest else "",
                latest.privacy_version if latest else "", local_dt(latest.privacy_accepted_at) if latest else "",
                "si" if latest and latest.marketing_opt_in else "no", local_dt(latest.marketing_consent_at) if latest else "",
                len([s for s in p.sessions if s.status in ("completed", "expired")]), best if best is not None else "",
            ]
        )
    header = [
        "jugador", "nombre", "correo", "celular", "registrado", "version_terminos", "terminos_aceptados",
        "version_privacidad", "privacidad_aceptada", "acepta_marketing", "marketing_fecha", "partidas", "mejor_puntaje",
    ]
    return _csv_response(f"participantes-{event_code}.csv", header, rows)


@bp.get("/export/partidas.csv")
@admin_required
def export_sessions():
    event_code = current_app.config["EVENT_CODE"]
    rows = db.session.execute(
        select(GameSession, Participant)
        .join(Participant, Participant.id == GameSession.participant_id)
        .where(GameSession.event_code == event_code)
        .order_by(GameSession.created_at)
    ).all()
    data = [
        [
            str(s.id), p.player_number, p.full_name, s.status, local_dt(s.started_at), local_dt(s.completed_at),
            s.pairs_found, s.memory_score, s.breed_answered, s.breed_correct, s.breed_score, s.total_score,
        ]
        for s, p in rows
    ]
    header = [
        "partida", "jugador", "nombre", "estado", "inicio", "fin", "parejas", "puntaje_memoria",
        "preguntas_respondidas", "razas_correctas", "puntaje_razas", "puntaje_total",
    ]
    return _csv_response(f"partidas-{event_code}.csv", header, data)


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        abort(404)
