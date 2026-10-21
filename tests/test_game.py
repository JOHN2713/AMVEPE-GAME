import json
import uuid
from collections import defaultdict

from app.extensions import db
from app.models import GameAnswer, GameSession, SessionMemoryCard


def _pairs(session_id):
    groups = defaultdict(list)
    for card in db.session.query(SessionMemoryCard).filter_by(session_id=uuid.UUID(session_id)):
        groups[card.pair_key].append(card.card_token)
    return list(groups.values())


def _match(client, sid, a, b):
    return client.post(f"/api/game/sessions/{sid}/memory-match", json={"cards": [a, b]})


def _correct_option(question_token):
    return db.session.query(GameAnswer).filter_by(question_token=question_token).one().correct_option_id


def test_board_has_12_cards_6_pairs_and_hides_secrets(client, register, fake_clock):
    pid = register().get_json()["participant_id"]
    response = client.post("/api/game/sessions", json={"participant_id": pid})
    assert response.status_code == 201
    state = response.get_json()
    assert len(state["cards"]) == 12
    pairs = _pairs(state["session_id"])
    assert len(pairs) == 6 and all(len(p) == 2 for p in pairs)
    raw = json.dumps(state)
    assert "pair_key" not in raw and "correct_option" not in raw
    # Las URLs de imagen son por carta: no revelan qué cartas forman pareja.
    assert len({c["image_url"] for c in state["cards"]}) == 12
    assert state["status"] == "created" and state["stage"] == "ready"


def test_only_approved_assets_are_used(client, register, fake_clock):
    pid = register().get_json()["participant_id"]
    sid = client.post("/api/game/sessions", json={"participant_id": pid}).get_json()["session_id"]
    session = db.session.get(GameSession, uuid.UUID(sid))
    used = {c.asset for c in session.cards} | {a.asset for a in session.answers}
    assert all(a.license_status == "approved" and a.active for a in used)
    # Las imágenes del tablero no se repiten en las preguntas de raza.
    assert not ({c.asset_id for c in session.cards} & {a.asset_id for a in session.answers})


def test_matching_pairs_scores_once(client, started_session, fake_clock):
    sid = started_session["session_id"]
    pairs = _pairs(sid)
    fake_clock.advance(5)
    result = _match(client, sid, *pairs[0]).get_json()
    assert result["match"] is True and result["points_awarded"] == 10 and result["total_score"] == 10
    again = _match(client, sid, *pairs[0])
    assert again.status_code == 409 and again.get_json()["error"]["code"] == "already_matched"
    assert db.session.get(GameSession, uuid.UUID(sid)).memory_score == 10


def test_mismatch_scores_zero(client, started_session, fake_clock):
    sid = started_session["session_id"]
    pairs = _pairs(sid)
    result = _match(client, sid, pairs[0][0], pairs[1][0]).get_json()
    assert result["match"] is False and result["points_awarded"] == 0 and result["total_score"] == 0


def test_same_card_twice_rejected(client, started_session, fake_clock):
    sid = started_session["session_id"]
    token = _pairs(sid)[0][0]
    response = _match(client, sid, token, token)
    assert response.status_code == 422 and response.get_json()["error"]["code"] == "same_card"


def test_cards_from_other_session_rejected(client, register, started_session, fake_clock):
    other_pid = register(email="otro@example.com").get_json()["participant_id"]
    other = client.post("/api/game/sessions", json={"participant_id": other_pid}).get_json()
    a, b = _pairs(other["session_id"])[0]
    assert _match(client, started_session["session_id"], a, b).status_code == 422


def test_memory_stage_closes_at_45_seconds(client, started_session, fake_clock):
    sid = started_session["session_id"]
    pairs = _pairs(sid)
    fake_clock.advance(46)
    response = _match(client, sid, *pairs[0])
    assert response.status_code == 409 and response.get_json()["error"]["code"] == "memory_stage_closed"


def test_breed_stage_not_available_during_memory(client, started_session, fake_clock):
    fake_clock.advance(10)
    response = client.get(f"/api/game/sessions/{started_session['session_id']}/breed-question")
    assert response.status_code == 409


def test_breed_question_flow(client, started_session, fake_clock):
    sid = started_session["session_id"]
    fake_clock.advance(46)
    q = client.get(f"/api/game/sessions/{sid}/breed-question").get_json()["question"]
    assert len(q["options"]) == 3
    assert len({o["label"] for o in q["options"]}) == 3
    assert "correct" not in json.dumps(q)  # ni correct_option_id ni etiqueta de respuesta
    # Pedir la pregunta de nuevo (p. ej. recarga) devuelve la misma.
    assert client.get(f"/api/game/sessions/{sid}/breed-question").get_json()["question"]["token"] == q["token"]

    correct = _correct_option(q["token"])
    result = client.post(f"/api/game/sessions/{sid}/breed-answer", json={"question_token": q["token"], "option_id": correct}).get_json()
    assert result["correct"] is True and result["points_awarded"] == 10 and result["total_score"] == 10

    twice = client.post(f"/api/game/sessions/{sid}/breed-answer", json={"question_token": q["token"], "option_id": correct})
    assert twice.status_code == 409 and twice.get_json()["error"]["code"] == "already_answered"

    q2 = result["next_question"]
    wrong = next(o["id"] for o in q2["options"] if o["id"] != _correct_option(q2["token"]))
    result2 = client.post(f"/api/game/sessions/{sid}/breed-answer", json={"question_token": q2["token"], "option_id": wrong}).get_json()
    assert result2["correct"] is False and result2["points_awarded"] == 0
    assert result2["total_score"] == 10 and result2["breed_answered"] == 2


