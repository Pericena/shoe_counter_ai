"""Capa de integración desacoplada: adaptadores que traducen eventos externos a operaciones internas.

Hoy existe el adaptador «generico» (JSON documentado en docs/10-integraciones.md). Para una plataforma
concreta (Shopify, WooCommerce, un TPV comercial…) se añade un adaptador que traduzca su formato a este,
sin tocar inventario ni ventas. No hay ninguna plataforma externa conectada en este momento.
"""
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..common import ApiError, utcnow
from ..extensions import db
from ..products.models import ProductVariant
from ..sales.models import Sale
from ..sales.services import create_return, create_sale
from .models import EVENT_TYPES, IntegrationChannel, IntegrationEvent


def hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def new_api_key():
    key = "sca_" + secrets.token_urlsafe(32)
    return key, hash_key(key), key[:12]


def authenticate(code, key):
    channel = db.session.execute(select(IntegrationChannel).where(IntegrationChannel.code == code)).scalar_one_or_none()
    if channel is None or not channel.is_active or not key or not secrets.compare_digest(channel.api_key_hash, hash_key(key)):
        raise ApiError("Integración no autorizada.", 401)
    return channel


def _lines(payload, require_condition=False):
    lines = payload.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("El evento no tiene líneas.")
    result, unknown = [], []
    for line in lines:
        sku = str(line.get("sku") or "").strip()
        variant = db.session.execute(select(ProductVariant).where(
            (ProductVariant.sku == sku) | (ProductVariant.barcode == sku))).scalar_one_or_none() if sku else None
        if variant is None:
            unknown.append(sku or "(vacío)")
            continue
        item = {"variant": variant, "quantity": line.get("quantity"), "unit_price": line.get("unit_price"),
                "condition": line.get("condition", "revision")}
        result.append(item)
    if unknown:
        raise LookupError(f"SKU no registrados en el inventario: {', '.join(unknown)}")
    return result


def _apply(channel, event_type, payload, event):
    external_ref = f"{channel.code}:{payload['external_id']}"
    if event_type == "venta":
        lines = _lines(payload)
        sale, _ = create_sale(
            lines=[{"variant_id": i["variant"].id, "quantity": i["quantity"], "unit_price": i["unit_price"]} for i in lines],
            location_id=channel.location_id, payment_method=payload.get("payment_method", "otro"),
            payment_reference=payload.get("payment_reference"), customer_name=payload.get("customer_name"),
            channel="integracion", external_ref=external_ref, allow_price_override=True, commit=False)
        event.sale_id = sale.id
    elif event_type == "devolucion":
        sale_ref = f"{channel.code}:{payload.get('sale_external_id')}"
        sale = db.session.execute(select(Sale).where(Sale.channel == "integracion", Sale.external_ref == sale_ref)).scalar_one_or_none()
        if sale is None:
            raise LookupError(f"La venta {payload.get('sale_external_id')} no existe en el inventario.")
        lines = _lines(payload)
        by_variant = {i.variant_id: i for i in sale.items}
        items = []
        for line in lines:
            sale_item = by_variant.get(line["variant"].id)
            if sale_item is None:
                raise LookupError(f"{line['variant'].sku} no está en la venta {payload.get('sale_external_id')}.")
            items.append({"sale_item_id": sale_item.id, "quantity": line["quantity"], "condition": line["condition"]})
        create_return(sale.id, items=items, reason=str(payload.get("reason") or "Devolución recibida por integración"),
                      commit=False)
        event.sale_id = sale.id


def process_event(channel, payload):
    """Procesa un evento de forma idempotente. Devuelve (evento, duplicado)."""
    if not isinstance(payload, dict):
        raise ApiError("El evento debe ser un objeto JSON.", 422)
    event_type, external_id = payload.get("type"), str(payload.get("external_id") or "").strip()[:150]
    if event_type not in EVENT_TYPES or not external_id:
        raise ApiError("Datos no válidos.", 422, {"type": f"Uno de {EVENT_TYPES}", "external_id": "Obligatorio."})
    existing = db.session.execute(select(IntegrationEvent).where(
        IntegrationEvent.channel_id == channel.id, IntegrationEvent.event_type == event_type,
        IntegrationEvent.external_id == external_id)).scalar_one_or_none()
    if existing is not None and existing.status == "procesado":
        existing.attempts += 1
        db.session.commit()
        return existing, True
    event = existing or IntegrationEvent(channel_id=channel.id, event_type=event_type, external_id=external_id,
                                         payload=payload, status="error")
    if existing is not None:
        event.attempts += 1
        event.payload = payload
    else:
        db.session.add(event)
    channel.last_event_at = utcnow()
    try:
        with db.session.begin_nested():
            _apply(channel, event_type, payload, event)
        event.status, event.error = "procesado", None
    except LookupError as error:
        event.status, event.error = "conflicto", str(error)
    except ApiError as error:
        details = f" {error.details}" if error.details else ""
        event.status, event.error = "conflicto", f"{error.message}{details}"
    except (ValueError, IntegrityError) as error:
        event.status, event.error = "error", str(error)
    event.processed_at = utcnow()
    if event.status != "procesado":
        from ..notifications.services import notify
        notify("sync_error", "alta", f"Error de sincronización ({channel.code})",
               f"Evento {event_type} {external_id}: {event.error}",
               "Revisa el evento en Integraciones y corrige el SKU o el stock; luego reenvíalo desde el sistema externo.",
               "integration_event", event.id, dedupe_key=f"sync:{channel.id}:{event_type}:{external_id}")
    db.session.commit()
    return event, False
