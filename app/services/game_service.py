"""Reglas autoritativas de la partida: tablero, tiempos por etapa, parejas y preguntas de raza."""

import random
import secrets
import uuid
from datetime import timedelta

from flask import current_app, url_for
from sqlalchemy import func, select, update

from app.extensions import db
from app.models import GameAnswer, GameSession, MemoryAttempt, Participant, SessionMemoryCard
from app.models.base import as_utc
from app.services import clock
from app.services.catalog_service import FALLBACK_BREEDS, breed_names_by_species, playable_assets
from app.services.errors import ApiError
from app.services.scoring_service import recompute_scores

_rng = random.SystemRandom()

FINISHED_STATUSES = ("completed", "expired", "invalidated")
# Una partida en curso que nadie cerró se marca expirada pasado este margen tras el final teórico.
EXPIRE_AFTER = timedelta(minutes=5)
ABANDON_AFTER = timedelta(minutes=30)


# --------------------------------------------------------------------------- tiempos

def stage_seconds() -> int:
    return current_app.config["STAGE_SECONDS"]


def total_seconds() -> int:
    return stage_seconds() * 2


def elapsed_seconds(session: GameSession) -> float | None:
    started = as_utc(session.started_at)
    if started is None:
        return None
    return (clock.now() - started).total_seconds()


def memory_end_seconds(session: GameSession) -> float:
    """Fin de la etapa 1: a los 45 s o, si antes se encontraron las 6 parejas, en ese instante.

    El tiempo sobrante pasa a la etapa 2; la partida siempre dura 90 s en total.
    """
    cards = session.cards
    started = as_utc(session.started_at)
    if started is not None and cards and all(c.matched_at for c in cards):
        last_match = max(as_utc(c.matched_at) for c in cards)
        return min(float(stage_seconds()), (last_match - started).total_seconds())
    return float(stage_seconds())


def current_stage(session: GameSession) -> str:
    if session.status in FINISHED_STATUSES or session.status == "abandoned":
        return "finished"
    elapsed = elapsed_seconds(session)
    if elapsed is None:
        return "ready"
    if elapsed < memory_end_seconds(session):
        return "memory"
    if elapsed < total_seconds():
        return "breed"
    return "finished"


# --------------------------------------------------------------------------- carga

def parse_session_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        raise ApiError("La partida no existe.", status=404, code="session_not_found")


def load_session(session_id, lock: bool = False) -> GameSession:
    sid = parse_session_id(session_id)
    query = select(GameSession).where(GameSession.id == sid)
    if lock:
        query = query.with_for_update()
    session = db.session.execute(query).scalar_one_or_none()
    if session is None:
        raise ApiError("La partida no existe.", status=404, code="session_not_found")
    return session


def _token() -> str:
    return secrets.token_urlsafe(18)


# --------------------------------------------------------------------------- creación

