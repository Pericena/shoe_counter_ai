"""Fábrica de la aplicación Flask de shoe_counter_ai."""
import os
import secrets

from flask import Flask, g, jsonify, request, send_from_directory, session
from sqlalchemy import text
from werkzeug.exceptions import HTTPException

from .common import ApiError
from .config import CONFIGS, validate
from .extensions import db, migrate

STORAGE_SUBDIRS = ("fotos", "procesadas", "importaciones", "exportaciones", "etiquetas", "registro", "derivados")

# Rutas de la API accesibles sin sesión. Todo lo demás bajo /api exige usuario (deny by default).
PUBLIC_API_PREFIXES = (
    "/api/health",
    "/api/auth/session",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/password-reset/",
    "/api/shop/",
    "/api/public/",
    # Autenticadas por su propio mecanismo (clave de integración / token de lectura BI) dentro de la ruta.
    "/api/integrations/inbound/",
    "/api/bi/datasets",
)
# Peticiones de máquina a máquina sin cookie de sesión: no aplica CSRF (se autentican con clave en cabecera).
CSRF_EXEMPT_PREFIXES = ("/api/integrations/inbound/",)
# Con contraseña temporal solo se permite gestionar la propia sesión.
PASSWORD_CHANGE_ALLOWED = ("/api/auth/",)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(config_name=None, overrides=None):
    config_name = config_name or os.environ.get("APP_ENV", "development")
    app = Flask(__name__, static_folder=None)
    app.config.from_object(CONFIGS[config_name])
    if overrides:
        app.config.update(overrides)
    validate(app.config)

    if app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    for sub in STORAGE_SUBDIRS:
        (app.config["STORAGE_DIR"] / sub).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))

    # Modelos (para Alembic) y rutas.
    from .ai import models as _ai_models  # noqa: F401
    from .audit import models as _audit_models  # noqa: F401
    from .auth import models as _auth_models  # noqa: F401
    from .files import models as _file_models  # noqa: F401
    from .imports import models as _import_models  # noqa: F401
    from .inventory import models as _inventory_models  # noqa: F401
    from .products import models as _product_models  # noqa: F401
    from .shop import models as _shop_models  # noqa: F401
    from .sales import models as _sales_models  # noqa: F401
    from .purchasing import models as _purchasing_models  # noqa: F401
    from .integrations import models as _integration_models  # noqa: F401
    from .notifications import models as _notification_models  # noqa: F401
    from .vision import models as _vision_models  # noqa: F401
    from .analytics import bi as _bi_models  # noqa: F401

    from .ai.cli import ai_cli
    from .ai.routes import bp as ai_bp
    from .audit.routes import bp as audit_bp
    from .auth.cli import users_cli
    from .auth.routes import bp as auth_bp
    from .auth.services import load_current_user
    from .auth.users_routes import bp as users_bp
    from .exports.routes import bp as exports_bp
    from .files.routes import bp as files_bp
    from .imports.routes import bp as imports_bp
    from .inventory.routes import bp as inventory_bp
    from .ocr.routes import bp as ocr_bp
    from .products.routes import bp as products_bp
    from .reports.routes import bp as reports_bp
    from .shop.routes import bp as shop_bp
    from .sales.routes import bp as sales_bp
    from .purchasing.routes import bp as purchasing_bp
    from .integrations.routes import bp as integrations_bp
    from .notifications.routes import bp as notifications_bp
    from .vision.routes import bp as vision_bp, vision_cli
    from .analytics.routes import bp as analytics_bp, bi_cli

    for blueprint in (auth_bp, users_bp, audit_bp, products_bp, inventory_bp, files_bp, ai_bp,
                      imports_bp, exports_bp, reports_bp, shop_bp, ocr_bp, sales_bp, purchasing_bp,
                      integrations_bp, notifications_bp, vision_bp, analytics_bp):
        app.register_blueprint(blueprint)
    for command in (users_cli, ai_cli, vision_cli, bi_cli):
        app.cli.add_command(command)

    @app.before_request
    def security_gate():
        g.user = load_current_user()
        path = request.path
        if not path.startswith("/api/"):
            return None
        if request.method in UNSAFE_METHODS and not path.startswith(CSRF_EXEMPT_PREFIXES):
            sent = request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf", "")
            if not expected or not secrets.compare_digest(sent, expected):
                raise ApiError("Token CSRF ausente o no válido. Recarga la página.", 403)
        if path.startswith(PUBLIC_API_PREFIXES):
            return None
        if g.user is None:
            raise ApiError("Debes iniciar sesión.", 401)
        if g.user.must_change_password and not path.startswith(PASSWORD_CHANGE_ALLOWED):
            raise ApiError("Debes cambiar tu contraseña temporal antes de continuar.", 403,
                           {"must_change_password": True})
        return None

    @app.get("/api/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            database = "ok"
        except Exception as error:  # noqa: BLE001 - el healthcheck informa, no propaga
            app.logger.warning("Healthcheck: base de datos no disponible: %s", error)
            database = "error"
        status = 200 if database == "ok" else 503
        return jsonify({"status": "ok" if status == 200 else "degraded", "database": database}), status

    web_dir = app.config["WEB_DIR"]

    @app.get("/")
    def index():
        return send_from_directory(web_dir, "index.html")

    @app.get("/<path:filename>")
    def web_files(filename):
        if filename.startswith("api/"):
            raise ApiError("Ruta no encontrada.", 404)
        # send_from_directory rechaza rutas fuera de web_dir (../).
        response = send_from_directory(web_dir, filename)
        # Revalidar siempre (ETag): tras una actualización el navegador no usa módulos JS antiguos.
        response.cache_control.no_cache = True
        return response

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        db.session.rollback()
        body = {"error": error.message}
        if error.details:
            body["details"] = error.details
        return jsonify(body), error.status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        messages = {404: "Ruta no encontrada.", 405: "Método no permitido.",
                    413: "El archivo supera el tamaño máximo permitido."}
        return jsonify({"error": messages.get(error.code, error.description)}), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        db.session.rollback()
        app.logger.exception("Error no controlado: %s", error)
        return jsonify({"error": "Error interno del servidor."}), 500

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    return app
