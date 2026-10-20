from flask import Blueprint, jsonify, request
from sqlalchemy import select

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, Validator, json_body, query_int
from ..extensions import db
from ..inventory.services import resolve_location
from .models import INTEGRATION_KINDS, IntegrationChannel, IntegrationEvent
from .services import authenticate, new_api_key, process_event

bp = Blueprint("integrations", __name__, url_prefix="/api/integrations")


@bp.post("/inbound/<code>/events")
def inbound(code):
    """Entrada para sistemas externos. Autenticación: cabecera X-Integration-Key (sin sesión ni CSRF)."""
    channel = authenticate(code, request.headers.get("X-Integration-Key", ""))
    event, duplicate = process_event(channel, request.get_json(silent=True))
    status = 200 if duplicate or event.status == "procesado" else 409
    return jsonify({"event_id": event.id, "status": event.status, "duplicate": duplicate, "error": event.error,
                    "sale_id": event.sale_id}), status


@bp.get("")
@require("integrations.manage")
def list_channels():
    rows = db.session.execute(select(IntegrationChannel).order_by(IntegrationChannel.id)).scalars().all()
    return jsonify({"items": [c.to_dict() for c in rows], "inbound_url": "/api/integrations/inbound/<code>/events"})


@bp.post("")
@require("integrations.manage")
def create_channel():
    v = Validator(json_body())
    v.text("code", required=True, max_len=40)
    v.text("name", required=True, max_len=120)
    v.choice("kind", INTEGRATION_KINDS, required=True)
    v.integer("location_id", minimum=1)
    clean = v.raise_if_errors()
    code = clean["code"].lower()
    if not code.replace("-", "").replace("_", "").isalnum():
        raise ApiError("Datos no válidos.", 422, {"code": "Solo letras, números, '-' y '_'."})
    if db.session.execute(select(IntegrationChannel).where(IntegrationChannel.code == code)).first():
        raise ApiError("Ya existe una integración con ese código.", 409)
    key, digest, prefix = new_api_key()
    channel = IntegrationChannel(code=code, name=clean["name"], kind=clean["kind"], api_key_hash=digest,
                                 api_key_prefix=prefix, location_id=resolve_location(clean.get("location_id")).id)
    db.session.add(channel)
    db.session.flush()
    audit("integracion_creada", "integration", channel.id, {"code": code})
    db.session.commit()
    return jsonify({**channel.to_dict(), "api_key": key,
                    "warning": "Copia la clave ahora: no se volverá a mostrar."}), 201


@bp.post("/<int:channel_id>/rotate-key")
@require("integrations.manage")
def rotate(channel_id):
    channel = db.session.get(IntegrationChannel, channel_id)
    if channel is None:
        raise ApiError("La integración no existe.", 404)
    key, digest, prefix = new_api_key()
    channel.api_key_hash, channel.api_key_prefix = digest, prefix
    audit("integracion_clave_rotada", "integration", channel.id)
    db.session.commit()
    return jsonify({**channel.to_dict(), "api_key": key, "warning": "Copia la clave ahora: no se volverá a mostrar."})


@bp.patch("/<int:channel_id>")
@require("integrations.manage")
def toggle(channel_id):
    channel = db.session.get(IntegrationChannel, channel_id)
    if channel is None:
        raise ApiError("La integración no existe.", 404)
    active = json_body().get("is_active")
    if not isinstance(active, bool):
        raise ApiError("Datos no válidos.", 422, {"is_active": "true o false."})
    channel.is_active = active
    audit("integracion_estado", "integration", channel.id, {"activa": active})
    db.session.commit()
    return jsonify(channel.to_dict())


@bp.get("/events")
@require("integrations.manage")
def events():
    limit = query_int("limit", default=50, minimum=1, maximum=200)
    query = select(IntegrationEvent)
    if status := request.args.get("status"):
        query = query.where(IntegrationEvent.status == status)
    rows = db.session.execute(query.order_by(IntegrationEvent.id.desc()).limit(limit)).scalars().all()
    return jsonify({"items": [e.to_dict() for e in rows]})
