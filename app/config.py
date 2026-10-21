import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{BASE_DIR / 'instance' / 'dev.sqlite3'}"
    # Railway entrega postgres:// o postgresql://; SQLAlchemy necesita el driver psycopg (v3).
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


class Config:
    APP_ENV = os.environ.get("APP_ENV", os.environ.get("FLASK_ENV", "development"))
    IS_PRODUCTION = APP_ENV == "production"

    SECRET_KEY = os.environ.get("SECRET_KEY") or ("dev-only-secret" if not IS_PRODUCTION else None)
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    JSON_SORT_KEYS = False
    MAX_CONTENT_LENGTH = 64 * 1024

    EVENT_CODE = os.environ.get("EVENT_CODE", "AMVEPE2026")
    TERMS_VERSION = os.environ.get("TERMS_VERSION", "1.0")
    PRIVACY_VERSION = os.environ.get("PRIVACY_VERSION", "1.0")
    PUBLIC_DEMO_URL = os.environ.get("PUBLIC_DEMO_URL", "https://example.com/perseo-pets-demo")

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")

    PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
    MAGNIFIC_API_KEY = os.environ.get("MAGNIFIC_API_KEY", "")
    MAGNIFIC_API_BASE = os.environ.get("MAGNIFIC_API_BASE", "https://api.magnific.com")

    # Reglas del juego
    STAGE_SECONDS = int(os.environ.get("STAGE_SECONDS", "45"))
    MEMORY_PAIRS = 6
    POINTS_PER_PAIR = 10
    POINTS_PER_BREED = 10
    BREED_QUESTIONS_PER_SESSION = int(os.environ.get("BREED_QUESTIONS_PER_SESSION", "24"))
    # Tolerancia de red para acciones que llegan justo en el límite de una etapa.
    ACTION_GRACE_SECONDS = float(os.environ.get("ACTION_GRACE_SECONDS", "0.75"))
    # 0 = partidas ilimitadas por participante.
    MAX_SESSIONS_PER_PARTICIPANT = int(os.environ.get("MAX_SESSIONS_PER_PARTICIPANT", "0"))
    # Las imágenes de prueba (placeholder) solo se permiten fuera de producción.
    ALLOW_PLACEHOLDER_ASSETS = _bool("ALLOW_PLACEHOLDER_ASSETS", default=not IS_PRODUCTION)

    ANIMALS_DIR = BASE_DIR / "app" / "static" / "img" / "animals"

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12


class TestConfig(Config):
    TESTING = True
    APP_ENV = "testing"
    IS_PRODUCTION = False
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    RATELIMIT_ENABLED = False
    ALLOW_PLACEHOLDER_ASSETS = True
    SESSION_COOKIE_SECURE = False
