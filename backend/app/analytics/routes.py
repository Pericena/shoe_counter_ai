import csv
import io
import json
import os

import click
from flask import Blueprint, Response, g, jsonify, request
from flask.cli import AppGroup
from sqlalchemy import select, text

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, json_body, query_int, utcnow
from ..extensions import db
from . import forecast as forecast_mod
from . import insights, kpis
from .bi import DATASETS, PG_VIEWS, BiToken, check_token, new_token

bp = Blueprint("analytics", __name__, url_prefix="/api")
bi_cli = AppGroup("bi", help="Integración con Power BI.")


@bp.get("/kpis")
@require("reports.view")
def get_kpis():
    return jsonify(kpis.all_kpis())


@bp.get("/kpis/definitions")
@require("reports.view")
def kpi_definitions():
    return jsonify({"items": kpis.KPI_DEFINITIONS})


@bp.get("/forecast")
@require("reports.view")
def get_forecast():
    return jsonify(forecast_mod.forecast(limit=query_int("limit", default=20, minimum=1, maximum=200),
                                         location_id=query_int("location_id"), variant_id=query_int("variant_id")))


@bp.get("/analytics/anomalies")
@require("reports.view")
def get_anomalies():
    return jsonify(insights.anomalies(days=query_int("days", default=90, minimum=1, maximum=730)))


@bp.get("/analytics/duplicates")
@require("products.view")
def get_duplicates():
    return jsonify(insights.duplicates())


@bp.get("/analytics/incomplete")
@require("products.view")
def get_incomplete():
    return jsonify(insights.incomplete())


# ---------- Power BI ----------

def _bi_access():
    """Sesión con permiso bi.view o token de lectura (Authorization: Bearer)."""
    user = getattr(g, "user", None)
    if user is not None and user.has("bi.view"):
        return f"usuario:{user.username}"
    header = request.headers.get("Authorization", "")
    token = check_token(header[7:].strip() if header.lower().startswith("bearer ") else "")
    if token is None:
        raise ApiError("Acceso a datos analíticos no autorizado.", 401)
    return f"token:{token.name}"


@bp.get("/bi/datasets")
def bi_catalog():
    _bi_access()
    db.session.commit()
    return jsonify({"datasets": sorted(DATASETS), "formats": ["csv", "json"],
                    "url": "/api/bi/datasets/<conjunto>.csv", "views_schema": "analytics", "views": sorted(PG_VIEWS)})


@bp.get("/bi/datasets/<name>.<fmt>")
def bi_dataset(name, fmt):
    who = _bi_access()
    if name not in DATASETS or fmt not in ("csv", "json"):
        raise ApiError("Conjunto o formato no disponible.", 404, {"disponibles": sorted(DATASETS)})
    rows = list(DATASETS[name]())
    audit("bi_lectura", "bi", name, {"formato": fmt, "filas": len(rows), "acceso": who})
    db.session.commit()
    if fmt == "json":
        return Response(json.dumps(rows, ensure_ascii=False, default=str), mimetype="application/json")
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return Response("﻿" + buffer.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={name}.csv"})


@bp.get("/bi/tokens")
@require("settings.manage")
def list_tokens():
    rows = db.session.execute(select(BiToken).order_by(BiToken.id.desc())).scalars().all()
    return jsonify({"items": [t.to_dict() for t in rows]})


@bp.post("/bi/tokens")
@require("settings.manage")
def create_token():
    name = str(json_body().get("name") or "").strip()[:100]
    if not name:
        raise ApiError("Datos no válidos.", 422, {"name": "Pon un nombre (p. ej. «Power BI gerencia»)."})
    token, digest, prefix = new_token()
    row = BiToken(name=name, token_hash=digest, prefix=prefix, created_by=g.user.id)
    db.session.add(row)
    db.session.flush()
    audit("bi_token_creado", "bi_token", row.id, {"nombre": name})
    db.session.commit()
    return jsonify({**row.to_dict(), "token": token, "warning": "Copia el token ahora: no se volverá a mostrar."}), 201


@bp.post("/bi/tokens/<int:token_id>/revoke")
@require("settings.manage")
def revoke_token(token_id):
    row = db.session.get(BiToken, token_id)
    if row is None:
        raise ApiError("El token no existe.", 404)
    row.revoked_at = utcnow()
    audit("bi_token_revocado", "bi_token", row.id)
    db.session.commit()
    return jsonify(row.to_dict())


def create_views(connection):
    """Crea/actualiza el esquema `analytics` con las vistas (solo PostgreSQL)."""
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS analytics"))
    for name, sql in PG_VIEWS.items():
        connection.execute(text(f"CREATE OR REPLACE VIEW analytics.{name} AS {sql}"))


@bi_cli.command("create-views")
def create_views_cli():
    """Crea o actualiza las vistas del esquema analytics (PostgreSQL)."""
    if db.engine.dialect.name != "postgresql":
        raise click.ClickException("Las vistas analíticas requieren PostgreSQL.")
    with db.engine.begin() as connection:
        create_views(connection)
    click.echo(f"Vistas creadas: {', '.join(sorted(PG_VIEWS))}")


@bi_cli.command("create-reader")
@click.option("--role", default="powerbi_reader", show_default=True)
def create_reader(role):
    """Crea un usuario de PostgreSQL de SOLO LECTURA sobre el esquema analytics.

    La contraseña se lee de la variable BI_READER_PASSWORD (nunca se escribe en el código).
    """
    if db.engine.dialect.name != "postgresql":
        raise click.ClickException("Requiere PostgreSQL.")
    password = os.environ.get("BI_READER_PASSWORD")
    if not password or len(password) < 16:
        raise click.ClickException("Define BI_READER_PASSWORD (mínimo 16 caracteres) en el entorno.")
    if not role.replace("_", "").isalnum():
        raise click.ClickException("Nombre de rol no válido.")
    with db.engine.begin() as connection:
        create_views(connection)
        exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
        quoted = connection.execute(text("SELECT quote_literal(:p)"), {"p": password}).scalar()
        if exists:
            connection.execute(text(f"ALTER ROLE {role} WITH LOGIN PASSWORD {quoted}"))
        else:
            connection.execute(text(f"CREATE ROLE {role} WITH LOGIN PASSWORD {quoted} NOSUPERUSER NOCREATEDB NOCREATEROLE"))
        database = connection.execute(text("SELECT current_database()")).scalar()
        connection.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO {role}'))
        connection.execute(text(f"REVOKE ALL ON SCHEMA public FROM {role}"))
        connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA analytics TO {role}"))
        connection.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO {role}"))
        connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO {role}"))
    click.echo(f"Rol de solo lectura '{role}' listo: SELECT sobre analytics.*; sin acceso a las tablas operativas.")
