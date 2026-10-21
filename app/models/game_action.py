from app.extensions import db
from app.models.base import JSONType, new_uuid, utcnow


class SessionMemoryCard(db.Model):
    """Estado privado del tablero. pair_key nunca sale por la API pública."""

    __tablename__ = "session_memory_cards"
    __table_args__ = (db.UniqueConstraint("session_id", "position"),)

    id = db.Column(db.Uuid, primary_key=True, default=new_uuid)
    session_id = db.Column(db.Uuid, db.ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    card_token = db.Column(db.String(64), nullable=False, unique=True)
    asset_id = db.Column(db.Uuid, db.ForeignKey("animal_assets.id"), nullable=False)
    pair_key = db.Column(db.String(64), nullable=False)
    position = db.Column(db.SmallInteger, nullable=False)
    matched_at = db.Column(db.DateTime(timezone=True), nullable=True)

    session = db.relationship("GameSession", back_populates="cards")
    asset = db.relationship("AnimalAsset")


class MemoryAttempt(db.Model):
    """Bitácora de comparaciones de cartas (trazabilidad y detección de abuso)."""

    __tablename__ = "memory_attempts"

    id = db.Column(db.Uuid, primary_key=True, default=new_uuid)
    session_id = db.Column(db.Uuid, db.ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    card_token_a = db.Column(db.String(64), nullable=False)
    card_token_b = db.Column(db.String(64), nullable=False)
    is_match = db.Column(db.Boolean, nullable=False)
    points_awarded = db.Column(db.Integer, nullable=False, default=0)
    elapsed_ms = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class GameAnswer(db.Model):
    """Pregunta de raza preparada para la sesión y, cuando se responde, su resultado.

    options guarda [{"id": token_opaco, "label": "Nombre"}]; correct_option_id es privado.
    """

    __tablename__ = "game_answers"
    __table_args__ = (db.UniqueConstraint("session_id", "position"),)

    id = db.Column(db.Uuid, primary_key=True, default=new_uuid)
    session_id = db.Column(db.Uuid, db.ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_token = db.Column(db.String(64), nullable=False, unique=True)
    asset_id = db.Column(db.Uuid, db.ForeignKey("animal_assets.id"), nullable=False)
    position = db.Column(db.SmallInteger, nullable=False)
    options = db.Column(JSONType, nullable=False)
    correct_option_id = db.Column(db.String(64), nullable=False)
    issued_at = db.Column(db.DateTime(timezone=True), nullable=True)
    selected_option_id = db.Column(db.String(64), nullable=True)
    is_correct = db.Column(db.Boolean, nullable=True)
    points_awarded = db.Column(db.Integer, nullable=False, default=0)
    answered_at = db.Column(db.DateTime(timezone=True), nullable=True)

    session = db.relationship("GameSession", back_populates="answers")
    asset = db.relationship("AnimalAsset")
