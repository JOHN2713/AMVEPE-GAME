"""Reloj autoritativo del servidor. Las pruebas lo reemplazan con monkeypatch para simular el paso del tiempo."""

from app.models.base import utcnow


def now():
    return utcnow()
