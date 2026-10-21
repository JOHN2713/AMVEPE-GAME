from flask import Blueprint, jsonify, request

from app.extensions import limiter
from app.services.game_service import expire_stale_sessions
from app.services.scoring_service import ranking as ranking_rows

bp = Blueprint("ranking", __name__, url_prefix="/api")


@bp.get("/ranking")
@limiter.limit("120/minute")
def get_ranking():
    limit = min(max(request.args.get("limit", default=10, type=int), 1), 50)
    expire_stale_sessions()
    # Solo alias anónimos y puntajes: nunca nombre, correo ni celular.
    return jsonify({"ranking": ranking_rows(limit=limit)})
