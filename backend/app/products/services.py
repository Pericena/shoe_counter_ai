"""Ficha consolidada de un producto: todo lo relacionado con él en un solo lugar.

Se usa en el detalle del producto, en el lector de etiquetas y en el conteo inteligente para que,
cuando se reconoce un producto ya registrado, se vea su marca, modelo, características y stock.
"""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from ..common import iso, utcnow
from ..extensions import db
from ..inventory.models import OUTBOUND_SALES_TYPES, InventoryMovement
from .models import Product, ProductVariant

OPEN_ORDER_STATUSES = ("creado", "pago_confirmado", "preparado")


def _sizes_sorted(sizes):
    def key(size):
        try:
            return (0, float(str(size).replace(",", ".")), str(size))
        except ValueError:
            return (1, 0.0, str(size))
    return sorted(sizes, key=key)


def variant_activity(variant_ids, days=30):
    """Ventas netas recientes y fecha del último movimiento por variante."""
    if not variant_ids:
        return {}
    since = utcnow() - timedelta(days=days)
    sold = dict(db.session.execute(
        select(InventoryMovement.variant_id, func.coalesce(func.sum(-InventoryMovement.quantity), 0))
        .where(InventoryMovement.variant_id.in_(variant_ids), InventoryMovement.created_at >= since,
               InventoryMovement.movement_type.in_(OUTBOUND_SALES_TYPES))
        .group_by(InventoryMovement.variant_id)).all())
    last = dict(db.session.execute(
        select(InventoryMovement.variant_id, func.max(InventoryMovement.created_at))
        .where(InventoryMovement.variant_id.in_(variant_ids)).group_by(InventoryMovement.variant_id)).all())
    return {vid: {"sold_recent": int(sold.get(vid, 0)), "last_movement_at": iso(last.get(vid))} for vid in variant_ids}


def product_card(product, highlight_variant_ids=(), detail=False):
    """Ficha del producto. `highlight_variant_ids`: variantes reconocidas (código, etiqueta o conteo)."""
    from ..ai.models import AICount
    from ..shop.models import Order, OrderItem

    variants = list(product.variants)
    ids = [v.id for v in variants]
    activity = variant_activity(ids)
    pairs = sum(v.stock_quantity for v in variants)
    value_cost = sum((v.cost * v.stock_quantity for v in variants if v.cost is not None), Decimal("0"))
    value_price = sum((v.price * v.stock_quantity for v in variants if v.price is not None), Decimal("0"))
    reserved = dict(db.session.execute(
        select(OrderItem.variant_id, func.sum(OrderItem.quantity)).join(Order)
        .where(OrderItem.variant_id.in_(ids), Order.status.in_(OPEN_ORDER_STATUSES))
        .group_by(OrderItem.variant_id)).all()) if ids else {}

    rows = []
    for v in variants:
        item = v.to_dict()
        item.update(activity.get(v.id, {}))
        item["reserved_open_orders"] = int(reserved.get(v.id, 0))
        item["highlight"] = v.id in highlight_variant_ids
        rows.append(item)
    sizes = _sizes_sorted({v.size for v in variants})
    colors = sorted({v.color for v in variants})
    matrix = {color: {size: None for size in sizes} for color in colors}
    for v in variants:
        matrix[v.color][v.size] = {"variant_id": v.id, "sku": v.sku, "stock": v.stock_quantity, "state": v.stock_state,
                                   "highlight": v.id in highlight_variant_ids}
    prices = [v.price for v in variants if v.price is not None]
    card = {
        "product": {
            "id": product.id, "code": product.code, "brand": product.brand.name, "model_name": product.model_name,
            "category": product.category.name if product.category else None, "footwear_type": product.footwear_type,
            "supplier": product.supplier.name if product.supplier else None, "description": product.description,
            "status": product.status, "is_published": product.is_published,
            "images": [i.to_dict() for i in product.images],
        },
        "totals": {
            "variants": len(variants), "pairs": pairs,
            "value_at_cost": str(value_cost.quantize(Decimal("0.01"))),
            "value_at_price": str(value_price.quantize(Decimal("0.01"))),
            "cost_complete": all(v.cost is not None for v in variants if v.stock_quantity),
            "low": sum(1 for v in variants if 0 < v.stock_quantity <= v.min_stock),
            "out": sum(1 for v in variants if v.stock_quantity == 0),
            "sold_last_30_days": sum(a["sold_recent"] for a in activity.values()),
            "reserved_open_orders": int(sum(reserved.values())) if reserved else 0,
            "price_min": str(min(prices)) if prices else None, "price_max": str(max(prices)) if prices else None,
        },
        "sizes": sizes, "colors": colors, "matrix": matrix, "variants": rows,
        "highlight_variant_ids": list(highlight_variant_ids),
    }
    if detail:
        movements = db.session.execute(
            select(InventoryMovement).where(InventoryMovement.variant_id.in_(ids))
            .order_by(InventoryMovement.id.desc()).limit(25)).scalars().all() if ids else []
        counts = db.session.execute(
            select(AICount).where(AICount.variant_id.in_(ids)).order_by(AICount.id.desc()).limit(10)
        ).scalars().all() if ids else []
        card["recent_movements"] = [m.to_dict() for m in movements]
        card["recent_counts"] = [c.to_dict(with_detections=False) for c in counts]
    return card


def card_for_variant(variant_id):
    variant = db.session.get(ProductVariant, variant_id)
    if variant is None:
        return None
    return product_card(variant.product, highlight_variant_ids=(variant.id,))


def get_product(product_id):
    return db.session.get(Product, product_id)
