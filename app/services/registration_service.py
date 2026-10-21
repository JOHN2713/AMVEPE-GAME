from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Participant, ParticipantConsent
from app.models.base import utcnow
from app.services.errors import ApiError
from app.services.validation import validate_registration


def register_participant(payload: dict) -> tuple[Participant, bool]:
    """Crea o recupera al participante del evento y registra la evidencia de consentimiento.

    Devuelve (participante, es_nuevo).
    """
    cfg = current_app.config
    data, errors = validate_registration(payload)
    if errors:
        raise ApiError("Revisa los datos marcados", status=422, code="validation_error", fields=errors)

    if data["terms_version"] != cfg["TERMS_VERSION"] or data["privacy_version"] != cfg["PRIVACY_VERSION"]:
        raise ApiError(
            "Las condiciones se actualizaron. Recarga la página para leer la versión vigente.",
            status=409,
            code="terms_version_mismatch",
        )

    event_code = cfg["EVENT_CODE"]
    now = utcnow()

    # Reintento corto por si dos registros simultáneos chocan en player_number o en el correo.
    for _attempt in range(3):
        participant = db.session.execute(
            select(Participant).where(Participant.event_code == event_code, Participant.email_normalized == data["email"])
        ).scalar_one_or_none()
        is_new = participant is None
        if is_new:
            next_number = (
                db.session.execute(select(func.coalesce(func.max(Participant.player_number), 0)).where(Participant.event_code == event_code)).scalar_one()
                + 1
            )
            participant = Participant(event_code=event_code, player_number=next_number, email_normalized=data["email"])
            db.session.add(participant)
        participant.full_name = data["full_name"]
        participant.email = data["email"]
        participant.phone_e164 = data["phone_e164"]
        participant.updated_at = now

        db.session.add(
            ParticipantConsent(
                participant=participant,
                terms_version=cfg["TERMS_VERSION"],
                terms_accepted_at=now,
                privacy_version=cfg["PRIVACY_VERSION"],
                privacy_accepted_at=now,
                marketing_opt_in=data["marketing_opt_in"],
                marketing_consent_at=now if data["marketing_opt_in"] else None,
            )
        )
        try:
            db.session.commit()
            return participant, is_new
        except IntegrityError:
            db.session.rollback()

    raise ApiError("No pudimos completar el registro. Inténtalo nuevamente.", status=503, code="registration_conflict")
