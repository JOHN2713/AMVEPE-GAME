import io
from functools import lru_cache

import segno
from flask import Blueprint, Response, current_app, jsonify, render_template
from sqlalchemy import text

from app.extensions import db
from app.services.catalog_service import playable_assets

bp = Blueprint("pages", __name__)


@bp.get("/")
def register():
    return render_template("register.html")


@bp.get("/juego")
def game():
    return render_template("game.html")


@bp.get("/resultados")
def results():
    return render_template("results.html", demo_url=current_app.config["PUBLIC_DEMO_URL"])


@bp.get("/ranking")
def ranking():
    return render_template("ranking.html")


@bp.get("/terminos")
def terms():
    return render_template("legal_page.html", page="terms")


@bp.get("/privacidad")
def privacy():
    return render_template("legal_page.html", page="privacy")


@bp.get("/creditos")
def credits():
    # Solo las imágenes que realmente pueden aparecer en el juego; sin raza para no revelar respuestas.
    assets = [a for a in playable_assets() if a.provider != "placeholder"]
    by_author: dict[str, dict] = {}
    for asset in sorted(assets, key=lambda a: (a.attribution or "").casefold()):
        entry = by_author.setdefault(asset.attribution or "Autor no indicado", {"sources": [], "provider": asset.provider})
        if asset.source_url.startswith("http"):
            entry["sources"].append(asset.source_url)
    return render_template("credits.html", credits=by_author)


@lru_cache(maxsize=4)
def _qr_svg(url: str) -> str:
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="svg", scale=8, dark="#030712", light="#FFFFFF", border=2)
    return buffer.getvalue().decode("utf-8")


@bp.get("/qr/demo.svg")
def demo_qr():
    svg = _qr_svg(current_app.config["PUBLIC_DEMO_URL"])
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


@bp.get("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "database": "ok"})
    except Exception:  # noqa: BLE001 - el health check nunca expone detalles
        db.session.rollback()
        return jsonify({"status": "degraded", "database": "error"}), 503
