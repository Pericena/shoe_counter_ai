"""Lector de etiquetas y códigos: propone datos; nunca crea ni modifica nada por sí solo."""
from flask import Blueprint, current_app, jsonify, request
from PIL import Image

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError
from ..extensions import db
from ..files.services import absolute_path, save_image
from . import services

bp = Blueprint("ocr", __name__, url_prefix="/api/ocr")


def _variant_item(v):
    item = v.to_dict()
    item.update({"brand": v.product.brand.name, "model_name": v.product.model_name, "product_code": v.product.code})
    return item


@bp.post("/analyze")
@require("inventory.view")
def analyze():
    stored = save_image(request.files.get("image"), "etiqueta")
    try:
        with Image.open(absolute_path(stored)) as image:
            result = services.identify(image)
    except Exception as error:  # noqa: BLE001 - el OCR no debe tumbar la petición
        current_app.logger.exception("Fallo del lector de etiquetas: %s", error)
        raise ApiError("No se pudo analizar la imagen con el lector de etiquetas.", 500)
    fields = result["fields"]
    audit("etiqueta_leida", "file", stored.id, {
        "codigos": fields["codes"][:10], "marcas": fields["brands"], "tallas": fields["sizes"],
        "coincidencias": [v.sku for v in result["matches"]][:10], "metodo": result["method"]})
    db.session.commit()
    return jsonify({
        "file_id": stored.id,
        "image_url": f"/api/files/{stored.id}",
        "barcodes": result["barcodes"], "lines": result["lines"], "fields": fields,
        "elapsed_ms": result["elapsed_ms"], "method": result["method"],
        "matches": [_variant_item(v) for v in result["matches"]],
        "suggestions": [_variant_item(v) for v in result["suggestions"]],
        # Ficha completa de cada producto reconocido (marca, modelo, características, stock por talla y color).
        "cards": services.cards_for(result["matches"] or result["suggestions"]),
        "note": ("Datos propuestos por lectura automática: revísalos antes de usarlos. La marca solo se reconoce "
                 "si aparece escrita y está registrada en Marcas."),
    })
