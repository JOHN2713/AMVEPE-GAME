from flask import request

from app.services.errors import ApiError


def json_body() -> dict:
    """Cuerpo JSON obligatorio en las peticiones POST de la API."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("La solicitud no es válida.", status=400, code="invalid_json")
    return data
