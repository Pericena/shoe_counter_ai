"""Reposición explicable y órdenes de compra.

Fórmulas (parámetros en Configuración):
  demanda media diaria  d = pares vendidos en los últimos H días / H        (ventas TPV + pedidos online)
  stock de seguridad    SS = max(stock mínimo, ⌈d × días de seguridad⌉)
  punto de reposición   ROP = ⌈d × plazo de entrega⌉ + SS
  stock objetivo        T = ROP + ⌈d × días de cobertura⌉
  posición inventario   P = físico − reservado + pendiente de recibir (órdenes aprobadas/solicitadas)
  cantidad sugerida     Q = T − P   (solo si P ≤ ROP)
Solo se recomienda una talla/color si vendió al menos «ventas mínimas» en el período, o si su stock
disponible está por debajo del mínimo configurado a mano para esa variante.
"""
import math
import secrets
from datetime import timedelta
from decimal import Decimal

from flask import g
from sqlalchemy import func, select

from ..audit.services import audit
from ..common import ApiError, utcnow
from ..extensions import db
from ..inventory.models import OUTBOUND_SALES_TYPES, InventoryMovement, StockLevel
from ..inventory.services import apply_movement, lock_variant
from ..inventory.settings import get_setting
from ..products.models import PriceHistory, ProductVariant
from .models import OPEN_PO_STATUSES, PO_TRANSITIONS, PurchaseOrder, PurchaseOrderLine, ReplenishmentRecommendation


def _number(prefix):
    return f"{prefix}-{utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}"


def on_order_quantities():
    rows = db.session.execute(
        select(PurchaseOrderLine.variant_id, PurchaseOrder.location_id,
               func.sum(PurchaseOrderLine.quantity_ordered - PurchaseOrderLine.quantity_received))
        .join(PurchaseOrder).where(PurchaseOrder.status.in_(OPEN_PO_STATUSES))
        .group_by(PurchaseOrderLine.variant_id, PurchaseOrder.location_id)).all()
    return {(v, loc): int(q or 0) for v, loc, q in rows}


def compute_recommendations():
    """Recalcula las propuestas. Conserva las ya revisadas/aprobadas/solicitadas; reemplaza las pendientes."""
    history = int(get_setting("replenishment_history_days"))
    default_lead = int(get_setting("replenishment_default_lead_days"))
    safety_days = int(get_setting("replenishment_safety_days"))
    cover_days = int(get_setting("replenishment_cover_days"))
    min_sales = int(get_setting("replenishment_min_sales"))
    since = utcnow() - timedelta(days=history)
    sold = {(v, loc): int(q) for v, loc, q in db.session.execute(
        select(InventoryMovement.variant_id, InventoryMovement.location_id, func.sum(-InventoryMovement.quantity))
        .where(InventoryMovement.created_at >= since, InventoryMovement.movement_type.in_(OUTBOUND_SALES_TYPES))
        .group_by(InventoryMovement.variant_id, InventoryMovement.location_id)).all()}
    on_order = on_order_quantities()
    db.session.query(ReplenishmentRecommendation).filter(ReplenishmentRecommendation.status == "pendiente").delete()
    busy = {(r.variant_id, r.location_id) for r in db.session.execute(select(ReplenishmentRecommendation).where(
        ReplenishmentRecommendation.status.in_(("revisada", "aprobada", "solicitada")))).scalars()}
    created = []
    levels = db.session.execute(select(StockLevel).join(ProductVariant).where(ProductVariant.status == "activo")).scalars().all()
    for level in levels:
        key = (level.variant_id, level.location_id)
        if key in busy:
            continue
        variant = level.variant
        units = sold.get(key, 0)
        avg = Decimal(units) / Decimal(history) if history else Decimal(0)
        supplier = variant.product.supplier
        lead = supplier.lead_time_days if supplier and supplier.lead_time_days is not None else default_lead
        safety = max(variant.min_stock, math.ceil(avg * safety_days))
        rop = math.ceil(avg * lead) + safety
        target = rop + math.ceil(avg * cover_days)
        pending = on_order.get(key, 0)
        position = level.on_hand - level.reserved + pending
        demand_ok = units >= min_sales
        minimum_breach = variant.min_stock > 0 and position < variant.min_stock
        if position > rop or not (demand_ok or minimum_breach):
            continue
        if demand_ok:
            suggested = max(0, target - position)
            reason = (f"Vendió {units} pares en {history} días (≈{float(avg):.2f}/día). Plazo {lead} d, seguridad {safety}: "
                      f"punto de reposición {rop}. Posición {position} = físico {level.on_hand} − reservado "
                      f"{level.reserved} + pedido {pending}. Objetivo {target} → sugerido {suggested}.")
        else:
            suggested = max(0, variant.min_stock - position)
            reason = (f"Sin ventas suficientes en {history} días ({units}); se repone solo hasta el stock mínimo "
                      f"configurado ({variant.min_stock}). Posición {position}.")
        if suggested <= 0:
            continue
        available = level.on_hand - level.reserved
        days_cover = (available / float(avg)) if avg > 0 else None
        if available <= 0 and units > 0:
            priority = "alta"
        elif days_cover is not None and days_cover < lead:
            priority = "alta"
        elif demand_ok:
            priority = "media"
        else:
            priority = "baja"
        rec = ReplenishmentRecommendation(
            variant_id=variant.id, location_id=level.location_id, supplier_id=supplier.id if supplier else None,
            history_days=history, units_sold=units, avg_daily_demand=avg.quantize(Decimal("0.0001")),
            lead_time_days=lead, safety_stock=safety, reorder_point=rop, target_stock=target,
            on_hand=level.on_hand, reserved=level.reserved, on_order=pending, inventory_position=position,
            suggested_qty=suggested, priority=priority, reason=reason)
        db.session.add(rec)
        created.append(rec)
    audit("reposicion_calculada", "replenishment", None, {"recomendaciones": len(created)})
    db.session.commit()
    return created


