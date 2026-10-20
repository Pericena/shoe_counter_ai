from decimal import Decimal

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from ..auth.services import require
from ..common import ApiError, Validator, json_body, parse_date_range, query_int
from ..extensions import db
from ..products.models import Brand, Product, ProductVariant
from .models import MOVEMENT_TYPES, SALES_MOVEMENT_TYPES, SYSTEM_MOVEMENT_TYPES, InventoryMovement
from .services import reconciliation, register_movement

bp = Blueprint("inventory", __name__, url_prefix="/api/inventory")


def stock_query():
    """Consulta de variantes con los filtros de la petición (reutilizada por exportaciones)."""
    query = select(ProductVariant).join(Product).join(Brand)
    if (product_id := query_int("product_id")) is not None:
        query = query.where(ProductVariant.product_id == product_id)
    if (brand_id := query_int("brand_id")) is not None:
        query = query.where(Product.brand_id == brand_id)
    if (category_id := query_int("category_id")) is not None:
        query = query.where(Product.category_id == category_id)
    if size := request.args.get("size"):
        query = query.where(ProductVariant.size == size.strip())
    if color := request.args.get("color"):
        query = query.where(func.lower(ProductVariant.color) == color.strip().lower())
    if q := request.args.get("q"):
        like = f"%{q.strip().lower()}%"
        query = query.where(
            func.lower(Product.model_name).like(like)
            | func.lower(Brand.name).like(like)
            | func.lower(ProductVariant.sku).like(like)
            | func.lower(func.coalesce(ProductVariant.barcode, "")).like(like)
        )
    state = request.args.get("state")
    if state == "agotado":
        query = query.where(ProductVariant.stock_quantity == 0)
    elif state == "bajo":
        query = query.where(ProductVariant.stock_quantity > 0,
                            ProductVariant.stock_quantity <= ProductVariant.min_stock)
    elif state == "alerta":
        query = query.where(ProductVariant.stock_quantity <= ProductVariant.min_stock)
    elif state not in (None, ""):
        raise ApiError("'state' debe ser 'agotado', 'bajo' o 'alerta'.")
    return query.order_by(Brand.name, Product.model_name, ProductVariant.size, ProductVariant.color)


def stock_item(v):
    item = v.to_dict()
    item.update({
        "brand": v.product.brand.name,
        "model_name": v.product.model_name,
        "product_code": v.product.code,
        "category": v.product.category.name if v.product.category else None,
        "inventory_value": str(v.cost * v.stock_quantity) if v.cost is not None else None,
    })
    return item


@bp.get("/stock")
@require("inventory.view")
def stock():
    """Existencias por modelo, talla y color con resumen sobre TODO el resultado filtrado."""
    limit = query_int("limit", default=50, minimum=1, maximum=500)
    offset = query_int("offset", default=0, minimum=0)
    rows = db.session.execute(stock_query()).scalars().all()
    total_value = Decimal("0")
    value_complete = True
    for v in rows:
        if v.cost is None:
            value_complete = value_complete and v.stock_quantity == 0
        else:
            total_value += v.cost * v.stock_quantity
    return jsonify({
        "items": [stock_item(v) for v in rows[offset:offset + limit]],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "summary": {
            "variants": len(rows),
            "pairs": sum(v.stock_quantity for v in rows),
            "inventory_value_at_cost": str(total_value.quantize(Decimal("0.01"))),
            "inventory_value_complete": value_complete,
            "low": sum(1 for v in rows if 0 < v.stock_quantity <= v.min_stock),
            "out": sum(1 for v in rows if v.stock_quantity == 0),
        },
    })


@bp.post("/movements")
@require("inventory.view")
def create_movement():
    data = json_body()
    v = Validator(data)
    v.integer("variant_id", required=True, minimum=1)
    v.choice("movement_type", tuple(t for t in MOVEMENT_TYPES if t not in SYSTEM_MOVEMENT_TYPES), required=True)
    v.integer("quantity")
    v.integer("counted_quantity", minimum=0)
    v.money("unit_cost")
    v.text("reason", max_len=1000)
    v.text("reference", max_len=100)
    clean = v.raise_if_errors()
    needed = "inventory.sell" if clean["movement_type"] in SALES_MOVEMENT_TYPES else "inventory.move"
    if not g.user.has(needed) and not g.user.has("inventory.move"):
        raise ApiError("No tienes permiso para este tipo de movimiento.", 403, {"required": [needed]})
    movement = register_movement(**clean)
    if movement is None:
        return jsonify({"movement": None, "message": "El conteo coincide con el stock; no se registró ajuste."})
    return jsonify({"movement": movement.to_dict()}), 201


def movements_query():
    query = select(InventoryMovement).join(ProductVariant).join(Product)
    if (variant_id := query_int("variant_id")) is not None:
        query = query.where(InventoryMovement.variant_id == variant_id)
    if (product_id := query_int("product_id")) is not None:
        query = query.where(ProductVariant.product_id == product_id)
    if (category_id := query_int("category_id")) is not None:
        query = query.where(Product.category_id == category_id)
    if movement_type := request.args.get("movement_type"):
        query = query.where(InventoryMovement.movement_type.in_(movement_type.split(",")))
    start, end = parse_date_range()
    if start:
        query = query.where(InventoryMovement.created_at >= start)
    if end:
        query = query.where(InventoryMovement.created_at < end)
    return query.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())


@bp.get("/movements")
@require("inventory.view")
def list_movements():
    limit = query_int("limit", default=50, minimum=1, maximum=500)
    offset = query_int("offset", default=0, minimum=0)
    query = movements_query()
    total = db.session.execute(select(func.count()).select_from(query.order_by(None).subquery())).scalar_one()
    rows = db.session.execute(query.limit(limit).offset(offset)).scalars().all()
    return jsonify({"items": [m.to_dict() for m in rows], "total": total, "limit": limit, "offset": offset})


@bp.get("/reconciliation")
@require("inventory.view")
def reconcile():
    return jsonify(reconciliation())
