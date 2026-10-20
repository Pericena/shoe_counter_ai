"""Tienda online: catálogo público, pedidos y gestión de pedidos por el personal.

No hay cobro en línea: el pedido se crea "pendiente de pago" y el personal confirma el pago
manualmente (transferencia, efectivo…) hasta que se integre un proveedor de pagos.
"""
import secrets
from decimal import Decimal

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func, select

from ..audit.services import audit, client_ip
from ..auth.services import check_rate, require
from ..common import ApiError, Validator, json_body, parse_date_range, query_int
from ..extensions import db
from ..inventory.services import apply_movement, lock_variant
from ..products.models import Brand, Category, Product, ProductVariant
from .models import ORDER_STATUSES, ORDER_TRANSITIONS, Order, OrderItem, OrderStatusHistory

bp = Blueprint("shop", __name__, url_prefix="/api")
MAX_LINES = 20
MAX_QTY_PER_LINE = 10
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _sellable(variant):
    return (variant.status == "activo" and variant.price is not None
            and variant.product.status == "activo" and variant.product.is_published)


def _public_product(product):
    variants = [v for v in product.variants if _sellable(v)]
    return {
        "id": product.id,
        "code": product.code,
        "brand": product.brand.name,
        "model_name": product.model_name,
        "category": product.category.name if product.category else None,
        "footwear_type": product.footwear_type,
        "description": product.description,
        "images": [i.to_dict() for i in product.images],
        "variants": [{"id": v.id, "size": v.size, "color": v.color, "price": str(v.price),
                      "available": v.stock_quantity > 0,
                      # Se muestra la cantidad solo si es baja, para no exponer el inventario completo.
                      "low_stock": 0 < v.stock_quantity <= 3} for v in variants],
        "price_from": str(min(v.price for v in variants)) if variants else None,
    }


@bp.get("/shop/products")
def shop_products():
    query = (select(Product).join(Brand)
             .where(Product.is_published.is_(True), Product.status == "activo"))
    if q := request.args.get("q"):
        like = f"%{q.strip().lower()}%"
        query = query.where(func.lower(Brand.name).like(like) | func.lower(Product.model_name).like(like))
    if (category_id := query_int("category_id")) is not None:
        query = query.where(Product.category_id == category_id)
    size = (request.args.get("size") or "").strip()
    color = (request.args.get("color") or "").strip().lower()
    only_available = request.args.get("available") == "1"
    products = db.session.execute(query.order_by(Brand.name, Product.model_name)).unique().scalars().all()
    items = []
    for product in products:
        data = _public_product(product)
        variants = data["variants"]
        if size:
            variants = [v for v in variants if v["size"] == size]
        if color:
            variants = [v for v in variants if v["color"].lower() == color]
        if only_available:
            variants = [v for v in variants if v["available"]]
        if not variants:
            continue
        data["variants"] = variants
        items.append(data)

    sellable = [v for p in products for v in p.variants if _sellable(v)]
    categories = db.session.execute(
        select(Category).join(Product, Product.category_id == Category.id).where(Product.is_published.is_(True), Product.status == "activo")
        .distinct().order_by(Category.name)).scalars().all()
    return jsonify({
        "items": items,
        "filters": {
            "sizes": sorted({v.size for v in sellable}, key=lambda s: (len(s), s)),
            "colors": sorted({v.color for v in sellable}),
            "categories": [c.to_dict() for c in categories],
        },
    })


@bp.get("/shop/products/<int:product_id>")
def shop_product(product_id):
    product = db.session.get(Product, product_id)
    if product is None or not product.is_published or product.status != "activo":
        raise ApiError("Producto no encontrado.", 404)
    return jsonify(_public_product(product))


def _order_code():
    while True:
        code = "PED-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.session.execute(select(Order.id).where(Order.code == code)).first():
            return code


def _parse_lines(raw_items):
    if not isinstance(raw_items, list) or not raw_items:
        raise ApiError("El carrito está vacío.", 422)
    if len(raw_items) > MAX_LINES:
        raise ApiError(f"Máximo {MAX_LINES} productos distintos por pedido.", 422)
    lines = {}
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ApiError("Datos no válidos.", 422, {f"items[{index}]": "Formato incorrecto."})
        variant_id, quantity = item.get("variant_id"), item.get("quantity")
        if isinstance(variant_id, bool) or not isinstance(variant_id, int):
            raise ApiError("Datos no válidos.", 422, {f"items[{index}]": "variant_id no válido."})
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_QTY_PER_LINE:
            raise ApiError("Datos no válidos.", 422,
                           {f"items[{index}]": f"La cantidad debe estar entre 1 y {MAX_QTY_PER_LINE}."})
        lines[variant_id] = lines.get(variant_id, 0) + quantity
    return lines


