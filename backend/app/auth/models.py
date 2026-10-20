from sqlalchemy import CheckConstraint

from ..common import iso, utcnow
from ..extensions import db

role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(db.Model):
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.String(200), nullable=False)


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)

    permissions = db.relationship("Permission", secondary=role_permissions, lazy="selectin")

    def permission_codes(self):
        return sorted(p.code for p in self.permissions)

    def to_dict(self):
        return {"id": self.id, "code": self.code, "name": self.name, "permissions": self.permission_codes()}


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("session_version >= 1", name="session_version_positive"),)

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    # Se incrementa al cambiar la contraseña o desactivar: invalida las sesiones abiertas.
    session_version = db.Column(db.Integer, nullable=False, default=1)
    last_login_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    role = db.relationship("Role", lazy="joined")

    def has(self, permission):
        return permission in self.role.permission_codes()

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "full_name": self.full_name,
            "email": self.email,
            "role": self.role.code,
            "role_name": self.role.name,
            "is_active": self.is_active,
            "must_change_password": self.must_change_password,
            "last_login_at": iso(self.last_login_at),
            "created_at": iso(self.created_at),
        }


class LoginThrottle(db.Model):
    """Contador de fallos por usuario o por IP (clave 'user:<nombre>' / 'ip:<dirección>')."""

    __tablename__ = "login_throttle"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(200), nullable=False, unique=True)
    failures = db.Column(db.Integer, nullable=False, default=0)
    window_start = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    locked_until = db.Column(db.DateTime(timezone=True))


class PasswordResetToken(db.Model):
    """Solo se guarda el hash SHA-256 del token; el token en claro viaja una vez por correo."""

    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
