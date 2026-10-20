from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, Validator, json_body, query_int
from ..extensions import db
from ..files.services import save_image
from .models import PRODUCT_STATUSES, SIZE_SYSTEMS, Brand, Category, PriceHistory, Product, ProductImage, ProductVariant, Supplier

bp = Blueprint("products", __name__, url_prefix="/api")
MAX_IMAGES_PER_PRODUCT = 8


def _commit(conflict_message):
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError(conflict_message, 409)


def _get_or_404(model, obj_id, label):
    obj = db.session.get(model, obj_id)
    if obj is None:
        raise ApiError(f"{label} no existe.", 404)
    return obj


def _changes(obj, values):
    """Aplica valores y devuelve solo los campos que cambiaron (para la auditoría)."""
    changed = {}
    for key, value in values.items():
        old = getattr(obj, key)
        if old != value:
            changed[key] = {"antes": str(old) if old is not None else None,
                            "despues": str(value) if value is not None else None}
            setattr(obj, key, value)
    return changed


# ---------- Catálogos simples: marcas, categorías ----------

def _simple_catalog(model, label, path, audit_name):
    @bp.get(f"/{path}", endpoint=f"list_{path}")
    @require("products.view")
    def list_items():
        rows = db.session.execute(select(model).order_by(model.name)).scalars().all()
        return jsonify({"items": [r.to_dict() for r in rows]})

    @bp.post(f"/{path}", endpoint=f"create_{path}")
    @require("products.manage")
    def create_item():
        v = Validator(json_body())
        v.text("name", required=True, max_len=100)
        item = model(**v.raise_if_errors())
        db.session.add(item)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            raise ApiError(f"Ya existe {label} con ese nombre.", 409)
        audit(f"{audit_name}_creada", path, item.id, {"name": item.name})
        db.session.commit()
        return jsonify(item.to_dict()), 201

    @bp.patch(f"/{path}/<int:item_id>", endpoint=f"update_{path}")
    @require("products.manage")
    def update_item(item_id):
        item = _get_or_404(model, item_id, label.capitalize())
        v = Validator(json_body())
        v.text("name", required=True, max_len=100)
        changes = _changes(item, v.raise_if_errors())
        audit(f"{audit_name}_modificada", path, item.id, changes)
        _commit(f"Ya existe {label} con ese nombre.")
        return jsonify(item.to_dict())


_simple_catalog(Brand, "una marca", "brands", "marca")
_simple_catalog(Category, "una categoría", "categories", "categoria")


# ---------- Proveedores ----------

def _supplier_fields(data, partial=False):
    v = Validator(data)
    v.text("name", required=not partial, max_len=150)
    v.text("contact_name", max_len=150)
    v.text("phone", max_len=50)
    v.text("email", max_len=150)
    v.text("notes", max_len=2000)
    if "lead_time_days" in data:
        if data["lead_time_days"] in (None, ""):
            v.clean["lead_time_days"] = None
        else:
            v.integer("lead_time_days", minimum=0)
    clean = v.raise_if_errors()
    if partial and "name" in clean and clean["name"] is None:
        raise ApiError("Datos no válidos.", 422, {"name": "Campo obligatorio."})
    return clean


@bp.get("/suppliers")
@require("products.view")
def list_suppliers():
    rows = db.session.execute(select(Supplier).order_by(Supplier.name)).scalars().all()
    return jsonify({"items": [s.to_dict() for s in rows]})


@bp.post("/suppliers")
@require("products.manage")
def create_supplier():
    supplier = Supplier(**_supplier_fields(json_body()))
    db.session.add(supplier)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Ya existe un proveedor con ese nombre.", 409)
    audit("proveedor_creado", "supplier", supplier.id, {"name": supplier.name})
    db.session.commit()
    return jsonify(supplier.to_dict()), 201


@bp.patch("/suppliers/<int:supplier_id>")
@require("products.manage")
def update_supplier(supplier_id):
    supplier = _get_or_404(Supplier, supplier_id, "El proveedor")
    changes = _changes(supplier, _supplier_fields(json_body(), partial=True))
    audit("proveedor_modificado", "supplier", supplier.id, changes)
    _commit("Ya existe un proveedor con ese nombre.")
    return jsonify(supplier.to_dict())


# ---------- Productos ----------