@bp.post("/shop/orders")
def create_order():
    """Crea el pedido y descuenta el stock en UNA transacción, bloqueando cada variante.

    Las variantes se bloquean en orden de id para evitar interbloqueos entre pedidos simultáneos.
    Si cualquier línea no tiene stock, se revierte todo: no quedan pedidos ni reservas a medias.
    """
    check_rate(f"order:{client_ip()}", current_app.config["ORDERS_PER_IP_PER_HOUR"], 60)
    db.session.commit()
    data = json_body()
    v = Validator(data)
    v.text("customer_name", required=True, max_len=150)
    v.text("customer_email", required=True, max_len=150)
    v.text("customer_phone", max_len=50)
    v.text("shipping_address", max_len=1000)
    v.text("notes", max_len=1000)
    clean = v.raise_if_errors()
    email = clean["customer_email"].lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ApiError("Datos no válidos.", 422, {"customer_email": "Correo no válido."})
    lines = _parse_lines(data.get("items"))

    order = Order(code=_order_code(), status="creado", customer_name=clean["customer_name"],
                  customer_email=email, customer_phone=clean.get("customer_phone"),
                  shipping_address=clean.get("shipping_address"), notes=clean.get("notes"),
                  total_amount=Decimal("0"))
    db.session.add(order)
    db.session.flush()
    total = Decimal("0")
    problems = {}
    for variant_id in sorted(lines):
        variant = db.session.get(ProductVariant, variant_id)
        if variant is None or not _sellable(variant):
            problems[str(variant_id)] = "El producto ya no está disponible."
            continue
        variant = lock_variant(variant_id)
        quantity = lines[variant_id]
        if variant.stock_quantity < quantity:
            problems[str(variant_id)] = f"Solo quedan {variant.stock_quantity} pares de {variant.sku}."
            continue
        line_total = variant.price * quantity
        total += line_total
        order.items.append(OrderItem(
            variant_id=variant.id, sku=variant.sku,
            description=f"{variant.product.brand.name} {variant.product.model_name}",
            size=variant.size, color=variant.color, quantity=quantity,
            unit_price=variant.price, line_total=line_total))
        apply_movement(variant, "salida_pedido", -quantity, reason="Reserva por pedido online",
                       reference=order.code, order_id=order.id)
    if problems:
        db.session.rollback()
        raise ApiError("Algunos productos del carrito no tienen stock suficiente.", 409, problems)
    order.total_amount = total
    order.history.append(OrderStatusHistory(from_status=None, to_status="creado", note="Pedido web"))
    audit("pedido_creado", "order", order.id, {"code": order.code, "total": str(total)})
    db.session.commit()
    return jsonify(order.to_dict(private=False)), 201


@bp.post("/shop/orders/lookup")
def lookup_order():
    """Consulta pública del estado: requiere el código y el correo usados en el pedido."""
    check_rate(f"lookup:{client_ip()}", 30, 15)
    db.session.commit()
    data = json_body()
    code = str(data.get("code") or "").strip().upper()
    email = str(data.get("email") or "").strip().lower()
    order = db.session.execute(select(Order).where(Order.code == code)).scalar_one_or_none()
    if order is None or not secrets.compare_digest(order.customer_email, email):
        raise ApiError("No encontramos un pedido con ese código y correo.", 404)
    return jsonify(order.to_dict(private=False))


# ---------- Gestión interna ----------

@bp.get("/orders")
@require("orders.view")
def list_orders():
    limit = query_int("limit", default=25, minimum=1, maximum=200)
    offset = query_int("offset", default=0, minimum=0)
    query = select(Order)
    if state := request.args.get("status"):
        if state not in ORDER_STATUSES:
            raise ApiError("Estado no válido.")
        query = query.where(Order.status == state)
    if q := request.args.get("q"):
        like = f"%{q.strip().lower()}%"
        query = query.where(func.lower(Order.code).like(like) | func.lower(Order.customer_name).like(like)
                            | func.lower(Order.customer_email).like(like))
    start, end = parse_date_range()
    if start:
        query = query.where(Order.created_at >= start)
    if end:
        query = query.where(Order.created_at < end)
    total = db.session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.session.execute(query.order_by(Order.id.desc()).limit(limit).offset(offset)).scalars().all()
    items = []
    for o in rows:
        items.append({"id": o.id, "code": o.code, "status": o.status, "customer_name": o.customer_name,
                      "customer_email": o.customer_email, "total_amount": str(o.total_amount),
                      "items": sum(i.quantity for i in o.items), "created_at": o.to_dict()["created_at"]})
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


@bp.get("/orders/<int:order_id>")
@require("orders.view")
def get_order(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        raise ApiError("El pedido no existe.", 404)
    return jsonify(order.to_dict())


@bp.post("/orders/<int:order_id>/status")
@require("orders.manage")
def change_order_status(order_id):
    data = json_body()
    new_status = data.get("status")
    note = str(data.get("note") or "").strip()[:1000] or None
    order = db.session.execute(select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if order is None:
        raise ApiError("El pedido no existe.", 404)
    if new_status not in ORDER_TRANSITIONS[order.status]:
        raise ApiError(f"No se puede pasar de '{order.status}' a '{new_status}'.", 409,
                       {"allowed": sorted(ORDER_TRANSITIONS[order.status])})
    if new_status == "pago_confirmado":
        reference = str(data.get("payment_reference") or "").strip()[:100]
        if not reference:
            raise ApiError("Datos no válidos.", 422,
                           {"payment_reference": "Indica la referencia del pago recibido (transferencia, recibo…)."})
        order.payment_reference = reference
    if new_status in ("cancelado", "devuelto"):
        if not note:
            raise ApiError("Datos no válidos.", 422, {"note": "Indica el motivo."})
        movement_type = "cancelacion_pedido" if new_status == "cancelado" else "devolucion_cliente"
        for item in sorted(order.items, key=lambda i: i.variant_id):
            variant = lock_variant(item.variant_id)
            apply_movement(variant, movement_type, item.quantity, reason=f"Pedido {order.code}: {note}",
                           reference=order.code, order_id=order.id)
    order.history.append(OrderStatusHistory(from_status=order.status, to_status=new_status,
                                            user_id=g.user.id, note=note))
    audit("pedido_estado", "order", order.id, {"code": order.code, "de": order.status, "a": new_status})
    order.status = new_status
    db.session.commit()
    return jsonify(order.to_dict())
