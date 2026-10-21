from app.extensions import db
from app.models.base import new_uuid


class ParticipantConsent(db.Model):
    """Evidencia histórica de aceptación. Cada registro/re-registro agrega una fila; nunca se sobrescribe."""

    __tablename__ = "participant_consents"

    id = db.Column(db.Uuid, primary_key=True, default=new_uuid)
    participant_id = db.Column(db.Uuid, db.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False, index=True)
    terms_version = db.Column(db.String(30), nullable=False)
    terms_accepted_at = db.Column(db.DateTime(timezone=True), nullable=False)
    privacy_version = db.Column(db.String(30), nullable=False)
    privacy_accepted_at = db.Column(db.DateTime(timezone=True), nullable=False)
    marketing_opt_in = db.Column(db.Boolean, nullable=False, default=False)
    marketing_consent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    participant = db.relationship("Participant", back_populates="consents")
