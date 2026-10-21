from sqlalchemy import UniqueConstraint

from app.extensions import db
from app.models.base import new_uuid, utcnow


class Participant(db.Model):
    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint("event_code", "email_normalized"),
        UniqueConstraint("event_code", "player_number"),
    )

    id = db.Column(db.Uuid, primary_key=True, default=new_uuid)
    event_code = db.Column(db.String(50), nullable=False)
    # Número público y anónimo para el ranking: "Jugador #0042".
    player_number = db.Column(db.Integer, nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    email_normalized = db.Column(db.String(254), nullable=False)
    phone_e164 = db.Column(db.String(16), nullable=False)
    anonymized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    consents = db.relationship("ParticipantConsent", back_populates="participant", order_by="ParticipantConsent.terms_accepted_at")
    sessions = db.relationship("GameSession", back_populates="participant")

    @property
    def public_alias(self) -> str:
        return f"Jugador #{self.player_number:04d}"

    @property
    def first_name(self) -> str:
        return self.full_name.split()[0] if self.full_name else ""