def create_session(participant_id) -> GameSession:
    cfg = current_app.config
    try:
        pid = uuid.UUID(str(participant_id))
    except (ValueError, TypeError):
        raise ApiError("Registro no encontrado. Vuelve a registrarte.", status=404, code="participant_not_found")
    participant = db.session.get(Participant, pid)
    if participant is None or participant.event_code != cfg["EVENT_CODE"] or participant.anonymized_at is not None:
        raise ApiError("Registro no encontrado. Vuelve a registrarte.", status=404, code="participant_not_found")

    max_sessions = cfg["MAX_SESSIONS_PER_PARTICIPANT"]
    if max_sessions > 0:
        played = db.session.execute(
            select(func.count(GameSession.id)).where(
                GameSession.participant_id == pid, GameSession.status.in_(("in_progress", "completed", "expired"))
            )
        ).scalar_one()
        if played >= max_sessions:
            raise ApiError("Ya alcanzaste el número máximo de partidas para este evento.", status=403, code="max_sessions_reached")

    # Las partidas preparadas que nunca empezaron quedan descartadas.
    db.session.execute(
        update(GameSession).where(GameSession.participant_id == pid, GameSession.status == "created").values(status="abandoned")
    )

    assets = playable_assets()
    memory_pool = [a for a in assets if a.usable_for_memory]
    if len(memory_pool) < cfg["MEMORY_PAIRS"]:
        raise ApiError("El juego no está disponible en este momento. Avisa al asesor.", status=503, code="content_unavailable")

    # Prioriza imágenes solo-memoria para reservar las de raza a la etapa 2.
    memory_only = [a for a in memory_pool if not a.usable_for_breed]
    shared = [a for a in memory_pool if a.usable_for_breed]
    _rng.shuffle(memory_only)
    _rng.shuffle(shared)
    board_assets = (memory_only + shared)[: cfg["MEMORY_PAIRS"]]
    board_ids = {a.id for a in board_assets}

    breed_pool = [a for a in assets if a.usable_for_breed and a.id not in board_ids]
    if not breed_pool:
        raise ApiError("El juego no está disponible en este momento. Avisa al asesor.", status=503, code="content_unavailable")

    session = GameSession(participant_id=pid, event_code=cfg["EVENT_CODE"], status="created")
    db.session.add(session)

    positions = list(range(cfg["MEMORY_PAIRS"] * 2))
    _rng.shuffle(positions)
    for index, asset in enumerate(board_assets):
        pair_key = _token()
        for copy in range(2):
            session.cards.append(
                SessionMemoryCard(card_token=_token(), asset_id=asset.id, pair_key=pair_key, position=positions[index * 2 + copy])
            )

    for position, asset in enumerate(_order_breed_questions(breed_pool, cfg["BREED_QUESTIONS_PER_SESSION"])):
        options, correct_id = _build_options(asset, assets)
        session.answers.append(
            GameAnswer(question_token=_token(), asset_id=asset.id, position=position, options=options, correct_option_id=correct_id)
        )

    db.session.commit()
    return session


def _order_breed_questions(pool, limit: int):
    """Alterna perro/gato mientras haya de ambos; no repite imágenes ni (si se puede) razas seguidas."""
    by_species = {"dog": [a for a in pool if a.species == "dog"], "cat": [a for a in pool if a.species == "cat"]}
    for items in by_species.values():
        _rng.shuffle(items)
    order = []
    turn = _rng.choice(["dog", "cat"])
    while len(order) < limit and (by_species["dog"] or by_species["cat"]):
        if not by_species[turn]:
            turn = "cat" if turn == "dog" else "dog"
        items = by_species[turn]
        pick = 0
        if order and len(items) > 1 and items[0].breed_name_es == order[-1].breed_name_es:
            pick = 1
        order.append(items.pop(pick))
        turn = "cat" if turn == "dog" else "dog"
    return order


def _build_options(asset, all_assets) -> tuple[list[dict], str]:
    correct = asset.breed_name_es.strip()
    species = asset.species
    catalog_names = breed_names_by_species(all_assets)[species]
    candidates = [n for n in catalog_names if n.casefold() != correct.casefold()]
    _rng.shuffle(candidates)
    distractors = candidates[:2]
    if len(distractors) < 2:
        extra = [n for n in FALLBACK_BREEDS[species] if n.casefold() != correct.casefold() and n not in distractors]
        _rng.shuffle(extra)
        distractors += extra[: 2 - len(distractors)]
    labels = [correct] + distractors
    _rng.shuffle(labels)
    options = [{"id": _token()[:12], "label": label} for label in labels]
    correct_id = next(o["id"] for o in options if o["label"] == correct)
    return options, correct_id


# --------------------------------------------------------------------------- inicio

def start_session(session_id) -> GameSession:
    session = load_session(session_id, lock=True)
    if session.status == "created":
        session.status = "in_progress"
        session.started_at = clock.now()
        db.session.commit()
    elif session.status != "in_progress":
        raise ApiError("Esta partida ya terminó.", status=409, code="session_finished")
    return session


