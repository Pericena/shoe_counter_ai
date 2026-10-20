import click
from flask import Blueprint, jsonify, request
from flask.cli import AppGroup
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, json_body, query_int
from ..extensions import db
from ..files.models import StoredFile
from ..files.services import save_image
from ..products.models import Brand, Product, ProductImage, ProductVariant, PriceHistory
from . import services
from .models import ImageFeature, VisionAnalysis

bp = Blueprint("vision", __name__, url_prefix="/api/vision")
vision_cli = AppGroup("vision", help="Identificación visual del catálogo.")
MAX_IMAGES = 5


def _analysis(analysis_id):
    analysis = db.session.get(VisionAnalysis, analysis_id)
    if analysis is None:
        raise ApiError("El análisis no existe.", 404)
    if analysis.status != "analizado":
        raise ApiError("Este análisis ya fue resuelto.", 409)
    return analysis


@bp.post("/analyze")
@require("counts.create", "products.view")
def analyze():
    files = request.files.getlist("images")
    if not files:
        raise ApiError("Selecciona al menos una imagen.", 422)
    if len(files) > MAX_IMAGES:
        raise ApiError(f"Máximo {MAX_IMAGES} imágenes por análisis.", 422)
    stored = [save_image(f, "registro") for f in files]
    result = services.analyze(stored)
    analysis = VisionAnalysis(user_id=None, file_ids=[s.id for s in stored], result=result)
    from flask import g
    analysis.user_id = g.user.id
    db.session.add(analysis)
    db.session.flush()
    audit("registro_inteligente_analizado", "vision", analysis.id, {
        "imagenes": len(stored), "decision": result["decision"],
        "candidatos": [(c["code"], c["score"]) for c in result["candidates"][:3]]})
    db.session.commit()
    return jsonify({"id": analysis.id, **result}), 201


def _attach_images(analysis, product):
    current = len(product.images)
    attached = 0
    for file_id in analysis.file_ids:
        stored = db.session.get(StoredFile, file_id)
        if stored is None or current + attached >= 8:
            continue
        if db.session.execute(select(ProductImage).where(ProductImage.file_id == file_id)).first():
            continue
        db.session.add(ProductImage(product_id=product.id, file_id=file_id, position=current + attached))
        services.index_image(stored, product.id)  # pasa a ser imagen de referencia del producto
        attached += 1
    return attached


@bp.post("/analyses/<int:analysis_id>/link")
@require("products.manage")
def link(analysis_id):
    analysis = _analysis(analysis_id)
    product_id = json_body().get("product_id")
    product = db.session.get(Product, product_id) if isinstance(product_id, int) else None
    if product is None:
        raise ApiError("Datos no válidos.", 422, {"product_id": "Producto no válido."})
    attached = _attach_images(analysis, product)
    services.record_feedback(analysis, product.id)
    services.mark_decided(analysis, "vinculado", product.id)
    audit("registro_inteligente_vinculado", "product", product.id, {"analisis": analysis.id, "fotos": attached})
    db.session.commit()
    return jsonify({"product_id": product.id, "images_attached": attached, "analysis": analysis.to_dict()})


@bp.post("/analyses/<int:analysis_id>/create")
@require("products.manage")
def create(analysis_id):
    """Crea un producto nuevo con los datos CONFIRMADOS por la persona, protegido contra duplicados."""
    from ..products.routes import _product_fields, _variant_fields
    from flask import g

    analysis = _analysis(analysis_id)
    data = json_body()
    product_data = dict(data.get("product") or {})
    brand_name = str(product_data.pop("brand_name", "") or "").strip()
    if brand_name and not product_data.get("brand_id"):
        brand = db.session.execute(select(Brand).where(func.lower(Brand.name) == brand_name.lower())).scalar_one_or_none()
        if brand is None:
            brand = Brand(name=brand_name[:100])
            db.session.add(brand)
            db.session.flush()
        product_data["brand_id"] = brand.id
    product_data.setdefault("status", "pendiente_revision")
    clean = _product_fields(product_data)
    strong = [c for c in analysis.result.get("candidates", []) if c.get("level") in ("fuerte", "codigo")]
    same_model = db.session.execute(select(Product).where(
        Product.brand_id == clean["brand_id"], func.lower(Product.model_name) == clean["model_name"].lower())).scalars().all()
    if (strong or same_model) and not data.get("confirm_new"):
        raise ApiError("Ya existe un producto que podría ser este. Revisa las coincidencias o confirma que es nuevo.", 409, {
            "candidates": [{"product_id": c["product_id"], "code": c["code"], "score": c["score"]} for c in strong],
            "same_brand_model": [{"product_id": p.id, "code": p.code} for p in same_model],
            "confirm_new": "Envía confirm_new=true y el motivo si realmente es un producto distinto."})
    product = Product(**clean)
    db.session.add(product)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Ya existe un producto con ese código.", 409)
    variant = None
    if data.get("variant"):
        variant = ProductVariant(product_id=product.id, stock_quantity=0, **_variant_fields(data["variant"]))
        db.session.add(variant)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            raise ApiError("Ya existe una variante con ese SKU o código de barras.", 409)
        db.session.add(PriceHistory(variant_id=variant.id, cost=variant.cost, price=variant.price, source="alta",
                                    user_id=g.user.id))
    attached = _attach_images(analysis, product)
    services.record_feedback(analysis, None)
    services.mark_decided(analysis, "creado", product.id)
    audit("registro_inteligente_creado", "product", product.id, {
        "analisis": analysis.id, "fotos": attached, "confirmado_como_nuevo": bool(data.get("confirm_new")),
        "motivo": str(data.get("reason") or "")[:300]})
    db.session.commit()
    return jsonify({"product": product.to_dict(with_variants=True), "images_attached": attached}), 201


@bp.post("/analyses/<int:analysis_id>/discard")
@require("counts.create")
def discard(analysis_id):
    analysis = _analysis(analysis_id)
    services.mark_decided(analysis, "descartado", None)
    audit("registro_inteligente_descartado", "vision", analysis.id)
    db.session.commit()
    return jsonify(analysis.to_dict())


@bp.get("/analyses")
@require("products.view")
def list_analyses():
    limit = query_int("limit", default=20, minimum=1, maximum=100)
    rows = db.session.execute(select(VisionAnalysis).order_by(VisionAnalysis.id.desc()).limit(limit)).scalars().all()
    return jsonify({"items": [{**a.to_dict(), "result": {"decision": a.result.get("decision"),
                                                          "top": (a.result.get("candidates") or [None])[0]}} for a in rows]})


@bp.get("/calibration")
@require("reports.view")
def calibration():
    indexed = db.session.execute(select(func.count()).select_from(ImageFeature).where(ImageFeature.product_id.isnot(None))).scalar_one()
    return jsonify({**services.calibration(), "reference_images": indexed})


@vision_cli.command("index")
def index_cli():
    """Calcula las características de todas las fotos de producto que aún no las tienen."""
    done = 0
    for image in db.session.execute(select(ProductImage)).scalars():
        exists = db.session.execute(select(ImageFeature).where(ImageFeature.file_id == image.file_id)).scalar_one_or_none()
        if exists is None or exists.product_id != image.product_id:
            services.index_image(image.file, image.product_id)
            done += 1
    db.session.commit()
    click.echo(f"Imágenes indexadas: {done}")