def test_distractors_same_species(client, started_session, fake_clock):
    sid = started_session["session_id"]
    dog_names = {"Beagle", "Pug", "Dálmata", "Bóxer", "Chihuahua", "Schnauzer"}
    for answer in db.session.get(GameSession, uuid.UUID(sid)).answers:
        labels = {o["label"] for o in answer.options}
        if answer.asset.species == "dog":
            assert labels <= dog_names
        else:
            assert not (labels & dog_names)


def test_breed_stage_closes_at_90_seconds(client, started_session, fake_clock):
    sid = started_session["session_id"]
    fake_clock.advance(46)
    q = client.get(f"/api/game/sessions/{sid}/breed-question").get_json()["question"]
    fake_clock.advance(45)
    response = client.post(f"/api/game/sessions/{sid}/breed-answer", json={"question_token": q["token"], "option_id": _correct_option(q["token"])})
    assert response.status_code == 409


def test_finish_flow_is_idempotent(client, started_session, fake_clock):
    sid = started_session["session_id"]
    pairs = _pairs(sid)
    fake_clock.advance(3)
    _match(client, sid, *pairs[0])
    _match(client, sid, *pairs[1])
    fake_clock.advance(44)
    q = client.get(f"/api/game/sessions/{sid}/breed-question").get_json()["question"]
    client.post(f"/api/game/sessions/{sid}/breed-answer", json={"question_token": q["token"], "option_id": _correct_option(q["token"])})

    early = client.post(f"/api/game/sessions/{sid}/finish", json={})
    assert early.status_code == 409 and early.get_json()["error"]["code"] == "session_in_progress"

    fake_clock.advance(45)
    first = client.post(f"/api/game/sessions/{sid}/finish", json={}).get_json()
    second = client.post(f"/api/game/sessions/{sid}/finish", json={}).get_json()
    assert first["status"] == "completed"
    assert first["total_score"] == 30 == first["memory_score"] + first["breed_score"]
    assert first["pairs_found"] == 2 and first["breed_correct"] == 1
    assert second["total_score"] == first["total_score"]
    assert first["ranking"]["position"] == 1


def test_start_is_idempotent_and_does_not_reset_clock(client, started_session, fake_clock):
    sid = started_session["session_id"]
    fake_clock.advance(20)
    state = client.post(f"/api/game/sessions/{sid}/start", json={}).get_json()
    assert 19000 <= state["elapsed_ms"] <= 21000
    assert state["stage"] == "memory"


def test_unknown_session_returns_404(client):
    assert client.get("/api/game/sessions/no-existe").status_code == 404
    assert client.get(f"/api/game/sessions/{uuid.uuid4()}").status_code == 404


def test_create_session_unknown_participant(client):
    response = client.post("/api/game/sessions", json={"participant_id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_placeholders_hidden_when_real_content_exists(app):
    from app.models import AnimalAsset
    from app.services.catalog_service import playable_assets

    db.session.add(AnimalAsset(species="other", usage="memory", provider="placeholder", source_url="placeholder://x",
                               local_path="img/ph.svg", license_status="approved", active=True))
    db.session.commit()
    assert all(a.provider != "placeholder" for a in playable_assets())


def test_completing_board_early_starts_breed_stage_immediately(client, started_session, fake_clock):
    sid = started_session["session_id"]
    pairs = _pairs(sid)
    fake_clock.advance(5)
    for pair in pairs[:5]:
        _match(client, sid, *pair)
    fake_clock.advance(15)  # última pareja a los 20 s
    last = _match(client, sid, *pairs[5]).get_json()
    assert last["memory_complete"] is True and last["memory_end_ms"] == 20000

    fake_clock.advance(0.5)
    state = client.get(f"/api/game/sessions/{sid}").get_json()
    assert state["stage"] == "breed" and state["memory_end_ms"] == 20000
    q = client.get(f"/api/game/sessions/{sid}/breed-question").get_json()["question"]
    answer = client.post(f"/api/game/sessions/{sid}/breed-answer", json={"question_token": q["token"], "option_id": _correct_option(q["token"])})
    assert answer.status_code == 200 and answer.get_json()["total_score"] == 70

    # La partida sigue terminando a los 90 s desde el inicio.
    fake_clock.advance(50)
    assert client.post(f"/api/game/sessions/{sid}/finish", json={}).status_code == 409
    fake_clock.advance(20)
    assert client.post(f"/api/game/sessions/{sid}/finish", json={}).get_json()["status"] == "completed"


def test_incomplete_board_keeps_45_second_memory_stage(client, started_session, fake_clock):
    sid = started_session["session_id"]
    _match(client, sid, *_pairs(sid)[0])
    fake_clock.advance(30)
    state = client.get(f"/api/game/sessions/{sid}").get_json()
    assert state["stage"] == "memory" and state["memory_end_ms"] == 45000
    assert client.get(f"/api/game/sessions/{sid}/breed-question").status_code == 409