def _require_window(session: GameSession, start: float, end: float, message: str, code: str) -> float:
    if session.status != "in_progress":
        if session.status == "created":
            raise ApiError("La partida aún no ha comenzado.", status=409, code="session_not_started")
        raise ApiError("Esta partida ya terminó.", status=409, code="session_finished")
    elapsed = elapsed_seconds(session)
    grace = current_app.config["ACTION_GRACE_SECONDS"]
    if elapsed is None or elapsed < start - grace or elapsed > end + grace:
        raise ApiError(message, status=409, code=code, extra={"stage": current_stage(session)})
    return elapsed


# --------------------------------------------------------------------------- etapa 1

def memory_match(session_id, token_a: str, token_b: str) -> dict:
    session = load_session(session_id, lock=True)
    elapsed = _require_window(session, 0, stage_seconds(), "El tiempo de la etapa de memoria terminó.", "memory_stage_closed")

    if not isinstance(token_a, str) or not isinstance(token_b, str) or not token_a or not token_b:
        raise ApiError("Selecciona dos cartas.", status=422, code="invalid_cards")
    if token_a == token_b:
        raise ApiError("Selecciona dos cartas diferentes.", status=422, code="same_card")

    cards = {c.card_token: c for c in session.cards if c.card_token in (token_a, token_b)}
    if len(cards) != 2:
        raise ApiError("Las cartas no pertenecen a esta partida.", status=422, code="invalid_cards")
    card_a, card_b = cards[token_a], cards[token_b]
    if card_a.matched_at or card_b.matched_at:
        raise ApiError("Esa pareja ya fue encontrada.", status=409, code="already_matched")

    is_match = card_a.pair_key == card_b.pair_key
    points = 0
    if is_match:
        now = clock.now()
        card_a.matched_at = now
        card_b.matched_at = now
        points = current_app.config["POINTS_PER_PAIR"]

    db.session.add(
        MemoryAttempt(
            session_id=session.id, card_token_a=token_a, card_token_b=token_b, is_match=is_match,
            points_awarded=points, elapsed_ms=int(elapsed * 1000),
        )
    )
    db.session.flush()
    recompute_scores(session)
    db.session.commit()
    return {
        "match": is_match,
        "points_awarded": points,
        "pairs_found": session.pairs_found,
        "pairs_total": current_app.config["MEMORY_PAIRS"],
        "memory_score": session.memory_score,
        "total_score": session.total_score,
        "memory_complete": session.pairs_found == current_app.config["MEMORY_PAIRS"],
        "memory_end_ms": int(memory_end_seconds(session) * 1000),
    }


# --------------------------------------------------------------------------- etapa 2

def _public_question(session: GameSession, answer: GameAnswer) -> dict:
    return {
        "token": answer.question_token,
        "number": answer.position + 1,
        "image_url": url_for("game.question_image", token=answer.question_token),
        "options": [{"id": o["id"], "label": o["label"]} for o in answer.options],
    }


def _next_question(session: GameSession) -> GameAnswer | None:
    for answer in session.answers:
        if answer.answered_at is None:
            if answer.issued_at is None:
                answer.issued_at = clock.now()
            return answer
    return None


def get_breed_question(session_id) -> dict:
    session = load_session(session_id, lock=True)
    # Se permite pedir la pregunta un instante antes del cambio de etapa para mostrarla sin espera.
    _require_window(session, memory_end_seconds(session) - 2, total_seconds(), "La etapa de razas no está disponible.", "breed_stage_closed")
    answer = _next_question(session)
    db.session.commit()
    return {"question": _public_question(session, answer) if answer else None, "exhausted": answer is None}


