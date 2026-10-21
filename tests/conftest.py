from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.extensions import db
from app.models import AnimalAsset
from app.services import clock


class FakeClock:
    def __init__(self):
        self.current = datetime(2026, 11, 5, 15, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.current

    def advance(self, seconds: float):
        self.current += timedelta(seconds=seconds)


@pytest.fixture()
def fake_clock(monkeypatch):
    fc = FakeClock()
    monkeypatch.setattr(clock, "now", fc)
    return fc


@pytest.fixture()
def app():
    app = create_app("app.config.TestConfig")
    with app.app_context():
        db.create_all()
        _seed_assets()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _seed_assets():
    for i in range(6):
        db.session.add(AnimalAsset(species="other", usage="memory", provider="test", source_url=f"t://m{i}",
                                   local_path=f"img/m{i}.webp", license_status="approved", active=True))
    dog_breeds = ["Beagle", "Pug", "Dálmata", "Bóxer", "Chihuahua", "Schnauzer"]
    cat_breeds = ["Persa", "Siamés", "Ragdoll", "Bengalí"]
    for i, breed in enumerate(dog_breeds):
        db.session.add(AnimalAsset(species="dog", usage="breed", breed_name_es=breed, provider="test", source_url=f"t://d{i}",
                                   local_path=f"img/d{i}.webp", license_status="approved", active=True))
    for i, breed in enumerate(cat_breeds):
        db.session.add(AnimalAsset(species="cat", usage="breed", breed_name_es=breed, provider="test", source_url=f"t://c{i}",
                                   local_path=f"img/c{i}.webp", license_status="approved", active=True))
    # No aprobadas: nunca deben aparecer en partidas.
    db.session.add(AnimalAsset(species="dog", usage="breed", breed_name_es="Rottweiler", provider="test", source_url="t://pending",
                               local_path="img/p.webp", license_status="pending", active=False))
    db.session.commit()


VALID_REGISTRATION = {
    "full_name": "María José Núñez",
    "email": "  Maria.Nunez@Example.COM ",
    "phone": "099 123 4567",
    "accept_terms": True,
    "accept_privacy": True,
    "marketing_opt_in": False,
    "terms_version": "1.0",
    "privacy_version": "1.0",
}


@pytest.fixture()
def register(client):
    def _register(**overrides):
        payload = {**VALID_REGISTRATION, **overrides}
        return client.post("/api/registrations", json=payload)

    return _register


@pytest.fixture()
def started_session(client, register, fake_clock):
    participant_id = register().get_json()["participant_id"]
    state = client.post("/api/game/sessions", json={"participant_id": participant_id}).get_json()
    client.post(f"/api/game/sessions/{state['session_id']}/start", json={})
    return state
