from decimal import Decimal

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from ..auth.services import require
from ..common import ApiError, Validator, json_body, parse_date_range, query_int
from ..extensions import db
from ..products.models import Brand, Product, ProductVariant
from ..audit.services import audit
from ..files.services import save_image
from .models import LOCATION_KINDS, MOVEMENT_TYPES, SALES_MOVEMENT_TYPES, SYSTEM_MOVEMENT_TYPES, InventoryMovement, Location, StockLevel
from .services import reconciliation, register_movement, transfer
from .settings import all_settings, set_setting

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
    if (location_id := query_int("location_id")) is not None:
        query = query.where(ProductVariant.id.in_(select(StockLevel.variant_id).where(StockLevel.location_id == location_id)))
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
        "sale_value": str(v.price * v.stock_quantity) if v.price is not None else None,
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
    page = rows[offset:offset + limit]
    from ..products.services import variant_activity
    activity = variant_activity([v.id for v in page])
    items = []
    for v in page:
        item = stock_item(v)
        item.update(activity.get(v.id, {}))
        items.append(item)
    return jsonify({
        "items": items,
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "summary": {
            "variants": len(rows),
            "pairs": sum(v.stock_quantity for v in rows),
            "reserved": sum(v.reserved_quantity for v in rows),
            "available": sum(v.stock_quantity - v.reserved_quantity for v in rows),
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
    v.integer("location_id", minimum=1)
    v.integer("evidence_file_id", minimum=1)
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
    if (location_id := query_int("location_id")) is not None:
        query = query.where(InventoryMovement.location_id == location_id)
    if channel := request.args.get("channel"):
        query = query.where(InventoryMovement.channel == channel)
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


@bp.post("/evidence")
@require("inventory.move")
def upload_evidence():
    """Foto de evidencia para un ajuste/baja; devuelve el file_id a enviar en el movimiento."""
    stored = save_image(request.files.get("image"), "conteo")
    db.session.commit()
    return jsonify({"file_id": stored.id, "url": f"/api/files/{stored.id}"}), 201


@bp.post("/transfers")
@require("inventory.move")
def create_transfer():
    data = json_body()
    v = Validator(data)
    v.integer("variant_id", required=True, minimum=1)
    v.integer("from_location_id", required=True, minimum=1)
    v.integer("to_location_id", required=True, minimum=1)
    v.integer("quantity", required=True, minimum=1)
    v.text("reason", max_len=1000)
    v.text("reference", max_len=100)
    clean = v.raise_if_errors()
    out, inn = transfer(**clean)
    return jsonify({"out": out.to_dict(), "in": inn.to_dict()}), 201


@bp.get("/variants/<int:variant_id>/levels")
@require("inventory.view")
def variant_levels(variant_id):
    levels = db.session.execute(select(StockLevel).where(StockLevel.variant_id == variant_id)).scalars().all()
    return jsonify({"items": [lv.to_dict() for lv in levels]})


@bp.patch("/variants/<int:variant_id>/levels/<int:location_id>")
@require("locations.manage")
def set_bin(variant_id, location_id):
    level = db.session.get(StockLevel, (variant_id, location_id))
    if level is None:
        raise ApiError("No hay stock registrado de esa variante en esa ubicación.", 404)
    v = Validator(json_body())
    v.text("bin", max_len=60)
    level.bin = v.raise_if_errors().get("bin")
    audit("ubicacion_estante", "variant", variant_id, {"ubicacion": location_id, "estante": level.bin})
    db.session.commit()
    return jsonify(level.to_dict())


@bp.get("/locations")
@require("inventory.view")
def list_locations():
    rows = db.session.execute(select(Location).order_by(Location.is_default.desc(), Location.name)).scalars().all()
    totals = dict(db.session.execute(select(StockLevel.location_id, func.sum(StockLevel.on_hand))
                                     .group_by(StockLevel.location_id)).all())
    return jsonify({"items": [{**loc.to_dict(), "pairs": int(totals.get(loc.id, 0) or 0)} for loc in rows]})


@bp.post("/locations")
@require("locations.manage")
def create_location():
    data = json_body()
    v = Validator(data)
    v.text("code", required=True, max_len=30)
    v.text("name", required=True, max_len=120)
    v.choice("kind", LOCATION_KINDS, required=True)
    v.text("address", max_len=300)
    clean = v.raise_if_errors()
    clean["code"] = clean["code"].upper()
    if db.session.execute(select(Location).where(Location.code == clean["code"])).first():
        raise ApiError("Ya existe una ubicación con ese código.", 409)
    location = Location(**clean)
    db.session.add(location)
    db.session.flush()
    audit("ubicacion_creada", "location", location.id, clean)
    db.session.commit()
    return jsonify(location.to_dict()), 201


@bp.patch("/locations/<int:location_id>")
@require("locations.manage")
def update_location(location_id):
    location = db.session.get(Location, location_id)
    if location is None:
        raise ApiError("La ubicación no existe.", 404)
    data = json_body()
    v = Validator(data)
    v.text("name", max_len=120)
    v.text("address", max_len=300)
    clean = v.raise_if_errors()
    if clean.get("name"):
        location.name = clean["name"]
    if "address" in clean:
        location.address = clean["address"]
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise ApiError("Datos no válidos.", 422, {"is_active": "true o false."})
        if not data["is_active"]:
            stock = db.session.execute(select(func.coalesce(func.sum(StockLevel.on_hand), 0)).where(
                StockLevel.location_id == location.id)).scalar_one()
            if stock:
                raise ApiError(f"No se puede desactivar: tiene {stock} pares. Transfiérelos antes.", 409)
        location.is_active = data["is_active"]
    if data.get("is_default") is True:
        for other in db.session.execute(select(Location)).scalars():
            other.is_default = other.id == location.id
    audit("ubicacion_modificada", "location", location.id,
          {k: data.get(k) for k in ("name", "address", "is_active", "is_default") if k in data})
    db.session.commit()
    return jsonify(location.to_dict())


@bp.get("/settings")
@require("settings.view")
def get_settings():
    return jsonify({"items": all_settings()})


@bp.patch("/settings")
@require("settings.manage")
def update_settings():
    data = json_body()
    changed = {}
    for key, value in data.items():
        try:
            set_setting(key, value, g.user)
        except KeyError:
            raise ApiError("Parámetro desconocido.", 422, {key: "No existe."})
        except ValueError as error:
            raise ApiError("Datos no válidos.", 422, {key: str(error)})
        changed[key] = value
    audit("configuracion_modificada", "settings", None, changed)
    db.session.commit()
    return jsonify({"items": all_settings()})
