import json

from werkzeug.security import generate_password_hash

from tests.test_game import _correct_option, _match, _pairs


def _play(client, register, fake_clock, email, pairs_to_find=0, breed_correct=0):
    pid = register(email=email).get_json()["participant_id"]
    sid = client.post("/api/game/sessions", json={"participant_id": pid}).get_json()["session_id"]
    client.post(f"/api/game/sessions/{sid}/start", json={})
    for pair in _pairs(sid)[:pairs_to_find]:
        _match(client, sid, *pair)
    fake_clock.advance(46)
    q = client.get(f"/api/game/sessions/{sid}/breed-question").get_json()["question"]
    for _ in range(breed_correct):
        q = client.post(f"/api/game/sessions/{sid}/breed-answer", json={"question_token": q["token"], "option_id": _correct_option(q["token"])}).get_json()["next_question"]
    fake_clock.advance(45)
    client.post(f"/api/game/sessions/{sid}/finish", json={})
    fake_clock.advance(10)
    return sid


def test_ranking_is_anonymous_and_best_per_participant(client, register, fake_clock):
    _play(client, register, fake_clock, "a@example.com", pairs_to_find=1)
    _play(client, register, fake_clock, "a@example.com", pairs_to_find=3)  # mejor partida de A
    _play(client, register, fake_clock, "b@example.com", pairs_to_find=2)
    response = client.get("/api/ranking")
    body = response.get_json()
    rows = body["ranking"]
    assert [r["total_score"] for r in rows] == [30, 20]
    assert rows[0]["player"] == "Jugador #0001"
    raw = json.dumps(body)
    assert "example.com" not in raw and "+593" not in raw and "María" not in raw


def test_tiebreak_prefers_more_breed_correct(client, register, fake_clock):
    _play(client, register, fake_clock, "a@example.com", pairs_to_find=2, breed_correct=0)
    _play(client, register, fake_clock, "b@example.com", pairs_to_find=1, breed_correct=1)
    rows = client.get("/api/ranking").get_json()["ranking"]
    assert rows[0]["player"] == "Jugador #0002"


def test_admin_requires_login(client):
    assert client.get("/admin").status_code == 302
    assert client.get("/admin/export/participantes.csv").status_code == 302


def test_admin_login_and_export(app, client, register, fake_clock):
    app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash("una-clave-segura-123")
    _play(client, register, fake_clock, "a@example.com", pairs_to_find=1)
    client.get("/admin/login")
    with client.session_transaction() as s:
        token = s["csrf_token"]
    bad = client.post("/admin/login", data={"username": "admin", "password": "mala", "csrf_token": token})
    assert "incorrectos" in bad.get_data(as_text=True)
    ok = client.post("/admin/login", data={"username": "admin", "password": "una-clave-segura-123", "csrf_token": token})
    assert ok.status_code == 302
    assert client.get("/admin").status_code == 200
    csv_text = client.get("/admin/export/participantes.csv").get_data(as_text=True)
    assert "a@example.com" in csv_text and "+593991234567" in csv_text


def test_admin_post_requires_csrf(app, client):
    app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash("una-clave-segura-123")
    assert client.post("/admin/login", data={"username": "admin", "password": "una-clave-segura-123"}).status_code == 400


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.get_json()["database"] == "ok"


def test_credits_lists_only_playable_assets_without_breeds(client):
    from app.extensions import db
    from app.models import AnimalAsset

    db.session.add(AnimalAsset(species="dog", usage="breed", breed_name_es="Akita", provider="magnific",
                               source_url="https://www.magnific.com/free-photo/x_1.htm", local_path="img/x.webp",
                               license_status="approved", active=True, attribution="Imagen de Autor Visible en Magnific (Freepik)"))
    db.session.add(AnimalAsset(species="dog", usage="breed", breed_name_es="Akita", provider="magnific",
                               source_url="https://www.magnific.com/free-photo/y_2.htm", local_path="img/y.webp",
                               license_status="pending", active=False, attribution="Imagen de Autor Pendiente en Magnific (Freepik)"))
    db.session.commit()
    html = client.get("/creditos").get_data(as_text=True)
    assert "Autor Visible" in html and "Autor Pendiente" not in html
    assert "Akita" not in html
