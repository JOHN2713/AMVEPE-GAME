from app.extensions import db
from app.models.base import new_uuid, utcnow

# created: tablero preparado, imágenes cargando · in_progress: reloj corriendo
# completed/expired: cerrada con puntaje validado · abandoned: nunca empezó · invalidated: anulada por administración
SESSION_STATUSES = ("created", "in_progress", "completed", "expired", "abandoned", "invalidated")
RANKED_STATUSES = ("completed", "expired")


class GameSession(db.Model):
    __tablename__ = "game_sessions"
    __table_args__ = (
        db.Index("ix_game_sessions_event_total", "event_code", db.text("total_score DESC")),
        db.Index("ix_game_sessions_participant_created", "participant_id", db.text("created_at DESC")),
    )

    id = db.Column(db.Uuid, primary_key=True, default=new_uuid)
    participant_id = db.Column(db.Uuid, db.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    event_code = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="created")
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    memory_score = db.Column(db.Integer, nullable=False, default=0)
    breed_score = db.Column(db.Integer, nullable=False, default=0)
    total_score = db.Column(db.Integer, nullable=False, default=0)
    pairs_found = db.Column(db.SmallInteger, nullable=False, default=0)
    breed_answered = db.Column(db.SmallInteger, nullable=False, default=0)
    breed_correct = db.Column(db.SmallInteger, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    participant = db.relationship("Participant", back_populates="sessions")
    cards = db.relationship("SessionMemoryCard", back_populates="session", order_by="SessionMemoryCard.position", cascade="all, delete-orphan")
    answers = db.relationship("GameAnswer", back_populates="session", order_by="GameAnswer.position", cascade="all, delete-orphan")
