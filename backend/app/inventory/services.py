"""Única vía para cambiar el stock.

Reglas:
  - Cada cambio de existencias es un InventoryMovement inmutable con usuario, ubicación, canal y motivo.
  - Se bloquean (SELECT … FOR UPDATE) la variante y su nivel en la ubicación durante la transacción.
  - Físico total de la variante = Σ quantity; reservado = Σ reserved_delta; por ubicación igual.
  - No se permite stock negativo ni reservar más de lo disponible.
  - Un mismo evento externo (canal + external_ref) solo se aplica una vez (idempotencia).
"""
from flask import g, has_request_context
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..audit.services import audit
from ..common import ApiError
from ..extensions import db
from ..products.models import ProductVariant
from .models import MOVEMENT_TYPES, InventoryMovement, Location, StockLevel


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


def default_location():
    location = db.session.execute(
        select(Location).where(Location.is_default.is_(True), Location.is_active.is_(True))).scalars().first()
    if location is None:
        location = db.session.execute(select(Location).where(Location.is_active.is_(True)).order_by(Location.id)).scalars().first()
    if location is None:
        location = Location(code="PRINCIPAL", name="Tienda principal", kind="tienda", is_default=True)
        db.session.add(location)
        db.session.flush()
    return location


def resolve_location(location_id=None):
    if location_id is None:
        return default_location()
    location = db.session.get(Location, location_id)
    if location is None or not location.is_active:
        raise ApiError("La ubicación no existe o está inactiva.", 404)
    return location


