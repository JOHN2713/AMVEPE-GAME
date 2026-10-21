"""Validación y normalización de los datos de registro. Debe coincidir con app/static/js/validation.js."""

import re
import unicodedata

from email_validator import EmailNotValidError, validate_email

NAME_MIN, NAME_MAX = 2, 100
NAME_EXTRA_CHARS = set(" '’-")
PHONE_STRIP_RE = re.compile(r"[\s\-().]")
PHONE_NATIONAL_RE = re.compile(r"^09\d{8}$")
PHONE_E164_RE = re.compile(r"^\+5939\d{8}$")

MSG_NAME_REQUIRED = "Ingresa tu nombre completo"
MSG_NAME_LENGTH = f"El nombre debe tener entre {NAME_MIN} y {NAME_MAX} caracteres"
MSG_NAME_CHARS = "El nombre solo puede contener letras, espacios, apóstrofes y guiones"
MSG_EMAIL = "Ingresa un correo electrónico válido"
MSG_PHONE = "Ingresa un celular ecuatoriano válido, por ejemplo 0991234567 o +593991234567"
MSG_TERMS = "Debes aceptar los Términos y Condiciones para participar"
MSG_PRIVACY = "Debes autorizar el tratamiento de datos para registrar tu participación"


def normalize_name(raw: str | None) -> tuple[str | None, str | None]:
    value = unicodedata.normalize("NFC", (raw or "")).strip()
    value = re.sub(r"\s+", " ", value)
    if not value:
        return None, MSG_NAME_REQUIRED
    if not (NAME_MIN <= len(value) <= NAME_MAX):
        return None, MSG_NAME_LENGTH
    for ch in value:
        if ch in NAME_EXTRA_CHARS:
            continue
        # Letras (L*) y marcas combinantes (M*) de cualquier alfabeto.
        if unicodedata.category(ch)[0] not in ("L", "M"):
            return None, MSG_NAME_CHARS
    if not any(unicodedata.category(ch)[0] == "L" for ch in value):
        return None, MSG_NAME_CHARS
    return value, None


def normalize_email(raw: str | None) -> tuple[str | None, str | None]:
    value = (raw or "").strip()
    if not value or len(value) > 254:
        return None, MSG_EMAIL
    try:
        result = validate_email(value, check_deliverability=False)
    except EmailNotValidError:
        return None, MSG_EMAIL
    return result.normalized.lower(), None


def normalize_phone(raw: str | None) -> tuple[str | None, str | None]:
    value = PHONE_STRIP_RE.sub("", (raw or "").strip())
    if PHONE_NATIONAL_RE.match(value):
        return "+593" + value[1:], None
    if PHONE_E164_RE.match(value):
        return value, None
    return None, MSG_PHONE


def validate_registration(payload: dict) -> tuple[dict, dict]:
    """Devuelve (datos_normalizados, errores_por_campo)."""
    errors: dict[str, str] = {}
    name, err = normalize_name(payload.get("full_name"))
    if err:
        errors["full_name"] = err
    email, err = normalize_email(payload.get("email"))
    if err:
        errors["email"] = err
    phone, err = normalize_phone(payload.get("phone"))
    if err:
        errors["phone"] = err
    if payload.get("accept_terms") is not True:
        errors["accept_terms"] = MSG_TERMS
    if payload.get("accept_privacy") is not True:
        errors["accept_privacy"] = MSG_PRIVACY

    data = {
        "full_name": name,
        "email": email,
        "phone_e164": phone,
        "marketing_opt_in": payload.get("marketing_opt_in") is True,
        "terms_version": str(payload.get("terms_version") or ""),
        "privacy_version": str(payload.get("privacy_version") or ""),
    }
    return data, errors
