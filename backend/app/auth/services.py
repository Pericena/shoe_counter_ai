"""Contraseñas, sesiones, límite de intentos y recuperación de contraseña."""
import hashlib
import secrets
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from functools import wraps

from flask import current_app, g, session
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from ..common import ApiError, utcnow
from ..extensions import db
from .models import LoginThrottle, PasswordResetToken, Role, User

# Hash de una contraseña aleatoria: se usa para gastar el mismo tiempo cuando el usuario no existe.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))
MIN_PASSWORD_LENGTH = 10


def hash_password(password):
    return generate_password_hash(password)  # Werkzeug 3: scrypt con sal aleatoria


def validate_password(password, username=None):
    """Devuelve un mensaje de error o None si la contraseña es aceptable."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
    if len(password) > 128:
        return "La contraseña no puede superar 128 caracteres."
    if len(set(password)) < 5:
        return "La contraseña es demasiado repetitiva."
    if username and username.lower() in password.lower():
        return "La contraseña no puede contener el nombre de usuario."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "La contraseña debe combinar letras y números."
    return None


# ---------- Límite de intentos ----------

def _aware(value):
    from datetime import timezone
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _throttle(key):
    """Fila del contador bloqueada (FOR UPDATE). Si dos peticiones simultáneas la crean a la vez,
    la segunda recibe IntegrityError dentro de un savepoint y vuelve a leer la fila ya creada."""
    from sqlalchemy.exc import IntegrityError

    query = select(LoginThrottle).where(LoginThrottle.key == key).with_for_update().execution_options(populate_existing=True)
    row = db.session.execute(query).scalar_one_or_none()
    if row is not None:
        return row
    try:
        with db.session.begin_nested():
            row = LoginThrottle(key=key, failures=0, window_start=utcnow())
            db.session.add(row)
    except IntegrityError:
        row = db.session.execute(query).scalar_one()
    return row


def is_locked(keys):
    now = utcnow()
    rows = db.session.execute(select(LoginThrottle).where(LoginThrottle.key.in_(keys))).scalars().all()
    return any(r.locked_until and _aware(r.locked_until) > now for r in rows)


def register_failure(key, limit):
    cfg = current_app.config
    now = utcnow()
    window = timedelta(minutes=cfg["LOGIN_LOCK_MINUTES"])
    row = _throttle(key)
    if _aware(row.window_start) < now - window:
        row.failures = 0
        row.window_start = now
    row.failures += 1
    if row.failures >= limit:
        row.locked_until = now + window
        row.failures = 0
        row.window_start = now


def clear_failures(key):
    row = db.session.execute(select(LoginThrottle).where(LoginThrottle.key == key)).scalar_one_or_none()
    if row is not None:
        db.session.delete(row)


def check_rate(key, limit, minutes):
    """Límite genérico (p. ej. pedidos públicos por IP). Lanza 429 si se supera."""
    now = utcnow()
    row = _throttle(key)
    if _aware(row.window_start) < now - timedelta(minutes=minutes):
        row.failures = 0
        row.window_start = now
    if row.failures >= limit:
        db.session.commit()
        raise ApiError("Demasiadas solicitudes. Inténtalo más tarde.", 429)
    row.failures += 1


# ---------- Autenticación ----------

def authenticate(username, password, ip):
    cfg = current_app.config
    username = (username or "").strip().lower()
    user_key, ip_key = f"user:{username}", f"ip:{ip}"
    if is_locked([user_key, ip_key]):
        raise ApiError("Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.", 429)

    user = db.session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    valid = check_password_hash(user.password_hash if user else _DUMMY_HASH, password or "")
    if not user or not valid or not user.is_active:
        register_failure(user_key, cfg["LOGIN_MAX_FAILURES_USER"])
        register_failure(ip_key, cfg["LOGIN_MAX_FAILURES_IP"])
        db.session.commit()
        return None
    clear_failures(user_key)
    clear_failures(ip_key)
    user.last_login_at = utcnow()
    return user


def start_session(user):
    session.clear()
    session.permanent = True
    session["uid"] = user.id
    session["sv"] = user.session_version
    session["csrf"] = secrets.token_urlsafe(32)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def load_current_user():
    uid = session.get("uid")
    if not uid:
        return None
    user = db.session.get(User, uid)
    if user is None or not user.is_active or user.session_version != session.get("sv"):
        session.pop("uid", None)
        session.pop("sv", None)
        return None
    return user


def require(*permissions):
    """Exige sesión y TODOS los permisos indicados. Se verifica en el servidor en cada petición."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = getattr(g, "user", None)
            if user is None:
                raise ApiError("Debes iniciar sesión.", 401)
            missing = [p for p in permissions if not user.has(p)]
            if missing:
                raise ApiError("No tienes permiso para esta acción.", 403, {"required": missing})
            return view(*args, **kwargs)
        return wrapper
    return decorator


def seed_roles():
    """Crea o completa roles y permisos según app/auth/permissions.py (idempotente)."""
    from .models import Permission
    from .permissions import PERMISSIONS, ROLES

    existing = {p.code: p for p in db.session.execute(select(Permission)).scalars()}
    for code, description in PERMISSIONS.items():
        if code not in existing:
            existing[code] = Permission(code=code, description=description)
            db.session.add(existing[code])
    for code, (name, perms) in ROLES.items():
        role = db.session.execute(select(Role).where(Role.code == code)).scalar_one_or_none()
        if role is None:
            role = Role(code=code, name=name)
            db.session.add(role)
        role.permissions = [existing[p] for p in perms]
    db.session.commit()


def get_role(code):
    role = db.session.execute(select(Role).where(Role.code == code)).scalar_one_or_none()
    if role is None:
        raise ApiError("Rol no válido.", 422, {"role": "Opciones: admin, inventario, operador, consulta"})
    return role


def set_password(user, password):
    user.password_hash = hash_password(password)
    user.session_version += 1


# ---------- Recuperación de contraseña ----------

def smtp_configured():
    cfg = current_app.config
    return bool(cfg.get("SMTP_HOST") and cfg.get("SMTP_FROM"))


def create_reset_token(user):
    token = secrets.token_urlsafe(32)
    db.session.add(PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=utcnow() + timedelta(minutes=current_app.config["PASSWORD_RESET_MINUTES"]),
    ))
    return token


def consume_reset_token(token):
    digest = hashlib.sha256((token or "").encode()).hexdigest()
    row = db.session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == digest)
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or _aware(row.expires_at) < utcnow():
        raise ApiError("El enlace de recuperación no es válido o ha caducado.", 400)
    row.used_at = utcnow()
    return db.session.get(User, row.user_id)


def send_reset_email(user, token):
    cfg = current_app.config
    message = EmailMessage()
    message["Subject"] = "Recuperación de contraseña — Shoe Counter AI"
    message["From"] = cfg["SMTP_FROM"]
    message["To"] = user.email
    link = f"{cfg['PUBLIC_BASE_URL'].rstrip('/')}/login.html#reset={token}"
    message.set_content(
        f"Hola {user.full_name}:\n\nPara crear una contraseña nueva abre este enlace "
        f"(caduca en {cfg['PASSWORD_RESET_MINUTES']} minutos):\n\n{link}\n\n"
        "Si no lo solicitaste, ignora este mensaje."
    )
    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15) as smtp:
        if cfg["SMTP_STARTTLS"]:
            smtp.starttls()
        if cfg.get("SMTP_USER"):
            smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"] or "")
        smtp.send_message(message)
