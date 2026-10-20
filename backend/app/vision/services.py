"""Registro inteligente: analiza fotos, propone coincidencias del catálogo y registra la decisión humana.

Cada dato propuesto lleva su origen:
  - "detectado": leído directamente (código de barras, texto de etiqueta, conteo del detector)
  - "inferido": deducido con incertidumbre (colores dominantes, datos de un producto parecido)
  - "pendiente": no hay evidencia suficiente → la persona debe completarlo
Nunca se crea ni modifica un producto o el stock sin la confirmación explícita del usuario.
"""
from flask import current_app, g
from PIL import Image
from sqlalchemy import select

import numpy as np

from ..common import utcnow
from ..extensions import db
from ..files.services import absolute_path, save_derived
from ..inventory.settings import get_setting
from ..products.models import Product
from . import features as feat
from .models import IdentificationFeedback, ImageFeature


def _detect(image):
    """Devuelve (detecciones, versión del modelo) o ([], None) si no hay detector."""
    try:
        from ..ai.detector import confidence_for, get_detector
        detector = get_detector()
        if detector is None:
            return [], None
        detections, _ = detector.predict(image, confidence_for(getattr(detector, "meta", {})), current_app.config["AI_IOU"])
        return detections, detector.version
    except Exception as error:  # noqa: BLE001 - sin detector se usa la imagen completa
        current_app.logger.warning("Detector no disponible para el registro inteligente: %s", error)
        return [], None


def _best_box(detections):
    if not detections:
        return None
    best = max(detections, key=lambda d: d["confidence"] * (d["x2"] - d["x1"]) * (d["y2"] - d["y1"]))
    return [best["x1"], best["y1"], best["x2"], best["y2"]]


def index_image(stored, product_id=None):
    """Calcula y guarda las características de una imagen (idempotente por archivo)."""
    existing = db.session.execute(select(ImageFeature).where(ImageFeature.file_id == stored.id)).scalar_one_or_none()
    if existing is not None:
        if product_id and existing.product_id != product_id:
            existing.product_id = product_id
        return existing, None
    with Image.open(absolute_path(stored)) as image:
        image = image.convert("RGB")
        detections, _ = _detect(image)
        box = _best_box(detections)
        values = feat.extract(np.asarray(image), box)
    row = ImageFeature(file_id=stored.id, product_id=product_id, box=box, **feat.serialize(values))
    db.session.add(row)
    db.session.flush()
    return row, values


def candidates(query, limit=5):
    """Productos del catálogo ordenados por similitud (mejor imagen de cada producto)."""
    best = {}
    refs = db.session.execute(select(ImageFeature).where(ImageFeature.product_id.isnot(None),
                                                         ImageFeature.version == feat.FEATURE_VERSION)).scalars().all()
    for ref in refs:
        result = feat.similarity(query, feat.deserialize(ref))
        current = best.get(ref.product_id)
        if current is None or result["score"] > current["score"]:
            best[ref.product_id] = {**result, "file_id": ref.file_id, "ref_colors": ref.colors or []}
    ranked = sorted(best.items(), key=lambda item: -item[1]["score"])[:limit]
    high, low = get_setting("vision_high_score"), get_setting("vision_low_score")
    out = []
    for rank, (product_id, result) in enumerate(ranked, start=1):
        product = db.session.get(Product, product_id)
        if product is None or result["score"] < low:
            continue
        query_colors = {c["name"] for c in query["colors"]}
        ref_colors = {c["name"] for c in result["ref_colors"]}
        out.append({
            "rank": rank, "product_id": product.id, "code": product.code, "brand": product.brand.name,
            "model_name": product.model_name, "category": product.category.name if product.category else None,
            "score": result["score"], "color_similarity": result["color"], "structure_similarity": result["structure"],
            "matched_points": result["matches"],
            "level": "fuerte" if result["score"] >= high else "posible",
            "reference_image": f"/api/public/images/{result['file_id']}",
            "differences": ([f"Colores distintos: foto {', '.join(sorted(query_colors - ref_colors)) or '-'} / "
                             f"catálogo {', '.join(sorted(ref_colors - query_colors)) or '-'}"]
                            if query_colors != ref_colors else []),
        })
    return out


def field(value, source, confidence=None, evidence=None):
    return {"value": value, "source": source if value not in (None, "", []) else "pendiente",
            "confidence": confidence, "evidence": evidence}


