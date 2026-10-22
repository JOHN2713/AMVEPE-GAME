import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import db, limiter, migrate
from app.services.errors import ApiError

load_dotenv()

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


def create_app(config_object: str = "app.config.Config") -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY es obligatorio en producción.")
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        # Vercel y otros entornos serverless tienen el disco de solo lectura; la app no lo necesita en producción.
        pass

    # Railway termina TLS en su proxy: respetar X-Forwarded-For/Proto para IP real y URLs https.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Las líneas de acceso de werkzeug incluyen rutas con session_id; se dejan solo en desarrollo.
    if app.config["IS_PRODUCTION"]:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    limiter.init_app(app)

    from app import models  # noqa: F401  (registra los modelos para Alembic)
    from app.routes.admin import bp as admin_bp
    from app.routes.game import bp as game_bp
    from app.routes.pages import bp as pages_bp
    from app.routes.ranking import bp as ranking_bp
    from app.routes.registrations import bp as registrations_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(game_bp)
    app.register_blueprint(ranking_bp)
    app.register_blueprint(admin_bp)

    from app.cli import register_cli

    register_cli(app)
    _register_error_handlers(app)
    _register_security_headers(app)

    @app.context_processor
    def inject_globals():
        return {
            "event_code": app.config["EVENT_CODE"],
            "terms_version": app.config["TERMS_VERSION"],
            "privacy_version": app.config["PRIVACY_VERSION"],
        }

    return app


def _wants_json() -> bool:
    return request.path.startswith("/api/") or request.path == "/health"


def _register_error_handlers(app: Flask) -> None:
    log = logging.getLogger("app.errors")

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return jsonify(err.to_dict()), err.status

    @app.errorhandler(429)
    def handle_rate_limit(_err):
        message = "Demasiadas solicitudes. Espera un momento e inténtalo de nuevo."
        if _wants_json():
            return jsonify({"error": {"code": "rate_limited", "message": message}}), 429
        return render_template("error.html", title="Un momento", message=message), 429

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        messages = {404: "No encontramos lo que buscas.", 405: "Método no permitido.", 413: "La solicitud es demasiado grande."}
        message = messages.get(err.code, "La solicitud no es válida.")
        if _wants_json():
            return jsonify({"error": {"code": f"http_{err.code}", "message": message}}), err.code
        return render_template("error.html", title="Ups", message=message), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Se registra el tipo y la ruta, nunca el cuerpo de la petición (puede contener datos personales).
        log.exception("Error no controlado en %s %s: %s", request.method, request.path, type(err).__name__)
        db.session.rollback()
        message = "Ocurrió un problema inesperado. Inténtalo de nuevo o avisa al asesor."
        if _wants_json():
            return jsonify({"error": {"code": "server_error", "message": message}}), 500
        return render_template("error.html", title="Ups", message=message), 500


def _register_security_headers(app: Flask) -> None:
    @app.after_request
    def set_headers(response):
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if app.config["IS_PRODUCTION"]:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith(("/api/", "/admin")):
            response.headers["Cache-Control"] = "no-store"
        return response
