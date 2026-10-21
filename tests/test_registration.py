import pytest

from app.extensions import db
from app.models import Participant, ParticipantConsent
from app.services.validation import normalize_email, normalize_name, normalize_phone


@pytest.mark.parametrize("name", ["María José Núñez", "O'Connor", "Ana-Lucía", "Zoë Ñañez", "Jo"])
def test_valid_names(name):
    assert normalize_name(name)[1] is None


@pytest.mark.parametrize("name", ["", "   ", "J", "Juan123", "Juan <script>", "x" * 101, "---"])
def test_invalid_names(name):
    assert normalize_name(name)[1] is not None


def test_email_normalized_lowercase():
    assert normalize_email("  Ana.Perez@Example.COM ") == ("ana.perez@example.com", None)
    assert normalize_email("ana@@example")[1] == "Ingresa un correo electrónico válido"


@pytest.mark.parametrize(
    "raw,expected",
    [("0991234567", "+593991234567"), ("099-123-4567", "+593991234567"), ("(099) 123 4567", "+593991234567"),
     ("+593991234567", "+593991234567"), ("+593 99 123 4567", "+593991234567")],
)
def test_valid_phones(raw, expected):
    assert normalize_phone(raw) == (expected, None)


@pytest.mark.parametrize("raw", ["", "022345678", "09912345", "099123456789", "+59322345678", "+1 555 123 4567", "abc"])
def test_invalid_phones(raw):
    assert normalize_phone(raw)[0] is None


def test_register_success(register):
    response = register()
    assert response.status_code == 201
    body = response.get_json()
    assert body["player"] == "Jugador #0001"
    assert body["first_name"] == "María"
    participant = db.session.get(Participant, __import__("uuid").UUID(body["participant_id"]))
    assert participant.email_normalized == "maria.nunez@example.com"
    assert participant.phone_e164 == "+593991234567"
    consent = participant.consents[0]
    assert consent.marketing_opt_in is False and consent.marketing_consent_at is None
    assert consent.terms_version == "1.0" and consent.privacy_version == "1.0"


def test_required_consents(register):
    response = register(accept_terms=False, accept_privacy=False)
    assert response.status_code == 422
    fields = response.get_json()["error"]["fields"]
    assert set(fields) == {"accept_terms", "accept_privacy"}
    assert db.session.query(Participant).count() == 0


def test_backend_repeats_validation(register):
    response = register(full_name="  ", email="no-es-correo", phone="12345")
    assert response.status_code == 422
    assert set(response.get_json()["error"]["fields"]) == {"full_name", "email", "phone"}


def test_duplicate_email_reuses_participant_and_keeps_consent_history(register):
    first = register().get_json()
    second = register(email="MARIA.NUNEZ@example.com", marketing_opt_in=True)
    assert second.status_code == 200
    assert second.get_json()["participant_id"] == first["participant_id"]
    assert second.get_json()["returning"] is True
    assert db.session.query(Participant).count() == 1
    consents = db.session.query(ParticipantConsent).all()
    assert len(consents) == 2
    assert sorted(c.marketing_opt_in for c in consents) == [False, True]


def test_player_numbers_are_sequential(register):
    assert register().get_json()["player"] == "Jugador #0001"
    assert register(email="otra@example.com").get_json()["player"] == "Jugador #0002"


def test_outdated_terms_version_is_rejected(register):
    response = register(terms_version="0.9")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "terms_version_mismatch"


def test_invalid_json(client):
    response = client.post("/api/registrations", data="hola", content_type="text/plain")
    assert response.status_code == 400
    assert "error" in response.get_json()
