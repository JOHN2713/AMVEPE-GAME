from flask import Blueprint, abort, current_app, jsonify, send_from_directory
from sqlalchemy import select

from app.extensions import db, limiter
from app.models import AnimalAsset, GameAnswer, SessionMemoryCard
from app.routes import json_body
from app.services import game_service
from app.services.scoring_service import participant_position

bp = Blueprint("game", __name__)

GAME_LIMIT = "300/minute"


@bp.post("/api/game/sessions")
@limiter.limit("30/minute")
def create_session():
    body = json_body()
    session = game_service.create_session(body.get("participant_id"))
    return jsonify(game_service.public_state(session)), 201


@bp.get("/api/game/sessions/<session_id>")
@limiter.limit(GAME_LIMIT)
def get_session(session_id):
    session = game_service.load_session(session_id)
    return jsonify(game_service.public_state(session))


@bp.post("/api/game/sessions/<session_id>/start")
@limiter.limit(GAME_LIMIT)
def start_session(session_id):
    session = game_service.start_session(session_id)
    return jsonify(game_service.public_state(session))


@bp.post("/api/game/sessions/<session_id>/memory-match")
@limiter.limit(GAME_LIMIT)
def memory_match(session_id):
    body = json_body()
    cards = body.get("cards")
    if not isinstance(cards, list) or len(cards) != 2:
        cards = [None, None]
    return jsonify(game_service.memory_match(session_id, cards[0], cards[1]))


@bp.get("/api/game/sessions/<session_id>/breed-question")
@limiter.limit(GAME_LIMIT)
def breed_question(session_id):
    return jsonify(game_service.get_breed_question(session_id))


@bp.post("/api/game/sessions/<session_id>/breed-answer")
@limiter.limit(GAME_LIMIT)
def breed_answer(session_id):
    body = json_body()
    return jsonify(game_service.breed_answer(session_id, body.get("question_token"), body.get("option_id")))


@bp.post("/api/game/sessions/<session_id>/finish")
@limiter.limit(GAME_LIMIT)
def finish(session_id):
    session = game_service.finish_session(session_id)
    return jsonify(_result_payload(session))


@bp.get("/api/game/sessions/<session_id>/result")
@limiter.limit(GAME_LIMIT)
def result(session_id):
    session = game_service.load_session(session_id)
    if session.status not in game_service.FINISHED_STATUSES:
        # El resultado solo se publica cuando el servidor dio por cerrada la partida.
        session = game_service.finish_session(session_id)
    return jsonify(_result_payload(session))


def _result_payload(session) -> dict:
    position = participant_position(session.participant_id) if session.status in ("completed", "expired") else None
    return {
        "session_id": str(session.id),
        "status": session.status,
        "player": session.participant.public_alias,
        "first_name": session.participant.first_name,
        "total_score": session.total_score,
        "memory_score": session.memory_score,
        "pairs_found": session.pairs_found,
        "pairs_total": current_app.config["MEMORY_PAIRS"],
        "breed_score": session.breed_score,
        "breed_correct": session.breed_correct,
        "breed_answered": session.breed_answered,
        "ranking": position and {
            "position": position["position"],
            "total_players": position["total_players"],
            "best_score": position["best_score"],
            "is_best": position["best_session_id"] == str(session.id),
        },
    }


# --------------------------------------------------------------------------- imágenes
# Se sirven por token opaco: la URL no revela la raza ni qué cartas forman pareja.

def _send_asset(asset_id):
    asset = db.session.get(AnimalAsset, asset_id)
    if asset is None:
        abort(404)
    response = send_from_directory(current_app.static_folder, asset.local_path, max_age=3600)
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@bp.get("/game/img/c/<token>")
def card_image(token):
    asset_id = db.session.execute(select(SessionMemoryCard.asset_id).where(SessionMemoryCard.card_token == token)).scalar_one_or_none()
    if asset_id is None:
        abort(404)
    return _send_asset(asset_id)


@bp.get("/game/img/q/<token>")
def question_image(token):
    asset_id = db.session.execute(select(GameAnswer.asset_id).where(GameAnswer.question_token == token)).scalar_one_or_none()
    if asset_id is None:
        abort(404)
    return _send_asset(asset_id)