def breed_answer(session_id, question_token: str, option_id: str) -> dict:
    session = load_session(session_id, lock=True)
    _require_window(session, memory_end_seconds(session), total_seconds(), "El tiempo de la etapa de razas terminó.", "breed_stage_closed")

    answer = next((a for a in session.answers if a.question_token == question_token), None)
    if answer is None or answer.issued_at is None:
        raise ApiError("La pregunta no pertenece a esta partida.", status=422, code="invalid_question")
    if answer.answered_at is not None:
        raise ApiError("Esta pregunta ya fue respondida.", status=409, code="already_answered")
    if not isinstance(option_id, str) or option_id not in {o["id"] for o in answer.options}:
        raise ApiError("Selecciona una de las opciones.", status=422, code="invalid_option")

    answer.selected_option_id = option_id
    answer.is_correct = option_id == answer.correct_option_id
    answer.points_awarded = current_app.config["POINTS_PER_BREED"] if answer.is_correct else 0
    answer.answered_at = clock.now()
    db.session.flush()
    recompute_scores(session)

    next_answer = _next_question(session)
    db.session.commit()
    correct_label = next(o["label"] for o in answer.options if o["id"] == answer.correct_option_id)
    return {
        "correct": answer.is_correct,
        "points_awarded": answer.points_awarded,
        # Se revela solo después de responder, como retroalimentación.
        "correct_label": correct_label,
        "breed_score": session.breed_score,
        "breed_correct": session.breed_correct,
        "breed_answered": session.breed_answered,
        "total_score": session.total_score,
        "next_question": _public_question(session, next_answer) if next_answer else None,
        "exhausted": next_answer is None,
    }


# --------------------------------------------------------------------------- cierre

def finish_session(session_id) -> GameSession:
    session = load_session(session_id, lock=True)
    if session.status in FINISHED_STATUSES:
        return session
    if session.status != "in_progress":
        raise ApiError("La partida no llegó a comenzar.", status=409, code="session_not_started")
    elapsed = elapsed_seconds(session)
    if elapsed < total_seconds() - current_app.config["ACTION_GRACE_SECONDS"]:
        raise ApiError(
            "La partida todavía está en curso.", status=409, code="session_in_progress",
            extra={"remaining_ms": int((total_seconds() - elapsed) * 1000)},
        )
    recompute_scores(session)
    session.status = "completed"
    session.completed_at = clock.now()
    db.session.commit()
    return session


def expire_stale_sessions() -> int:
    """Cierra partidas que nadie finalizó (p. ej. se cerró el navegador). Se llama desde ranking/admin."""
    now = clock.now()
    cutoff_started = now - timedelta(seconds=total_seconds()) - EXPIRE_AFTER
    stale = db.session.execute(
        select(GameSession).where(GameSession.status == "in_progress", GameSession.started_at < cutoff_started)
    ).scalars().all()
    for session in stale:
        recompute_scores(session)
        session.status = "expired"
        session.completed_at = as_utc(session.started_at) + timedelta(seconds=total_seconds())
    abandoned = db.session.execute(
        update(GameSession)
        .where(GameSession.status == "created", GameSession.created_at < now - ABANDON_AFTER)
        .values(status="abandoned")
    ).rowcount
    if stale or abandoned:
        db.session.commit()
    return len(stale)


# --------------------------------------------------------------------------- serialización

def public_state(session: GameSession) -> dict:
    """Estado visible para el navegador: sin pair_key ni respuestas correctas."""
    elapsed = elapsed_seconds(session)
    matched_cards = [c for c in session.cards if c.matched_at]
    return {
        "session_id": str(session.id),
        "status": session.status,
        "stage": current_stage(session),
        "stage_seconds": stage_seconds(),
        "total_seconds": total_seconds(),
        "memory_end_ms": int(memory_end_seconds(session) * 1000),
        "server_now": clock.now().isoformat(),
        "elapsed_ms": int(elapsed * 1000) if elapsed is not None else None,
        "cards": [
            {"token": c.card_token, "image_url": url_for("game.card_image", token=c.card_token), "matched": c.matched_at is not None}
            for c in session.cards
        ],
        "preload": [url_for("game.question_image", token=a.question_token) for a in session.answers],
        "pairs_total": current_app.config["MEMORY_PAIRS"],
        "pairs_found": len(matched_cards) // 2,
        "memory_score": session.memory_score,
        "breed_score": session.breed_score,
        "breed_correct": session.breed_correct,
        "breed_answered": session.breed_answered,
        "total_score": session.total_score,
    }
