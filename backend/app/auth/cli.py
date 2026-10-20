"""Comandos de administración: `flask --app run users create-admin`, `users reset-password`, `users list`."""
import getpass
import os

import click
from flask.cli import AppGroup
from sqlalchemy import select

from ..audit.services import audit
from ..extensions import db
from .models import User
from .services import get_role, hash_password, set_password, validate_password

users_cli = AppGroup("users", help="Gestión de usuarios desde la consola.")


def _ask_password(username):
    """La contraseña se pide por consola (no queda en el historial) o se lee de ADMIN_PASSWORD."""
    password = os.environ.get("ADMIN_PASSWORD")
    if password:
        click.echo("Usando la contraseña de la variable de entorno ADMIN_PASSWORD.")
    else:
        password = getpass.getpass("Contraseña: ")
        if password != getpass.getpass("Repite la contraseña: "):
            raise click.ClickException("Las contraseñas no coinciden.")
    if error := validate_password(password, username):
        raise click.ClickException(error)
    return password


@users_cli.command("create-admin")
@click.option("--username", required=True, help="Nombre de usuario (minúsculas).")
@click.option("--full-name", default="Administrador", show_default=True)
@click.option("--email", default=None)
def create_admin(username, full_name, email):
    """Crea un usuario administrador. No hay credenciales por defecto."""
    username = username.strip().lower()
    if db.session.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise click.ClickException(f"El usuario '{username}' ya existe.")
    password = _ask_password(username)
    user = User(username=username, full_name=full_name, email=email and email.lower(),
                role=get_role("admin"), password_hash=hash_password(password), must_change_password=False)
    db.session.add(user)
    db.session.flush()
    audit("usuario_creado", "user", user.id, {"username": username, "role": "admin", "origen": "consola"}, user=user)
    db.session.commit()
    click.echo(f"Administrador '{username}' creado.")


@users_cli.command("reset-password")
@click.option("--username", required=True)
def reset_password(username):
    """Restablece la contraseña de un usuario (deberá cambiarla al entrar)."""
    user = db.session.execute(select(User).where(User.username == username.strip().lower())).scalar_one_or_none()
    if user is None:
        raise click.ClickException("El usuario no existe.")
    set_password(user, _ask_password(user.username))
    user.must_change_password = True
    user.is_active = True
    audit("usuario_modificado", "user", user.id, {"password": "restablecida desde consola"}, user=user)
    db.session.commit()
    click.echo(f"Contraseña de '{user.username}' restablecida. Se le pedirá cambiarla al entrar.")


@users_cli.command("list")
def list_users():
    for user in db.session.execute(select(User).order_by(User.username)).scalars():
        state = "activo" if user.is_active else "inactivo"
        click.echo(f"{user.id:>4}  {user.username:<20} {user.role.code:<11} {state}")
