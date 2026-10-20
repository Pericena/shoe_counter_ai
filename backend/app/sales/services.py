"""Ventas y devoluciones. Toda variación de stock pasa por inventory.services (una sola vez por evento)."""
import secrets
from decimal import Decimal

from flask import g
from sqlalchemy import select

from ..audit.services import audit
from ..common import ApiError, utcnow
from ..extensions import db
from ..inventory.models import StockLevel
from ..inventory.services import apply_movement, lock_variant, resolve_location
from .models import PAYMENT_METHODS, RETURN_CONDITIONS, ReturnItem, Sale, SaleItem, SaleReturn

CENT = Decimal("0.01")


def _number(prefix):
    return f"{prefix}-{utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}"


def _money(value, field):
    try:
        amount = Decimal(str(value)).quantize(CENT)
    except Exception:  # noqa: BLE001
        raise ApiError("Datos no válidos.", 422, {field: "Debe ser un importe."})
    if amount < 0:
        raise ApiError("Datos no válidos.", 422, {field: "No puede ser negativo."})
    return amount


def create_sale(*, lines, location_id=None, payment_method="efectivo", payment_reference=None, customer_name=None,
                channel="tpv", external_ref=None, allow_price_override=False, commit=True):
    """Registra una venta. Si (canal, external_ref) ya existe devuelve la venta original sin tocar el stock."""
    if external_ref:
        existing = db.session.execute(select(Sale).where(Sale.channel == channel, Sale.external_ref == external_ref)).scalar_one_or_none()
        if existing is not None:
            return existing, False
    if payment_method not in PAYMENT_METHODS:
        raise ApiError("Datos no válidos.", 422, {"payment_method": f"Opciones: {', '.join(PAYMENT_METHODS)}"})
    if not isinstance(lines, list) or not lines:
        raise ApiError("La venta no tiene productos.", 422)
    location = resolve_location(location_id)
    merged = {}
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ApiError("Datos no válidos.", 422, {f"lines[{index}]": "Formato incorrecto."})
        vid, qty = line.get("variant_id"), line.get("quantity")
        if isinstance(vid, bool) or not isinstance(vid, int) or isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError("Datos no válidos.", 422, {f"lines[{index}]": "variant_id y quantity (> 0) enteros."})
        entry = merged.setdefault(vid, {"quantity": 0, "discount": Decimal("0"), "unit_price": None})
        entry["quantity"] += qty
        entry["discount"] += _money(line.get("discount", 0), f"lines[{index}].discount")
        if line.get("unit_price") is not None:
            if not allow_price_override:
                raise ApiError("No tienes permiso para cambiar el precio de venta.", 403)
            entry["unit_price"] = _money(line["unit_price"], f"lines[{index}].unit_price")

    sale = Sale(number=_number("V"), channel=channel, external_ref=external_ref, location_id=location.id,
                user_id=g.user.id if getattr(g, "user", None) else None, customer_name=customer_name,
                payment_method=payment_method, payment_reference=payment_reference,
                subtotal=Decimal("0"), discount_total=Decimal("0"), total=Decimal("0"))
    db.session.add(sale)
    db.session.flush()
    problems = {}
    for vid in sorted(merged):
        entry = merged[vid]
        variant = lock_variant(vid)
        price = entry["unit_price"] if entry["unit_price"] is not None else variant.price
        if price is None:
            problems[str(vid)] = f"{variant.sku} no tiene precio de venta."
            continue
        level = db.session.get(StockLevel, (variant.id, location.id))
        available = level.available if level else 0
        if available < entry["quantity"]:
            problems[str(vid)] = f"Solo hay {available} pares disponibles de {variant.sku} en {location.name}."
            continue
        gross = price * entry["quantity"]
        if entry["discount"] > gross:
            problems[str(vid)] = f"El descuento supera el importe de {variant.sku}."
            continue
        sale.items.append(SaleItem(variant_id=variant.id, quantity=entry["quantity"], unit_price=price,
                                   discount=entry["discount"], unit_cost=variant.cost, line_total=gross - entry["discount"]))
        sale.subtotal += gross
        sale.discount_total += entry["discount"]
        apply_movement(variant, "salida_venta", -entry["quantity"], location=location, channel=channel,
                       reason=f"Venta {sale.number}", reference=sale.number,
                       external_ref=f"{sale.number}:{variant.id}")
    if problems:
        # Sin rollback aquí: quien llama decide (la ruta revierte; el procesador de eventos usa un savepoint).
        raise ApiError("No se pudo registrar la venta.", 409, problems)
    sale.total = sale.subtotal - sale.discount_total
    audit("venta", "sale", sale.id, {"numero": sale.number, "total": str(sale.total), "canal": channel,
                                     "external_ref": external_ref})
    if commit:
        db.session.commit()
    return sale, True


