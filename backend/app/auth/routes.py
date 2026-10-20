from flask import Blueprint, current_app, g, jsonify, session
from sqlalchemy import func, select

from ..audit.services import audit, client_ip
from ..common import ApiError, json_body
from ..extensions import db
from .models import User
from .services import (authenticate, consume_reset_token, create_reset_token, csrf_token,
                       send_reset_email, set_password, smtp_configured, start_session,
                       validate_password)

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _session_payload(user):
    return {
        "user": user.to_dict() if user else None,
        "permissions": user.role.permission_codes() if user else [],
        "csrf_token": csrf_token(),
    }


@bp.get("/session")
def current_session():
    """Devuelve el usuario actual (o null) y el token CSRF para las peticiones siguientes."""
    return jsonify(_session_payload(getattr(g, "user", None)))


@bp.post("/login")
def login():
    data = json_body()
    username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
        raise ApiError("Introduce usuario y contraseña.", 422)
    user = authenticate(username, password, client_ip())
    if user is None:
        audit("login_fallido", "user", details={"username": username.strip().lower()[:50]}, commit=True)
        raise ApiError("Usuario o contraseña incorrectos.", 401)
    start_session(user)
    g.user = user
    audit("login", "user", user.id, user=user)
    db.session.commit()
    return jsonify(_session_payload(user))


@bp.post("/logout")
def logout():
    user = getattr(g, "user", None)
    if user:
        audit("logout", "user", user.id, user=user, commit=True)
    session.clear()
    return jsonify({"ok": True, "csrf_token": csrf_token()})


@bp.post("/change-password")
def change_password():
    user = getattr(g, "user", None)
    if user is None:
        raise ApiError("Debes iniciar sesión.", 401)
    data = json_body()
    from werkzeug.security import check_password_hash
    if not check_password_hash(user.password_hash, data.get("current_password") or ""):
        raise ApiError("La contraseña actual no es correcta.", 422, {"current_password": "Incorrecta."})
    new = data.get("new_password")
    if error := validate_password(new, user.username):
        raise ApiError(error, 422, {"new_password": error})
    if new == data.get("current_password"):
        raise ApiError("La nueva contraseña debe ser distinta.", 422)
    set_password(user, new)
    user.must_change_password = False
    audit("cambio_contrasena", "user", user.id)
    db.session.commit()
    start_session(user)  # renueva la sesión actual; las demás quedan invalidadas
    return jsonify(_session_payload(user))


@bp.post("/password-reset/request")
def password_reset_request():
    """Respuesta idéntica exista o no el correo, para no revelar cuentas."""
    email = (json_body().get("email") or "").strip().lower()
    generic = {"message": "Si el correo pertenece a un usuario activo, recibirá un enlace de recuperación."}
    if not smtp_configured():
        return jsonify({**generic, "email_enabled": False,
                        "message": "La recuperación por correo no está configurada. Pide a un administrador "
                                   "que restablezca tu contraseña."})
    user = db.session.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if user and user.is_active and email:
        token = create_reset_token(user)
        audit("recuperacion_solicitada", "user", user.id, user=user)
        db.session.commit()
        try:
            send_reset_email(user, token)
        except Exception as error:  # noqa: BLE001
            current_app.logger.error("No se pudo enviar el correo de recuperación: %s", error)
    return jsonify({**generic, "email_enabled": True})


@bp.post("/password-reset/confirm")
def password_reset_confirm():
    data = json_body()
    user = consume_reset_token(data.get("token"))
    if user is None or not user.is_active:
        raise ApiError("El enlace de recuperación no es válido o ha caducado.", 400)
    if error := validate_password(data.get("new_password"), user.username):
        db.session.rollback()
        raise ApiError(error, 422, {"new_password": error})
    set_password(user, data["new_password"])
    user.must_change_password = False
    audit("recuperacion_completada", "user", user.id, user=user)
    db.session.commit()
    return jsonify({"message": "Contraseña actualizada. Ya puedes iniciar sesión."})