def lock_level(variant, location):
    level = db.session.execute(
        select(StockLevel).where(StockLevel.variant_id == variant.id, StockLevel.location_id == location.id)
        .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if level is None:
        level = StockLevel(variant_id=variant.id, location_id=location.id, on_hand=0, reserved=0)
        db.session.add(level)
        db.session.flush()
    return level


def find_by_external_ref(channel, external_ref):
    if not external_ref:
        return None
    return db.session.execute(select(InventoryMovement).where(
        InventoryMovement.channel == channel, InventoryMovement.external_ref == external_ref)).scalar_one_or_none()


def apply_movement(variant, movement_type, delta, *, reserved_delta=0, location=None, counterpart=None,
                   unit_cost=None, reason=None, reference=None, count_id=None, order_id=None, user=None,
                   channel="tienda", external_ref=None, evidence_file_id=None):
    """Aplica un movimiento sobre una variante YA bloqueada. No confirma la transacción."""
    if movement_type not in MOVEMENT_TYPES:
        raise ApiError("Tipo de movimiento no permitido.", 422)
    if delta == 0 and reserved_delta == 0:
        raise ApiError("El movimiento no cambia ninguna cantidad.", 422)
    location = location or default_location()
    level = lock_level(variant, location)
    new_on_hand = level.on_hand + delta
    new_reserved = level.reserved + reserved_delta
    if new_on_hand < 0:
        raise ApiError(f"Stock insuficiente en {location.name}: hay {level.on_hand} pares de {variant.sku}.", 409,
                       {"variant_id": variant.id, "available": level.on_hand - level.reserved,
                        "on_hand": level.on_hand, "location_id": location.id})
    if new_reserved < 0:
        raise ApiError("No se puede liberar más reserva de la existente.", 409)
    if new_reserved > new_on_hand:
        raise ApiError(f"Stock disponible insuficiente en {location.name}: {level.on_hand - level.reserved} pares "
                       f"disponibles de {variant.sku} ({level.reserved} reservados).", 409,
                       {"variant_id": variant.id, "available": level.on_hand - level.reserved,
                        "location_id": location.id})
    if user is None and has_request_context():
        user = getattr(g, "user", None)
    stock_before = variant.stock_quantity
    level.on_hand, level.reserved = new_on_hand, new_reserved
    variant.stock_quantity += delta
    variant.reserved_quantity += reserved_delta
    movement = InventoryMovement(
        variant_id=variant.id, location_id=location.id, counterpart_location_id=counterpart.id if counterpart else None,
        movement_type=movement_type, quantity=delta, reserved_delta=reserved_delta, stock_before=stock_before,
        balance_after=variant.stock_quantity, location_balance_after=new_on_hand, unit_cost=unit_cost,
        reason=reason, reference=reference, count_id=count_id, order_id=order_id, user_id=user.id if user else None,
        channel=channel, external_ref=external_ref, evidence_file_id=evidence_file_id,
    )
    db.session.add(movement)
    try:
        with db.session.begin_nested():
            db.session.flush()
    except IntegrityError:
        raise ApiError("Este evento ya se registró (referencia externa duplicada).", 409,
                       {"external_ref": external_ref, "channel": channel})
    audit("movimiento_inventario", "variant", variant.id, {
        "movement_id": movement.id, "tipo": movement_type, "cantidad": delta, "reservado": reserved_delta,
        "saldo": variant.stock_quantity, "ubicacion": location.code, "referencia": reference, "canal": channel,
    }, user=user)
    return movement


def register_movement(*, variant_id, movement_type, quantity=None, counted_quantity=None,
                      unit_cost=None, reason=None, reference=None, count_id=None, location_id=None,
                      channel="tienda", external_ref=None, evidence_file_id=None, commit=True):
    """Registra un movimiento manual y actualiza los saldos en la misma transacción.

    - entradas/salidas/devoluciones/bajas: `quantity` > 0; el signo lo pone el tipo.
    - ajuste: `quantity` con signo y `reason` obligatorio.
    - conteo_fisico: `counted_quantity` >= 0 en la ubicación; se registra la diferencia.
      Si no hay diferencia, no se crea movimiento (devuelve None).
    - Si `external_ref` ya existe para el canal, devuelve el movimiento original (idempotente).
    """
    if movement_type not in MOVEMENT_TYPES:
        raise ApiError("Tipo de movimiento no permitido.", 422)
    previous = find_by_external_ref(channel, external_ref)
    if previous is not None:
        return previous

    variant = lock_variant(variant_id)
    location = resolve_location(location_id)
    sign = MOVEMENT_TYPES[movement_type]

    if movement_type == "conteo_fisico":
        if counted_quantity is None or counted_quantity < 0:
            raise ApiError("El conteo físico requiere 'counted_quantity' >= 0.", 422)
        level = lock_level(variant, location)
        delta = counted_quantity - level.on_hand
        system_qty = level.on_hand
        if delta == 0:
            audit("conteo_sin_diferencia", "variant", variant.id,
                  {"contado": counted_quantity, "ubicacion": location.code, "referencia": reference, "count_id": count_id})
            if commit:
                db.session.commit()
            return None
        if counted_quantity < level.reserved:
            raise ApiError(f"El conteo ({counted_quantity}) es menor que lo reservado para pedidos ({level.reserved}). "
                           "Revisa los pedidos pendientes antes de ajustar.", 409)
        reason = (reason + " — " if reason else "") + f"Conteo físico en {location.name}: sistema {system_qty}, contado {counted_quantity}"
    elif movement_type in ("ajuste",):
        if not quantity:
            raise ApiError("El ajuste requiere 'quantity' distinto de 0.", 422)
        if not reason:
            raise ApiError("Todo ajuste debe justificarse en 'reason'.", 422)
        delta = quantity
    elif movement_type in ("danado", "perdido"):
        if quantity is None or quantity <= 0:
            raise ApiError("'quantity' debe ser un entero mayor que 0.", 422)
        if not reason:
            raise ApiError("Indica el motivo de la baja en 'reason'.", 422)
        delta = -quantity
    else:
        if quantity is None or quantity <= 0:
            raise ApiError("'quantity' debe ser un entero mayor que 0.", 422)
        delta = sign * quantity
        if movement_type == "stock_inicial":
            already = db.session.execute(select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.variant_id == variant.id, InventoryMovement.location_id == location.id,
                InventoryMovement.movement_type == "stock_inicial")).scalar_one()
            if already:
                raise ApiError(f"{variant.sku} ya tiene stock inicial en {location.name}; usa un ajuste o un conteo físico.", 409)

    movement = apply_movement(variant, movement_type, delta, location=location, unit_cost=unit_cost, reason=reason,
                              reference=reference, count_id=count_id, channel=channel, external_ref=external_ref,
                              evidence_file_id=evidence_file_id)
    if commit:
        db.session.commit()
    return movement


