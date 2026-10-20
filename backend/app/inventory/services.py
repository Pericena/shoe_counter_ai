"""Única vía para cambiar el stock. Bloquea la fila de la variante durante la transacción."""
from flask import g, has_request_context
from sqlalchemy import func, select

from ..audit.services import audit
from ..common import ApiError
from ..extensions import db
from ..products.models import ProductVariant
from .models import MOVEMENT_TYPES, InventoryMovement


def lock_variant(variant_id):
    """SELECT … FOR UPDATE: en PostgreSQL serializa operaciones concurrentes sobre la variante.

    populate_existing=True es imprescindible: si la variante ya estaba cargada en la sesión, sin él
    SQLAlchemy devolvería el objeto con el stock leído ANTES del bloqueo (venta duplicada).
    """
    variant = db.session.execute(
        select(ProductVariant).where(ProductVariant.id == variant_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if variant is None:
        raise ApiError("La variante no existe.", 404)
    return variant


def apply_movement(variant, movement_type, delta, *, unit_cost=None, reason=None, reference=None,
                   count_id=None, order_id=None, user=None):
    """Aplica un movimiento sobre una variante YA bloqueada. No confirma la transacción."""
    new_balance = variant.stock_quantity + delta
    if new_balance < 0:
        raise ApiError(f"Stock insuficiente: hay {variant.stock_quantity} pares de {variant.sku}.", 409,
                       {"variant_id": variant.id, "available": variant.stock_quantity})
    if user is None and has_request_context():
        user = getattr(g, "user", None)
    movement = InventoryMovement(
        variant_id=variant.id, movement_type=movement_type, quantity=delta, balance_after=new_balance,
        unit_cost=unit_cost, reason=reason, reference=reference, count_id=count_id, order_id=order_id,
        user_id=user.id if user else None,
    )
    variant.stock_quantity = new_balance
    db.session.add(movement)
    db.session.flush()
    audit("movimiento_inventario", "variant", variant.id, {
        "movement_id": movement.id, "tipo": movement_type, "cantidad": delta, "saldo": new_balance,
        "referencia": reference,
    }, user=user)
    return movement


def register_movement(*, variant_id, movement_type, quantity=None, counted_quantity=None,
                      unit_cost=None, reason=None, reference=None, count_id=None, commit=True):
    """Registra un movimiento manual y actualiza el saldo en la misma transacción.

    - entradas/salidas/devoluciones: `quantity` > 0; el signo lo pone el tipo.
    - ajuste: `quantity` con signo y `reason` obligatorio.
    - conteo_fisico: `counted_quantity` >= 0; se registra la diferencia.
      Si no hay diferencia, no se crea movimiento (devuelve None).
    """
    if movement_type not in MOVEMENT_TYPES:
        raise ApiError("Tipo de movimiento no permitido.", 422)

    variant = lock_variant(variant_id)
    sign = MOVEMENT_TYPES[movement_type]

    if movement_type == "conteo_fisico":
        if counted_quantity is None or counted_quantity < 0:
            raise ApiError("El conteo físico requiere 'counted_quantity' >= 0.", 422)
        delta = counted_quantity - variant.stock_quantity
        system_qty = variant.stock_quantity
        if delta == 0:
            audit("conteo_sin_diferencia", "variant", variant.id,
                  {"contado": counted_quantity, "referencia": reference, "count_id": count_id})
            if commit:
                db.session.commit()
            return None
        reason = (reason + " — " if reason else "") + f"Conteo físico: sistema {system_qty}, contado {counted_quantity}"
    elif movement_type == "ajuste":
        if not quantity:
            raise ApiError("El ajuste requiere 'quantity' distinto de 0.", 422)
        if not reason:
            raise ApiError("Todo ajuste debe justificarse en 'reason'.", 422)
        delta = quantity
    else:
        if quantity is None or quantity <= 0:
            raise ApiError("'quantity' debe ser un entero mayor que 0.", 422)
        delta = sign * quantity

    movement = apply_movement(variant, movement_type, delta, unit_cost=unit_cost, reason=reason,
                              reference=reference, count_id=count_id)
    if commit:
        db.session.commit()
    return movement


def ledger_balance_before(variant_ids, moment):
    """Saldo de cada variante justo antes de `moment`, reconstruido desde el libro mayor."""
    query = (select(InventoryMovement.variant_id, func.coalesce(func.sum(InventoryMovement.quantity), 0))
             .where(InventoryMovement.created_at < moment))
    if variant_ids is not None:
        query = query.where(InventoryMovement.variant_id.in_(variant_ids))
    return {vid: int(total) for vid, total in db.session.execute(query.group_by(InventoryMovement.variant_id))}


def reconciliation():
    """Compara el saldo guardado de cada variante con la suma de sus movimientos."""
    sums = dict(db.session.execute(
        select(InventoryMovement.variant_id, func.coalesce(func.sum(InventoryMovement.quantity), 0))
        .group_by(InventoryMovement.variant_id)
    ).all())
    mismatches = []
    variants = db.session.execute(select(ProductVariant)).scalars().all()
    for variant in variants:
        ledger = int(sums.get(variant.id, 0))
        if ledger != variant.stock_quantity:
            mismatches.append({
                "variant_id": variant.id,
                "sku": variant.sku,
                "stock_quantity": variant.stock_quantity,
                "ledger_sum": ledger,
            })
    return {"variants_checked": len(variants), "mismatches": mismatches, "ok": not mismatches}
