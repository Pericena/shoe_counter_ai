"""Gestión de usuarios (solo administradores)."""
from flask import Blueprint, g, jsonify
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..audit.services import audit
from ..common import ApiError, Validator, json_body
from ..extensions import db
from .models import Role, User
from .services import get_role, hash_password, require, set_password, validate_password

bp = Blueprint("users", __name__, url_prefix="/api")

USERNAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789._-")


def _active_admins():
    return db.session.execute(
        select(func.count()).select_from(User).join(Role)
        .where(Role.code == "admin", User.is_active.is_(True))
    ).scalar_one()


@bp.get("/roles")
@require("users.manage")
def list_roles():
    roles = db.session.execute(select(Role).order_by(Role.id)).scalars().all()
    return jsonify({"items": [r.to_dict() for r in roles]})


@bp.get("/users")
@require("users.manage")
def list_users():
    users = db.session.execute(select(User).order_by(User.username)).scalars().all()
    return jsonify({"items": [u.to_dict() for u in users]})


@bp.post("/users")
@require("users.manage")
def create_user():
    data = json_body()
    v = Validator(data)
    v.text("username", required=True, max_len=50)
    v.text("full_name", required=True, max_len=150)
    v.text("email", max_len=150)
    v.text("role", required=True, max_len=30)
    clean = v.raise_if_errors()
    username = clean["username"].lower()
    if not set(username) <= USERNAME_CHARS or len(username) < 3:
        raise ApiError("Datos no válidos.", 422, {"username": "Mínimo 3 caracteres: letras, números, '.', '_' o '-'."})
    password = data.get("password")
    if error := validate_password(password, username):
        raise ApiError(error, 422, {"password": error})
    user = User(
        username=username,
        full_name=clean["full_name"],
        email=(clean.get("email") or None) and clean["email"].lower(),
        role=get_role(clean["role"]),
        password_hash=hash_password(password),
        must_change_password=True,
    )
    db.session.add(user)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Ya existe un usuario con ese nombre o correo.", 409)
    audit("usuario_creado", "user", user.id, {"username": username, "role": clean["role"]})
    db.session.commit()
    return jsonify(user.to_dict()), 201


@bp.patch("/users/<int:user_id>")
@require("users.manage")
def update_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        raise ApiError("El usuario no existe.", 404)
    data = json_body()
    v = Validator(data)
    v.text("full_name", max_len=150)
    v.text("email", max_len=150)
    v.text("role", max_len=30)
    clean = v.raise_if_errors()
    changes = {}
    was_admin = user.role.code == "admin" and user.is_active

    if clean.get("full_name"):
        user.full_name = changes["full_name"] = clean["full_name"]
    if "email" in clean:
        user.email = changes["email"] = (clean["email"] or None) and clean["email"].lower()
    if clean.get("role") and clean["role"] != user.role.code:
        user.role = get_role(clean["role"])
        user.session_version += 1
        changes["role"] = clean["role"]
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise ApiError("Datos no válidos.", 422, {"is_active": "Debe ser verdadero o falso."})
        if user.id == g.user.id and not data["is_active"]:
            raise ApiError("No puedes desactivar tu propio usuario.", 422)
        if user.is_active != data["is_active"]:
            user.is_active = changes["is_active"] = data["is_active"]
            user.session_version += 1
    if "password" in data:
        if error := validate_password(data["password"], user.username):
            raise ApiError(error, 422, {"password": error})
        set_password(user, data["password"])
        user.must_change_password = True
        changes["password"] = "restablecida (temporal)"

    db.session.flush()
    if was_admin and _active_admins() == 0:
        db.session.rollback()
        raise ApiError("Debe quedar al menos un administrador activo.", 422)
    try:
        audit("usuario_modificado", "user", user.id, changes)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Ya existe un usuario con ese correo.", 409)
    return jsonify(user.to_dict())