def create_po_from_recommendations(rec_ids):
    """Agrupa recomendaciones por proveedor y ubicación en órdenes en BORRADOR (no compromete dinero)."""
    recs = db.session.execute(select(ReplenishmentRecommendation).where(ReplenishmentRecommendation.id.in_(rec_ids))).scalars().all()
    if not recs:
        raise ApiError("No se encontraron recomendaciones.", 404)
    orders = {}
    for rec in recs:
        if rec.status not in ("pendiente", "revisada"):
            raise ApiError(f"La recomendación #{rec.id} ya está {rec.status}.", 409)
        if rec.supplier_id is None:
            raise ApiError(f"{rec.variant.sku} no tiene proveedor: asígnalo al producto antes de pedir.", 422)
        key = (rec.supplier_id, rec.location_id)
        if key not in orders:
            orders[key] = PurchaseOrder(number=_number("OC"), supplier_id=rec.supplier_id, location_id=rec.location_id,
                                        status="borrador", created_by=g.user.id, notes="Generada desde reposición")
            db.session.add(orders[key])
        line = PurchaseOrderLine(variant_id=rec.variant_id, quantity_ordered=rec.suggested_qty, unit_cost=rec.variant.cost)
        orders[key].lines.append(line)
        db.session.flush()
        rec.po_line_id = line.id
        rec.status = "aprobada"
        rec.reviewed_by = g.user.id
        rec.reviewed_at = utcnow()
    for po in orders.values():
        audit("orden_compra_creada", "purchase_order", po.id, {"numero": po.number, "lineas": len(po.lines)})
    db.session.commit()
    return list(orders.values())


def change_po_status(po, new_status):
    if new_status not in PO_TRANSITIONS[po.status]:
        raise ApiError(f"No se puede pasar de '{po.status}' a '{new_status}'.", 409,
                       {"allowed": sorted(PO_TRANSITIONS[po.status])})
    if new_status == "aprobada":
        if not g.user.has("purchases.approve"):
            raise ApiError("Aprobar una orden de compra requiere el permiso purchases.approve.", 403)
        po.approved_by, po.approved_at = g.user.id, utcnow()
    if new_status == "solicitada":
        po.ordered_at = utcnow()
        lead = po.supplier.lead_time_days
        if lead is not None and po.expected_date is None:
            po.expected_date = (utcnow() + timedelta(days=lead)).date()
    old = po.status
    po.status = new_status
    for line in po.lines:
        rec = db.session.execute(select(ReplenishmentRecommendation).where(
            ReplenishmentRecommendation.po_line_id == line.id)).scalar_one_or_none()
        if rec:
            rec.status = {"solicitada": "solicitada", "cancelada": "descartada"}.get(new_status, rec.status)
    audit("orden_compra_estado", "purchase_order", po.id, {"numero": po.number, "de": old, "a": new_status})
    db.session.commit()


def receive(po, lines, receipt_ref):
    """Recibe mercancía: entrada_compra por línea, idempotente por (orden, recepción, línea)."""
    if po.status not in ("solicitada", "recibida_parcial", "aprobada"):
        raise ApiError("Solo se recibe mercancía de órdenes aprobadas o solicitadas.", 409)
    if not receipt_ref:
        receipt_ref = _number("REC")
    by_id = {line.id: line for line in po.lines}
    applied = 0
    for index, entry in enumerate(lines or []):
        line = by_id.get(entry.get("line_id")) if isinstance(entry, dict) else None
        qty = entry.get("quantity") if isinstance(entry, dict) else None
        if line is None:
            raise ApiError("Datos no válidos.", 422, {f"lines[{index}]": "La línea no pertenece a la orden."})
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0 or qty > line.quantity_ordered - line.quantity_received:
            raise ApiError("Datos no válidos.", 422,
                           {f"lines[{index}]": f"Cantidad entre 1 y {line.quantity_ordered - line.quantity_received}."})
        external_ref = f"{po.number}:{receipt_ref}:{line.id}"
        if db.session.execute(select(InventoryMovement.id).where(
                InventoryMovement.channel == "compras", InventoryMovement.external_ref == external_ref)).first():
            continue  # recepción ya registrada (reintento): no se duplica el stock
        variant = lock_variant(line.variant_id)
        cost = line.unit_cost
        if entry.get("unit_cost") is not None:
            cost = Decimal(str(entry["unit_cost"])).quantize(Decimal("0.01"))
        apply_movement(variant, "entrada_compra", qty, location=po.location, unit_cost=cost, channel="compras",
                       reason=f"Recepción de {po.number}", reference=po.number, external_ref=external_ref)
        line.quantity_received += qty
        if cost is not None and variant.cost != cost:
            variant.cost = cost
            db.session.add(PriceHistory(variant_id=variant.id, cost=cost, price=variant.price, source="compra",
                                        user_id=g.user.id))
        applied += 1
    if all(line.quantity_received == line.quantity_ordered for line in po.lines):
        po.status, po.received_at = "recibida", utcnow()
    elif any(line.quantity_received for line in po.lines):
        po.status = "recibida_parcial"
    for line in po.lines:
        if line.quantity_received == line.quantity_ordered:
            rec = db.session.execute(select(ReplenishmentRecommendation).where(
                ReplenishmentRecommendation.po_line_id == line.id)).scalar_one_or_none()
            if rec:
                rec.status = "recibida"
    audit("recepcion_compra", "purchase_order", po.id, {"numero": po.number, "recepcion": receipt_ref, "lineas": applied})
    db.session.commit()
    return applied
