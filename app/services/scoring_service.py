"""Puntaje calculado a partir de las acciones validadas y ranking anónimo del evento."""

from flask import current_app
from sqlalchemy import and_, case, func, select

from app.extensions import db
from app.models import GameAnswer, GameSession, Participant, SessionMemoryCard
from app.models.game_session import RANKED_STATUSES


def recompute_scores(session: GameSession) -> None:
    """Nunca se confía en puntajes enviados por el navegador: todo sale de la base."""
    cfg = current_app.config
    matched_cards = db.session.execute(
        select(func.count(SessionMemoryCard.id)).where(SessionMemoryCard.session_id == session.id, SessionMemoryCard.matched_at.is_not(None))
    ).scalar_one()
    answered, correct = db.session.execute(
        select(
            func.count(GameAnswer.id),
            func.coalesce(func.sum(case((GameAnswer.is_correct.is_(True), 1), else_=0)), 0),
        ).where(GameAnswer.session_id == session.id, GameAnswer.answered_at.is_not(None))
    ).one()
    session.pairs_found = matched_cards // 2
    session.memory_score = session.pairs_found * cfg["POINTS_PER_PAIR"]
    session.breed_answered = answered
    session.breed_correct = int(correct)
    session.breed_score = session.breed_correct * cfg["POINTS_PER_BREED"]
    session.total_score = session.memory_score + session.breed_score


def _best_sessions_subquery(event_code: str):
    """Mejor partida por participante. Desempate: total, aciertos de raza, fin más temprano."""
    order = (GameSession.total_score.desc(), GameSession.breed_correct.desc(), GameSession.completed_at.asc())
    per_participant = (
        select(
            GameSession.id.label("session_id"),
            GameSession.participant_id,
            GameSession.total_score,
            GameSession.memory_score,
            GameSession.breed_score,
            GameSession.pairs_found,
            GameSession.breed_correct,
            GameSession.breed_answered,
            GameSession.completed_at,
            func.row_number().over(partition_by=GameSession.participant_id, order_by=order).label("rn"),
        )
        .join(Participant, Participant.id == GameSession.participant_id)
        .where(GameSession.event_code == event_code, GameSession.status.in_(RANKED_STATUSES), Participant.anonymized_at.is_(None))
        .subquery()
    )
    best = select(per_participant).where(per_participant.c.rn == 1).subquery()
    ranked = select(
        best,
        func.row_number().over(
            order_by=(best.c.total_score.desc(), best.c.breed_correct.desc(), best.c.completed_at.asc())
        ).label("position"),
    ).subquery()
    return ranked


def ranking(limit: int = 10, include_private: bool = False) -> list[dict]:
    event_code = current_app.config["EVENT_CODE"]
    ranked = _best_sessions_subquery(event_code)
    columns = [ranked, Participant.player_number]
    if include_private:
        columns += [Participant.full_name, Participant.email, Participant.phone_e164]
    rows = db.session.execute(
        select(*columns).join(Participant, Participant.id == ranked.c.participant_id).order_by(ranked.c.position).limit(limit)
    ).mappings().all()
    result = []
    for row in rows:
        item = {
            "position": row["position"],
            "player": f"Jugador #{row['player_number']:04d}",
            "total_score": row["total_score"],
            "memory_score": row["memory_score"],
            "breed_score": row["breed_score"],
            "pairs_found": row["pairs_found"],
            "breed_correct": row["breed_correct"],
        }
        if include_private:
            item.update(
                session_id=str(row["session_id"]),
                full_name=row["full_name"],
                email=row["email"],
                phone=row["phone_e164"],
                breed_answered=row["breed_answered"],
                completed_at=row["completed_at"],
            )
        result.append(item)
    return result


def participant_position(participant_id) -> dict | None:
    event_code = current_app.config["EVENT_CODE"]
    ranked = _best_sessions_subquery(event_code)
    row = db.session.execute(select(ranked.c.position, ranked.c.session_id, ranked.c.total_score).where(ranked.c.participant_id == participant_id)).first()
    if row is None:
        return None
    total = db.session.execute(select(func.count()).select_from(ranked)).scalar_one()
    return {"position": row.position, "total_players": total, "best_session_id": str(row.session_id), "best_score": row.total_score}


def event_stats() -> dict:
    event_code = current_app.config["EVENT_CODE"]
    participants = db.session.execute(select(func.count(Participant.id)).where(Participant.event_code == event_code)).scalar_one()
    by_status = dict(
        db.session.execute(
            select(GameSession.status, func.count(GameSession.id)).where(GameSession.event_code == event_code).group_by(GameSession.status)
        ).all()
    )
    played = db.session.execute(
        select(
            func.count(GameSession.id),
            func.coalesce(func.avg(GameSession.total_score), 0),
            func.coalesce(func.max(GameSession.total_score), 0),
        ).where(and_(GameSession.event_code == event_code, GameSession.status.in_(RANKED_STATUSES)))
    ).one()
    return {
        "participants": participants,
        "sessions_by_status": by_status,
        "sessions_played": played[0],
        "average_score": round(float(played[1]), 1),
        "max_score": played[2],
    }
