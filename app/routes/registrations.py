from flask import Blueprint, jsonify

from app.extensions import limiter
from app.routes import json_body
from app.services.registration_service import register_participant

bp = Blueprint("registrations", __name__, url_prefix="/api")


@bp.post("/registrations")
# El stand usa un solo equipo (misma IP): límites holgados que solo frenan abuso automatizado.
@limiter.limit("30/minute;400/hour")
def create_registration():
    participant, is_new = register_participant(json_body())
    return (
        jsonify(
            {
                "participant_id": str(participant.id),
                "first_name": participant.first_name,
                "player": participant.public_alias,
                "returning": not is_new,
            }
        ),
        201 if is_new else 200,
    )
