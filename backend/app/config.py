"""Configuración por entorno. Todo valor sensible llega por variables de entorno."""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def _env(name, default=None):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name, default=False):
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "si", "sí", "on")


def _database_url():
    """Las rutas SQLite relativas se resuelven desde la raíz del proyecto (no desde instance/)."""
    url = _env("DATABASE_URL")
    prefix = "sqlite:///"
    if url and url.startswith(prefix) and not Path(url[len(prefix):]).is_absolute():
        path = (BASE_DIR / url[len(prefix):]).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return prefix + path.as_posix()
    return url


class Config:
    SECRET_KEY = _env("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    STORAGE_DIR = Path(_env("STORAGE_DIR", str(BASE_DIR / "storage")))
    WEB_DIR = Path(_env("WEB_DIR", str(BASE_DIR / "web")))
    MAX_CONTENT_LENGTH = int(_env("MAX_UPLOAD_MB", "15")) * 1024 * 1024
    JSON_SORT_KEYS = False
    TESTING = False

    # Sesión: cookie firmada, inaccesible desde JS, SameSite=Lax.
    # SESSION_COOKIE_SECURE=true es obligatorio detrás de HTTPS.
    SESSION_COOKIE_NAME = "shoe_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(_env("SESSION_HOURS", "8")))

    # Límite de intentos de inicio de sesión.
    LOGIN_MAX_FAILURES_USER = int(_env("LOGIN_MAX_FAILURES_USER", "5"))
    LOGIN_MAX_FAILURES_IP = int(_env("LOGIN_MAX_FAILURES_IP", "20"))
    LOGIN_LOCK_MINUTES = int(_env("LOGIN_LOCK_MINUTES", "15"))
    ORDERS_PER_IP_PER_HOUR = int(_env("ORDERS_PER_IP_PER_HOUR", "10"))

    # Recuperación de contraseña por correo: solo si SMTP está configurado.
    SMTP_HOST = _env("SMTP_HOST")
    SMTP_PORT = int(_env("SMTP_PORT", "587"))
    SMTP_USER = _env("SMTP_USER")
    SMTP_PASSWORD = _env("SMTP_PASSWORD")
    SMTP_FROM = _env("SMTP_FROM")
    SMTP_STARTTLS = _env_bool("SMTP_STARTTLS", True)
    PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "http://localhost:8088")
    PASSWORD_RESET_MINUTES = int(_env("PASSWORD_RESET_MINUTES", "30"))

    # Detector de zapatos (ONNX). Carpeta con <versión>/model.onnx + metadata.json.
    AI_MODELS_DIR = Path(_env("AI_MODELS_DIR", str(BASE_DIR / "modelo" / "exportados")))
    AI_MODEL_VERSION = _env("AI_MODEL_VERSION")  # vacío = la versión más reciente disponible
    # Vacío = usar "recommended_confidence" del metadata.json del modelo (elegido en validación); 0.35 si no hay.
    AI_CONFIDENCE = float(_env("AI_CONFIDENCE")) if _env("AI_CONFIDENCE") else None
    AI_IOU = float(_env("AI_IOU", "0.5"))

    # Si hay un proxy HTTPS delante (Fase de despliegue), confiar en X-Forwarded-*.
    TRUST_PROXY = _env_bool("TRUST_PROXY", False)


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "solo-para-pruebas"
    SQLALCHEMY_DATABASE_URI = _env("TEST_DATABASE_URL", "sqlite://")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    SMTP_HOST = None
    AI_MODELS_DIR = Path("/no-existe")


class ProductionConfig(Config):
    DEBUG = False


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def validate(config):
    """Falla al arrancar si falta configuración obligatoria, en vez de usar valores inseguros."""
    missing = [key for key in ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI") if not config.get(key)]
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno obligatorias: "
            + ", ".join("DATABASE_URL" if k == "SQLALCHEMY_DATABASE_URI" else k for k in missing)
            + ". Copia .env.example a .env y complétalo."
        )
    if not config.get("TESTING") and config["SECRET_KEY"] in ("cambia-esta-clave", "dev", "secret"):
        raise RuntimeError("SECRET_KEY usa un valor de ejemplo. Genera una clave aleatoria.")