def _product_fields(data, partial=False):
    v = Validator(data)
    v.text("code", required=not partial, max_len=50)
    v.text("model_name", required=not partial, max_len=150)
    v.text("footwear_type", max_len=100)
    v.text("description", max_len=5000)
    v.text("name", max_len=200)
    v.text("subcategory", max_len=100)
    v.text("segment", max_len=60)
    v.text("material", max_len=100)
    v.text("season", max_len=60)
    v.text("collection", max_len=100)
    v.text("supplier_ref", max_len=100)
    if data.get("size_system") not in (None, ""):
        v.choice("size_system", SIZE_SYSTEMS)
    elif "size_system" in data:
        v.clean["size_system"] = None
    v.choice("status", PRODUCT_STATUSES)
    if not partial or "brand_id" in data:
        v.integer("brand_id", required=True, minimum=1)
    for field in ("category_id", "supplier_id"):
        if field in data:
            if data[field] in (None, ""):
                v.clean[field] = None
            else:
                v.integer(field, minimum=1)
    if "is_published" in data:
        if not isinstance(data["is_published"], bool):
            v.errors["is_published"] = "Debe ser verdadero o falso."
        else:
            v.clean["is_published"] = data["is_published"]
    clean = v.raise_if_errors()
    for key in ("code", "model_name"):
        if key in clean and clean[key] is None:
            raise ApiError("Datos no válidos.", 422, {key: "Campo obligatorio."})
    if clean.get("brand_id") is not None:
        _get_or_404(Brand, clean["brand_id"], "La marca")
    if clean.get("category_id") is not None:
        _get_or_404(Category, clean["category_id"], "La categoría")
    if clean.get("supplier_id") is not None:
        _get_or_404(Supplier, clean["supplier_id"], "El proveedor")
    return clean


@bp.get("/products")
@require("products.view")
def list_products():
    limit = query_int("limit", default=25, minimum=1, maximum=200)
    offset = query_int("offset", default=0, minimum=0)
    query = select(Product).join(Brand)
    if q := request.args.get("q"):
        like = f"%{q.strip().lower()}%"
        query = query.where(func.lower(Brand.name).like(like)
                            | func.lower(Product.model_name).like(like)
                            | func.lower(Product.code).like(like))
    if (category_id := query_int("category_id")) is not None:
        query = query.where(Product.category_id == category_id)
    if (brand_id := query_int("brand_id")) is not None:
        query = query.where(Product.brand_id == brand_id)
    if status := request.args.get("status"):
        query = query.where(Product.status == status)
    total = db.session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.session.execute(query.order_by(Brand.name, Product.model_name)
                              .limit(limit).offset(offset)).scalars().all()
    items = []
    for p in rows:
        item = p.to_dict()
        item["variant_count"] = len(p.variants)
        item["stock_pairs"] = sum(v.stock_quantity for v in p.variants)
        items.append(item)
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


@bp.post("/products")
@require("products.manage")
def create_product():
    product = Product(**_product_fields(json_body()))
    db.session.add(product)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Ya existe un producto con ese código.", 409)
    audit("producto_creado", "product", product.id, {"code": product.code})
    db.session.commit()
    return jsonify(product.to_dict(with_variants=True)), 201


@bp.get("/products/<int:product_id>")
@require("products.view")
def get_product(product_id):
    return jsonify(_get_or_404(Product, product_id, "El producto").to_dict(with_variants=True))


@bp.get("/products/<int:product_id>/overview")
@require("products.view")
def product_overview(product_id):
    """Ficha completa: características, matriz talla×color con stock, totales, ventas, movimientos y conteos."""
    from .services import product_card
    product = _get_or_404(Product, product_id, "El producto")
    return jsonify(product_card(product, detail=True))


@bp.patch("/products/<int:product_id>")
@require("products.manage")
def update_product(product_id):
    product = _get_or_404(Product, product_id, "El producto")
    changes = _changes(product, _product_fields(json_body(), partial=True))
    audit("producto_modificado", "product", product.id, changes)
    _commit("Ya existe un producto con ese código.")
    return jsonify(product.to_dict(with_variants=True))


@bp.post("/products/<int:product_id>/images")
@require("products.manage")
def upload_product_image(product_id):
    product = _get_or_404(Product, product_id, "El producto")
    if len(product.images) >= MAX_IMAGES_PER_PRODUCT:
        raise ApiError(f"Máximo {MAX_IMAGES_PER_PRODUCT} fotos por producto.", 422)
    stored = save_image(request.files.get("image"), "producto")
    image = ProductImage(product_id=product.id, file_id=stored.id, position=len(product.images))
    db.session.add(image)
    try:
        from ..vision.services import index_image
        index_image(stored, product.id)  # referencia para la identificación visual
    except Exception as error:  # noqa: BLE001 - la foto se guarda aunque falle el indexado
        from flask import current_app
        current_app.logger.warning("No se pudo indexar la foto %s: %s", stored.id, error)
    audit("foto_producto_subida", "product", product.id, {"file_id": stored.id})
    db.session.commit()
    return jsonify(image.to_dict()), 201