def analyze(stored_files):
    """Analiza 1–5 imágenes del mismo producto y devuelve propuestas con su origen y evidencias."""
    from ..ocr.services import identify

    images, all_candidates, barcodes, brands, sizes, colors, codes = [], {}, [], [], [], {}, set()
    model_version, shoes_counts = None, []
    for stored in stored_files:
        with Image.open(absolute_path(stored)) as image:
            image = image.convert("RGB")
            detections, version = _detect(image)
            model_version = model_version or version
            box = _best_box(detections)
            rgb = np.asarray(image)
            query = feat.extract(rgb, box)
            derived = None
            if box is not None:
                derived = save_derived(stored, Image.fromarray(feat.crop(rgb, box)))
            row = ImageFeature(file_id=stored.id, product_id=None, box=box, **feat.serialize(query))
            db.session.add(row)
            try:
                found = identify(image)
            except Exception as error:  # noqa: BLE001
                current_app.logger.warning("Lectura de etiqueta fallida en registro inteligente: %s", error)
                found = {"barcodes": [], "fields": {"brands": [], "sizes": [], "codes": []}, "matches": []}
        shoes_counts.append(len(detections))
        for c in query["colors"]:
            colors[c["name"]] = max(colors.get(c["name"], 0), c["share"])
        barcodes += [b["text"] for b in found["barcodes"]]
        brands += found["fields"]["brands"]
        sizes += found["fields"]["sizes"]
        codes |= {v.product_id for v in found["matches"]}
        for cand in candidates(query):
            prev = all_candidates.get(cand["product_id"])
            if prev is None or cand["score"] > prev["score"]:
                all_candidates[cand["product_id"]] = cand
        images.append({"file_id": stored.id, "url": f"/api/files/{stored.id}", "shoes_detected": len(detections),
                       "box": box, "crop_file_id": derived.id if derived else None,
                       "colors": query["colors"], "detections": detections})
    # Un código de barras/SKU leído que coincide con un producto es la evidencia más fuerte.
    for product_id in codes:
        product = db.session.get(Product, product_id)
        all_candidates[product_id] = {**all_candidates.get(product_id, {}), "product_id": product_id, "code": product.code,
                                      "brand": product.brand.name, "model_name": product.model_name,
                                      "category": product.category.name if product.category else None,
                                      "score": 100.0, "level": "codigo", "differences": [],
                                      "reference_image": all_candidates.get(product_id, {}).get("reference_image")}
    ranked = sorted(all_candidates.values(), key=lambda c: -c["score"])
    top = ranked[0] if ranked else None
    color_list = sorted(colors.items(), key=lambda kv: -kv[1])
    strong = top is not None and top.get("level") in ("fuerte", "codigo")
    proposal = {
        "brand": field(brands[0], "detectado", evidence="texto de la etiqueta") if brands else
        field(top["brand"] if strong else None, "inferido", top["score"] if strong else None, "producto parecido del catálogo"),
        "model_name": field(top["model_name"] if strong else None, "inferido" if top and top.get("level") != "codigo" else "detectado",
                            top["score"] if strong else None, "producto del catálogo"),
        "category": field(top["category"] if strong else None, "inferido", None, "producto del catálogo"),
        "color": field(color_list[0][0] if color_list else None, "inferido", round(color_list[0][1] * 100) if color_list else None,
                       "color dominante del recorte"),
        "secondary_colors": field([c for c, _ in color_list[1:3]], "inferido"),
        "size": field(sizes[0] if sizes else None, "detectado", evidence="texto de la etiqueta"),
        "barcode": field(barcodes[0] if barcodes else None, "detectado", evidence="código de barras/QR"),
        "shoes_detected": field(max(shoes_counts) if shoes_counts else None, "detectado",
                                evidence=f"detector {model_version}" if model_version else "sin detector"),
    }
    decision = ("codigo" if top and top.get("level") == "codigo" else
                "coincidencia_fuerte" if strong and (len(ranked) == 1 or ranked[1]["score"] < top["score"] - 10) else
                "ambigua" if len([c for c in ranked if c["level"] in ("fuerte", "codigo")]) > 1 or
                (strong and len(ranked) > 1) else
                "posible" if ranked else "sin_coincidencias")
    return {
        "images": images, "proposal": proposal, "candidates": ranked, "decision": decision,
        "model_version": model_version,
        "calibration_note": ("Los umbrales de similitud aún no están calibrados con fotos reales de la tienda: "
                             "confirma siempre la coincidencia. Cada decisión se registra para calibrarlos."),
    }


def record_feedback(analysis, chosen_product_id):
    for cand in analysis.result.get("candidates", []):
        db.session.add(IdentificationFeedback(
            analysis_id=analysis.id, product_id=cand["product_id"], rank=cand.get("rank", 0), score=cand["score"],
            outcome="aceptada" if cand["product_id"] == chosen_product_id else "rechazada",
            user_id=g.user.id if getattr(g, "user", None) else None))


def calibration():
    """Precisión real de la propuesta top-1 por umbral, según las decisiones registradas."""
    rows = db.session.execute(select(IdentificationFeedback).where(IdentificationFeedback.rank == 1)).scalars().all()
    total = len(rows)
    table = []
    for threshold in range(10, 100, 10):
        proposed = [r for r in rows if r.score >= threshold]
        correct = sum(1 for r in proposed if r.outcome == "aceptada")
        table.append({"threshold": threshold, "proposals": len(proposed), "correct": correct,
                      "precision": round(correct / len(proposed), 3) if proposed else None,
                      "coverage": round(len(proposed) / total, 3) if total else None})
    return {"decisions": total, "table": table, "sufficient": total >= 30,
            "message": None if total >= 30 else f"Solo hay {total} decisiones registradas: se necesitan al menos 30 "
                                                 "para fijar un umbral con criterio."}


def mark_decided(analysis, status, product_id):
    analysis.status, analysis.product_id = status, product_id
    analysis.decided_by, analysis.decided_at = (g.user.id if getattr(g, "user", None) else None), utcnow()