def transfer(*, variant_id, from_location_id, to_location_id, quantity, reason=None, reference=None, commit=True):
    """Transferencia entre ubicaciones: dos movimientos con el mismo documento; el total no cambia."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ApiError("'quantity' debe ser un entero mayor que 0.", 422)
    if from_location_id == to_location_id:
        raise ApiError("El origen y el destino deben ser distintos.", 422)
    variant = lock_variant(variant_id)
    origin, destination = resolve_location(from_location_id), resolve_location(to_location_id)
    document = reference or f"TRF-{variant.id}-{origin.code}-{destination.code}"
    out = apply_movement(variant, "transferencia_salida", -quantity, location=origin, counterpart=destination,
                         reason=reason, reference=document)
    inn = apply_movement(variant, "transferencia_entrada", quantity, location=destination, counterpart=origin,
                         reason=reason, reference=document)
    if commit:
        db.session.commit()
    return out, inn


def ledger_balance_before(variant_ids, moment):
    """Saldo físico de cada variante justo antes de `moment`, reconstruido desde el libro mayor."""
    query = (select(InventoryMovement.variant_id, func.coalesce(func.sum(InventoryMovement.quantity), 0))
             .where(InventoryMovement.created_at < moment))
    if variant_ids is not None:
        query = query.where(InventoryMovement.variant_id.in_(variant_ids))
    return {vid: int(total) for vid, total in db.session.execute(query.group_by(InventoryMovement.variant_id))}


def reconciliation():
    """Compara saldos guardados (variante y ubicación, físico y reservado) con el libro de movimientos."""
    totals = {vid: (int(q), int(r)) for vid, q, r in db.session.execute(
        select(InventoryMovement.variant_id, func.coalesce(func.sum(InventoryMovement.quantity), 0),
               func.coalesce(func.sum(InventoryMovement.reserved_delta), 0)).group_by(InventoryMovement.variant_id))}
    per_location = {(vid, lid): (int(q), int(r)) for vid, lid, q, r in db.session.execute(
        select(InventoryMovement.variant_id, InventoryMovement.location_id,
               func.coalesce(func.sum(InventoryMovement.quantity), 0),
               func.coalesce(func.sum(InventoryMovement.reserved_delta), 0))
        .group_by(InventoryMovement.variant_id, InventoryMovement.location_id))}
    mismatches = []
    variants = db.session.execute(select(ProductVariant)).scalars().all()
    for variant in variants:
        ledger, reserved = totals.get(variant.id, (0, 0))
        if ledger != variant.stock_quantity or reserved != variant.reserved_quantity:
            mismatches.append({"variant_id": variant.id, "sku": variant.sku, "stock_quantity": variant.stock_quantity,
                               "ledger_sum": ledger, "reserved_quantity": variant.reserved_quantity,
                               "ledger_reserved": reserved})
    for level in db.session.execute(select(StockLevel)).scalars():
        ledger, reserved = per_location.get((level.variant_id, level.location_id), (0, 0))
        if ledger != level.on_hand or reserved != level.reserved:
            mismatches.append({"variant_id": level.variant_id, "location_id": level.location_id,
                               "on_hand": level.on_hand, "ledger_sum": ledger,
                               "reserved": level.reserved, "ledger_reserved": reserved})
    return {"variants_checked": len(variants), "mismatches": mismatches, "ok": not mismatches}