@bp.delete("/products/<int:product_id>/images/<int:image_id>")
@require("products.manage")
def delete_product_image(product_id, image_id):
    image = db.session.get(ProductImage, image_id)
    if image is None or image.product_id != product_id:
        raise ApiError("La foto no existe.", 404)
    db.session.delete(image)  # el archivo se conserva en storage y en stored_files (trazabilidad)
    audit("foto_producto_retirada", "product", product_id, {"file_id": image.file_id})
    db.session.commit()
    return jsonify({"ok": True})


# ---------- Variantes (talla + color) ----------

def _variant_fields(data, partial=False):
    if "stock_quantity" in data:
        raise ApiError("El stock no se edita directamente: registra un movimiento en /api/inventory/movements.", 422)
    v = Validator(data)
    v.text("sku", required=not partial, max_len=60)
    v.text("barcode", max_len=64)
    v.text("size", required=not partial, max_len=20)
    v.text("color", required=not partial, max_len=50)
    v.money("cost")
    v.money("price")
    v.integer("min_stock", minimum=0)
    v.choice("status", PRODUCT_STATUSES)
    clean = v.raise_if_errors()
    for key in ("sku", "size", "color"):
        if key in clean and clean[key] is None:
            raise ApiError("Datos no válidos.", 422, {key: "Campo obligatorio."})
    return clean


def _check_price_permission(fields):
    if ("cost" in fields or "price" in fields) and not g.user.has("prices.manage"):
        raise ApiError("Modificar costos o precios requiere el permiso prices.manage.", 403)


@bp.get("/variants/<int:variant_id>/price-history")
@require("products.view")
def price_history(variant_id):
    _get_or_404(ProductVariant, variant_id, "La variante")
    rows = db.session.execute(select(PriceHistory).where(PriceHistory.variant_id == variant_id)
                              .order_by(PriceHistory.id.desc())).scalars().all()
    return jsonify({"items": [r.to_dict() for r in rows]})


@bp.post("/products/<int:product_id>/variants")
@require("products.manage")
def create_variant(product_id):
    _get_or_404(Product, product_id, "El producto")
    fields = _variant_fields(json_body())
    _check_price_permission(fields)
    variant = ProductVariant(product_id=product_id, stock_quantity=0, **fields)
    db.session.add(variant)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Ya existe una variante con ese SKU, código de barras o talla+color para este producto.", 409)
    if variant.cost is not None or variant.price is not None:
        db.session.add(PriceHistory(variant_id=variant.id, cost=variant.cost, price=variant.price, source="alta",
                                    user_id=g.user.id))
    audit("variante_creada", "variant", variant.id, {"sku": variant.sku})
    db.session.commit()
    return jsonify(variant.to_dict()), 201


@bp.get("/variants/<int:variant_id>")
@require("products.view")
def get_variant(variant_id):
    return jsonify(_get_or_404(ProductVariant, variant_id, "La variante").to_dict())


@bp.get("/variants/lookup")
@require("products.view")
def lookup_variant():
    """Busca una variante por SKU o código de barras exacto (lector de códigos)."""
    code = (request.args.get("code") or "").strip()
    if not code:
        raise ApiError("Indica 'code'.")
    variant = db.session.execute(
        select(ProductVariant).where((ProductVariant.sku == code) | (ProductVariant.barcode == code))
    ).scalar_one_or_none()
    if variant is None:
        raise ApiError("No hay ninguna variante con ese SKU o código de barras.", 404)
    item = variant.to_dict()
    item.update({"brand": variant.product.brand.name, "model_name": variant.product.model_name})
    return jsonify(item)


@bp.patch("/variants/<int:variant_id>")
@require("products.manage")
def update_variant(variant_id):
    variant = _get_or_404(ProductVariant, variant_id, "La variante")
    fields = _variant_fields(json_body(), partial=True)
    _check_price_permission(fields)
    changes = _changes(variant, fields)
    if "cost" in changes or "price" in changes:
        db.session.add(PriceHistory(variant_id=variant.id, cost=variant.cost, price=variant.price, source="edicion",
                                    user_id=g.user.id))
    audit("variante_modificada", "variant", variant.id, changes)
    _commit("Ya existe una variante con ese SKU, código de barras o talla+color para este producto.")
    return jsonify(variant.to_dict())