def _reintegrate(item, quantity, sale, note):
    variant = lock_variant(item.variant_id)
    apply_movement(variant, "devolucion_cliente", quantity, location=resolve_location(sale.location_id),
                   channel=sale.channel if sale.channel in ("tpv", "integracion") else "tienda",
                   reason=note, reference=sale.number)


def create_return(sale_id, *, items, reason, commit=True):
    sale = db.session.execute(select(Sale).where(Sale.id == sale_id).with_for_update()
                              .execution_options(populate_existing=True)).scalar_one_or_none()
    if sale is None:
        raise ApiError("La venta no existe.", 404)
    if not reason:
        raise ApiError("Datos no válidos.", 422, {"reason": "Indica el motivo de la devolución."})
    if not isinstance(items, list) or not items:
        raise ApiError("Indica qué productos se devuelven.", 422)
    sale_items = {i.id: i for i in sale.items}
    user = getattr(g, "user", None)
    record = SaleReturn(number=_number("D"), sale_id=sale.id, user_id=user.id if user else None, reason=reason,
                        refund_amount=Decimal("0"))
    db.session.add(record)
    for index, entry in enumerate(items):
        item = sale_items.get(entry.get("sale_item_id")) if isinstance(entry, dict) else None
        qty = entry.get("quantity") if isinstance(entry, dict) else None
        condition = entry.get("condition") if isinstance(entry, dict) else None
        if item is None:
            raise ApiError("Datos no válidos.", 422, {f"items[{index}]": "La línea no pertenece a la venta."})
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0 or qty > item.quantity - item.returned_quantity:
            raise ApiError("Datos no válidos.", 422,
                           {f"items[{index}]": f"Cantidad entre 1 y {item.quantity - item.returned_quantity}."})
        if condition not in RETURN_CONDITIONS:
            raise ApiError("Datos no válidos.", 422, {f"items[{index}]": "Condición: reintegrable, danado o revision."})
        item.returned_quantity += qty
        unit_net = (item.line_total / item.quantity).quantize(CENT)
        record.refund_amount += unit_net * qty
        record.items.append(ReturnItem(sale_item_id=item.id, quantity=qty, condition=condition))
        if condition == "reintegrable":
            _reintegrate(item, qty, sale, f"Devolución {record.number} de {sale.number}: {reason}")
    db.session.flush()
    audit("devolucion", "sale", sale.id, {"numero": record.number, "importe": str(record.refund_amount),
                                          "lineas": [(i.sale_item_id, i.quantity, i.condition) for i in record.items]})
    if commit:
        db.session.commit()
    return record


def resolve_return_item(item_id, resolution):
    item = db.session.get(ReturnItem, item_id)
    if item is None:
        raise ApiError("La línea de devolución no existe.", 404)
    if item.condition != "revision" or item.resolution is not None:
        raise ApiError("Esta línea no está pendiente de revisión.", 409)
    if resolution not in ("reintegrable", "danado"):
        raise ApiError("Datos no válidos.", 422, {"resolution": "reintegrable o danado."})
    item.resolution = resolution
    item.resolved_by = g.user.id
    item.resolved_at = utcnow()
    sale = item.sale_item.sale
    if resolution == "reintegrable":
        _reintegrate(item.sale_item, item.quantity, sale,
                     f"Devolución {item.sale_return.number} revisada: reintegrable")
    audit("devolucion_revisada", "sale", sale.id, {"return_item": item.id, "resolucion": resolution})
    db.session.commit()
    return item
