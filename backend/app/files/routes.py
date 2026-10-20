from flask import Blueprint, g, send_file
from sqlalchemy import select

from ..auth.services import require
from ..common import ApiError
from ..extensions import db
from ..products.models import Product, ProductImage
from .models import StoredFile
from .services import absolute_path

bp = Blueprint("files", __name__)


@bp.get("/api/files/<int:file_id>")
@require("inventory.view")
def private_file(file_id):
    """Fotos de conteo e importaciones: solo usuarios con sesión y permiso."""
    stored = db.session.get(StoredFile, file_id)
    if stored is None:
        raise ApiError("Archivo no encontrado.", 404)
    if stored.purpose == "importacion" and not g.user.has("imports.manage"):
        raise ApiError("No tienes permiso para esta acción.", 403)
    response = send_file(absolute_path(stored), mimetype=stored.mime_type, max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/api/public/images/<int:file_id>")
def public_image(file_id):
    """Solo fotos de productos activos publicados en la tienda (o cualquiera para el personal)."""
    row = db.session.execute(
        select(StoredFile, Product).join(ProductImage, ProductImage.file_id == StoredFile.id)
        .join(Product, Product.id == ProductImage.product_id)
        .where(StoredFile.id == file_id, StoredFile.purpose == "producto")
    ).first()
    if row is None:
        raise ApiError("Imagen no encontrada.", 404)
    stored, product = row
    staff = getattr(g, "user", None) is not None
    if not staff and not (product.is_published and product.status == "activo"):
        raise ApiError("Imagen no encontrada.", 404)
    response = send_file(absolute_path(stored), mimetype="image/jpeg", max_age=3600)
    return response
