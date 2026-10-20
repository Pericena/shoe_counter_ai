"""Lectura de etiquetas: códigos de barras/QR (zxing-cpp) y texto (RapidOCR sobre ONNX Runtime, sin conexión).

Solo PROPONE campos: el usuario los revisa antes de guardar nada. La marca se reconoce únicamente si
aparece escrita (caja, etiqueta, lengüeta) y coincide con una marca registrada: no hay reconocimiento
de logotipos.
"""
import re
import threading
import time
import unicodedata

import numpy as np

_lock = threading.Lock()
_engine = None

COLORS = ["negro", "blanco", "azul", "rojo", "verde", "amarillo", "gris", "marron", "marrón", "cafe", "café",
          "beige", "rosa", "rosado", "morado", "violeta", "naranja", "celeste", "plateado", "dorado", "crema",
          "camel", "vino", "turquesa", "black", "white", "blue", "red", "green", "grey", "gray", "brown", "pink"]
# Talla tras una palabra clave. Dos pasadas:
#  1) admite confusiones típicas del OCR (O->0, I/l->1, S->5, B->8) solo si el número NO va pegado a letras;
#  2) si va pegado (el OCR une palabras: "TALLA40NEGRO"), solo dígitos reales.
# Ante ambigüedad ("TALLA4ONEGRO") no se propone nada: mejor vacío que una talla equivocada.
_KEYS_EU = r"\b(?:talla|tal\.?|t\.|size|eur|eu|br|bra)\s*[:#]?\s*"
_KEYS_US = r"\b(?:us|uk|cm)\s*[:#]?\s*"
SIZE_PATTERNS = [
    (re.compile(_KEYS_EU + r"([0-9OoIlSB]{2}(?:[.,][05])?)(?![0-9A-Za-z])", re.I), True),
    (re.compile(_KEYS_US + r"([0-9OoIlSB]{1,2}(?:[.,][05])?)(?![0-9A-Za-z])", re.I), True),
    (re.compile(_KEYS_EU + r"(\d{2}(?:[.,][05])?)(?![0-9])", re.I), False),
]
_OCR_DIGITS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})
PRICE_PATTERN = re.compile(r"(?:precio|pvp|bs\.?|bob|usd|\$)\s*[:]?\s*(\d{1,6}(?:[.,]\d{2})?)", re.I)


def _fold(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def ocr_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        return _engine


def read_barcodes(rgb):
    import zxingcpp
    results = []
    for item in zxingcpp.read_barcodes(rgb):
        if item.valid and item.text:
            results.append({"text": item.text, "format": str(item.format).split(".")[-1]})
    seen, unique = set(), []
    for r in results:
        if r["text"] not in seen:
            seen.add(r["text"])
            unique.append(r)
    return unique


def read_text(rgb):
    result, _ = ocr_engine()(rgb)
    lines = []
    for box, text, score in result or []:
        if text and float(score) >= 0.5:
            lines.append({"text": text.strip(), "confidence": round(float(score), 3)})
    return lines


def extract_fields(lines, barcodes, brand_names, known_codes):
    """Campos candidatos a partir del texto. Cada candidato indica de dónde sale (trazable)."""
    full = " ".join(line["text"] for line in lines)
    folded = _fold(full)
    fields = {"brands": [], "sizes": [], "prices": [], "colors": [], "codes": []}
    for brand in brand_names:
        if len(brand) >= 2 and re.search(rf"\b{re.escape(_fold(brand))}\b", folded):
            fields["brands"].append(brand)
    for pattern, tolerant in SIZE_PATTERNS:
        for match in pattern.finditer(full):
            raw = match.group(1)
            if not any(ch.isdigit() for ch in raw):
                continue
            value = (raw.translate(_OCR_DIGITS) if tolerant else raw).replace(",", ".")
            if not 1 <= float(value) <= 60:
                continue
            if value not in fields["sizes"]:
                fields["sizes"].append(value)
    for match in PRICE_PATTERN.finditer(full):
        value = match.group(1).replace(",", ".")
        if value not in fields["prices"]:
            fields["prices"].append(value)
    for color in COLORS:
        if re.search(rf"\b{re.escape(_fold(color))}\b", folded):
            name = color.capitalize()
            if name not in fields["colors"]:
                fields["colors"].append(name)
    tokens = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9\-_.]{2,59}", full.replace(" ", " ")))
    compact = full.replace(" ", "")
    for code in known_codes:
        if code in tokens or (len(code) >= 6 and code.replace(" ", "") in compact):
            fields["codes"].append(code)
    for barcode in barcodes:
        if barcode["text"] not in fields["codes"]:
            fields["codes"].append(barcode["text"])
    return fields


def identify(pil_image, use_text=True):
    """Lee códigos (y opcionalmente texto) y busca variantes REGISTRADAS que coincidan.

    Devuelve las variantes exactas (por código de barras, SKU o código de producto) y, si no hay,
    sugerencias por marca + talla leídas en el texto. No crea ni modifica nada.
    """
    from sqlalchemy import func, or_, select

    from ..extensions import db
    from ..products.models import Brand, Product, ProductVariant

    brands = db.session.execute(select(Brand.name)).scalars().all()
    codes = [c for row in db.session.execute(select(ProductVariant.sku, ProductVariant.barcode)).all() for c in row if c]
    codes += db.session.execute(select(Product.code)).scalars().all()
    rgb = np.ascontiguousarray(np.asarray(pil_image.convert("RGB")))
    started = time.perf_counter()
    barcodes = read_barcodes(rgb)
    lines = read_text(rgb) if use_text else []
    fields = extract_fields(lines, barcodes, brands, codes)
    elapsed = int((time.perf_counter() - started) * 1000)

    exact = []
    if fields["codes"]:
        exact = db.session.execute(select(ProductVariant).join(Product).where(or_(
            ProductVariant.sku.in_(fields["codes"]), ProductVariant.barcode.in_(fields["codes"]),
            Product.code.in_(fields["codes"])))).scalars().all()
    suggested = []
    if not exact and fields["brands"]:
        query = select(ProductVariant).join(Product).join(Brand).where(
            func.lower(Brand.name).in_([b.lower() for b in fields["brands"]]))
        if fields["sizes"]:
            query = query.where(ProductVariant.size.in_(fields["sizes"]))
        suggested = db.session.execute(query.limit(20)).scalars().all()
    method = "codigo" if exact and barcodes else ("etiqueta" if exact else ("sugerencia" if suggested else None))
    return {"barcodes": barcodes, "lines": lines, "fields": fields, "elapsed_ms": elapsed,
            "matches": exact, "suggestions": suggested, "method": method}


def cards_for(variants):
    """Una ficha por producto, resaltando las variantes reconocidas."""
    from ..products.services import product_card
    by_product = {}
    for v in variants:
        by_product.setdefault(v.product_id, (v.product, set()))[1].add(v.id)
    return [product_card(product, highlight_variant_ids=tuple(ids)) for product, ids in by_product.values()]
