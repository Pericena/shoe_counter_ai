"""Conteo inteligente: subir foto → detectar → revisar → confirmar → (opcional) conciliar con stock."""
import io

from flask import Blueprint, current_app, g, jsonify, request, send_file
from PIL import Image, ImageDraw
from sqlalchemy import func, select

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, json_body, parse_date_range, query_int, utcnow
from ..extensions import db
from ..files.services import absolute_path, save_image
from ..inventory.services import lock_variant, register_movement
from .detector import ModelUnavailable, confidence_for, get_detector, model_status
from ..products.models import ProductVariant
from .models import AICount, AIDetection

bp = Blueprint("ai", __name__, url_prefix="/api/ai")
MAX_MANUAL_BOXES = 500
MAX_FRAME_BYTES = 3 * 1024 * 1024


def _payload(count, message=None):
    """Conteo + ficha del producto identificado + comparación foto ↔ stock del sistema."""
    from ..products.services import product_card
    body = count.to_dict()
    variant = count.identified_variant
    if variant is not None:
        shoes = sum(1 for d in count.detections if d.accepted)
        body["identified"] = product_card(variant.product, highlight_variant_ids=(variant.id,))
        body["comparison"] = {
            "variant_id": variant.id, "sku": variant.sku, "size": variant.size, "color": variant.color,
            "system_pairs": variant.stock_quantity,
            "photo_shoes": shoes,
            "photo_pairs_confirmed": count.pairs_complete,
            "photo_loose_confirmed": count.loose_shoes,
            "note": ("La foto puede mostrar solo una parte del stock (un estante, una caja). La diferencia es "
                     "orientativa hasta que confirmes el alcance del conteo."),
        }
    breakdown = detection_breakdown(count)
    if any(row["variant_id"] is not None for row in breakdown):
        for row in breakdown:
            v = db.session.get(ProductVariant, row["variant_id"]) if row["variant_id"] else None
            row.update({"sku": v.sku, "product": f"{v.product.brand.name} {v.product.model_name}",
                        "size": v.size, "color": v.color, "system_pairs": v.stock_quantity} if v else {"sku": None})
        body["by_variant"] = breakdown
    if message:
        body["message"] = message
    return body


def _identify_on_create(count, stored):
    """Identifica el producto: variante indicada por el cliente (cámara en vivo) o código/etiqueta en la foto."""
    hint = request.form.get("variant_id")
    if hint:
        try:
            variant = db.session.get(ProductVariant, int(hint))
        except ValueError:
            variant = None
        if variant is None:
            raise ApiError("Datos no válidos.", 422, {"variant_id": "La variante indicada no existe."})
        count.identified_variant_id = variant.id
        count.identification = {"method": "seleccion_en_vivo", "candidates": [variant.sku]}
        return
    try:
        from ..ocr.services import identify
        with Image.open(absolute_path(stored)) as image:
            # Solo el código de barras aquí. El OCR de texto carga otro modelo y dejaba
            # la petición en «Procesando» sin mostrar la foto ni las cajas.
            found = identify(image, use_text=False)
    except Exception as error:  # noqa: BLE001 - la identificación es opcional
        current_app.logger.warning("No se pudo identificar el producto en el conteo: %s", error)
        return
    candidates = found["matches"] or found["suggestions"]
    count.identification = {
        "method": found["method"], "codes": found["fields"]["codes"][:10], "brands": found["fields"]["brands"],
        "sizes": found["fields"]["sizes"], "candidates": [v.sku for v in candidates][:10]}
    if len(found["matches"]) == 1:
        count.identified_variant_id = found["matches"][0].id


def _get_count(count_id):
    count = db.session.get(AICount, count_id)
    if count is None:
        raise ApiError("El conteo no existe.", 404)
    return count


@bp.get("/status")
@require("inventory.view")
def status():
    info, _ = model_status()
    info.pop("path", None)
    return jsonify(info)


@bp.post("/detect")
@require("counts.create")
def detect_frame():
    """Vista previa en vivo: detecta en un fotograma de la cámara SIN guardarlo ni crear un conteo.

    Para registrar, el cliente envía la foto a POST /api/ai/counts (queda guardada y pendiente de revisión).
    """
    file = request.files.get("frame")
    if file is None:
        raise ApiError("Falta el fotograma.", 422)
    raw = file.read(MAX_FRAME_BYTES + 1)
    if not raw or len(raw) > MAX_FRAME_BYTES:
        raise ApiError("Fotograma vacío o demasiado grande (máx. 3 MB).", 413)
    try:
        image = Image.open(io.BytesIO(raw))
        if image.format not in ("JPEG", "PNG", "WEBP"):
            raise ApiError("El fotograma debe ser JPEG, PNG o WEBP.", 415)
        image.load()
    except ApiError:
        raise
    except Exception:  # noqa: BLE001
        raise ApiError("El fotograma no es una imagen válida.", 415)
    try:
        detector = get_detector()
    except ModelUnavailable:
        detector = None
    if detector is None:
        return jsonify({"model_installed": False, "detections": [], "count": None,
                        "message": "No hay modelo de detección instalado: usa «Registrar foto» y cuenta a mano."})
    conf = confidence_for(getattr(detector, "meta", {}))
    detections, elapsed = detector.predict(image, conf, current_app.config["AI_IOU"])
    return jsonify({"model_installed": True, "model_version": detector.version, "confidence_threshold": conf,
                    "detections": detections, "count": len(detections), "inference_ms": elapsed})


@bp.post("/counts")
@require("counts.create")
def create_count():
    stored = save_image(request.files.get("image"), "conteo")
    notes = (request.form.get("notes") or "").strip()[:2000] or None
    count = AICount(file_id=stored.id, user_id=g.user.id, status="revision", notes=notes)

    try:
        detector = get_detector()
    except ModelUnavailable as error:
        current_app.logger.error(str(error))
        detector = None
    message = None
    detections = None
    if detector is not None:
        conf = confidence_for(getattr(detector, "meta", {}))
        try:
            with Image.open(absolute_path(stored)) as image:
                detections, elapsed = detector.predict(image, conf, current_app.config["AI_IOU"])
        except Exception as error:  # noqa: BLE001 - un fallo del modelo no debe impedir el conteo manual
            current_app.logger.exception("Fallo de inferencia con %s: %s", detector.version, error)
            message = ("El modelo de detección falló al procesar esta foto. Cuenta manualmente "
                       "marcando cada zapato; el error quedó registrado.")
    if detections is not None:
        count.model_version = detector.version
        count.confidence_threshold = conf
        count.inference_ms = elapsed
        count.detected_count = len(detections)
        for det in detections:
            count.detections.append(AIDetection(source="modelo", accepted=True, **det))
    else:
        message = message or ("No hay un modelo de detección instalado: el conteo se hará de forma manual "
                              "marcando cada zapato sobre la foto.")
    _identify_on_create(count, stored)
    db.session.add(count)
    db.session.flush()
    audit("conteo_creado", "ai_count", count.id, {
        "modelo": count.model_version, "detectados": count.detected_count, "file_id": stored.id,
        "producto_identificado": count.identified_variant.sku if count.identified_variant else None})
    db.session.commit()
    return jsonify(_payload(count, message)), 201


@bp.get("/counts")
@require("inventory.view")
def list_counts():
    limit = query_int("limit", default=25, minimum=1, maximum=200)
    offset = query_int("offset", default=0, minimum=0)
    query = select(AICount)
    if state := request.args.get("status"):
        query = query.where(AICount.status == state)
    start, end = parse_date_range()
    if start:
        query = query.where(AICount.created_at >= start)
    if end:
        query = query.where(AICount.created_at < end)
    total = db.session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.session.execute(query.order_by(AICount.id.desc()).limit(limit).offset(offset)).scalars().all()
    return jsonify({"items": [c.to_dict(with_detections=False) for c in rows], "total": total,
                    "limit": limit, "offset": offset})


@bp.get("/counts/<int:count_id>")
@require("inventory.view")
def get_count(count_id):
    return jsonify(_payload(_get_count(count_id)))


@bp.put("/counts/<int:count_id>/identify")
@require("counts.create")
def identify_count(count_id):
    """Asigna o corrige a mano el producto (variante) que aparece en la foto."""
    count = _get_count(count_id)
    if count.status in ("aplicado", "descartado"):
        raise ApiError("Este conteo ya está cerrado.", 409)
    variant_id = json_body().get("variant_id")
    if variant_id is not None and (isinstance(variant_id, bool) or not isinstance(variant_id, int)):
        raise ApiError("Datos no válidos.", 422, {"variant_id": "Debe ser un id de variante o null."})
    if variant_id is not None and db.session.get(ProductVariant, variant_id) is None:
        raise ApiError("La variante no existe.", 404)
    count.identified_variant_id = variant_id
    count.identification = {**(count.identification or {}), "method": "manual" if variant_id else None}
    audit("conteo_identificado", "ai_count", count.id, {"variant_id": variant_id})
    db.session.commit()
    return jsonify(_payload(count))


def _box(data, index):
    try:
        x1, y1, x2, y2 = (float(data[k]) for k in ("x1", "y1", "x2", "y2"))
    except (KeyError, TypeError, ValueError):
        raise ApiError("Datos no válidos.", 422, {f"detections[{index}]": "Coordenadas x1, y1, x2, y2 numéricas."})
    x1, x2 = sorted((min(max(x1, 0.0), 1.0), min(max(x2, 0.0), 1.0)))
    y1, y2 = sorted((min(max(y1, 0.0), 1.0), min(max(y2, 0.0), 1.0)))
    if x2 - x1 < 0.003 or y2 - y1 < 0.003:
        raise ApiError("Datos no válidos.", 422, {f"detections[{index}]": "La caja es demasiado pequeña."})
    return x1, y1, x2, y2


@bp.put("/counts/<int:count_id>/review")
@require("counts.create")
def review_count(count_id):
    """Guarda la revisión: acepta/rechaza cajas del modelo y reemplaza las cajas manuales."""
    count = _get_count(count_id)
    if count.status != "revision":
        raise ApiError("Este conteo ya no está en revisión.", 409)
    data = json_body()
    items = data.get("detections")
    if not isinstance(items, list):
        raise ApiError("Datos no válidos.", 422, {"detections": "Debe ser una lista."})
    model_boxes = {d.id: d for d in count.detections if d.source == "modelo"}
    manual = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ApiError("Datos no válidos.", 422, {f"detections[{index}]": "Debe ser un objeto."})
        variant_id = _detection_variant(item, index)
        if item.get("source") == "modelo":
            det = model_boxes.get(item.get("id"))
            if det is None:
                raise ApiError("Datos no válidos.", 422, {f"detections[{index}]": "Detección desconocida."})
            det.accepted = bool(item.get("accepted", True))
            det.variant_id = variant_id if det.accepted else None
        else:
            if item.get("accepted", True) is False:
                continue
            manual.append((_box(item, index), variant_id))
    if len(manual) > MAX_MANUAL_BOXES:
        raise ApiError(f"Máximo {MAX_MANUAL_BOXES} cajas manuales.", 422)
    for det in [d for d in count.detections if d.source == "manual"]:
        count.detections.remove(det)
    for (x1, y1, x2, y2), variant_id in manual:
        count.detections.append(AIDetection(x1=x1, y1=y1, x2=x2, y2=y2, confidence=None,
                                            source="manual", accepted=True, variant_id=variant_id))
    if "notes" in data:
        count.notes = (str(data["notes"]).strip()[:2000]) or None
    db.session.flush()
    audit("conteo_revisado", "ai_count", count.id, {
        "aceptadas": sum(1 for d in count.detections if d.accepted),
        "manuales": len(manual),
        "rechazadas": sum(1 for d in count.detections if d.source == "modelo" and not d.accepted)})
    db.session.commit()
    return jsonify(_payload(count))


def _nonneg_int(data, field):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApiError("Datos no válidos.", 422, {field: "Debe ser un entero mayor o igual a 0."})
    return value


def _detection_variant(item, index):
    """Producto asociado a una caja concreta (opcional). Solo lo asigna la persona en la revisión."""
    value = item.get("variant_id")
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or db.session.get(ProductVariant, value) is None:
        raise ApiError("Datos no válidos.", 422, {f"detections[{index}].variant_id": "Variante inexistente."})
    return value


def detection_breakdown(count):
    """Cajas aceptadas agrupadas por variante asociada (None = sin asociar)."""
    groups = {}
    for det in count.detections:
        if det.accepted:
            groups[det.variant_id] = groups.get(det.variant_id, 0) + 1
    return [{"variant_id": vid, "shoes": n} for vid, n in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))]


@bp.post("/counts/<int:count_id>/confirm")
@require("counts.confirm")
def confirm_count(count_id):
    """Confirma zapatos individuales y su desglose en pares completos y zapatos sueltos."""
    count = _get_count(count_id)
    if count.status != "revision":
        raise ApiError("Este conteo ya no está en revisión.", 409)
    data = json_body()
    pairs, loose = _nonneg_int(data, "pairs_complete"), _nonneg_int(data, "loose_shoes")
    accepted = sum(1 for d in count.detections if d.accepted)
    if pairs * 2 + loose != accepted:
        raise ApiError(
            f"El desglose no cuadra: {pairs} pares × 2 + {loose} sueltos = {pairs * 2 + loose}, "
            f"pero hay {accepted} zapatos marcados. Revisa las cajas o el desglose.", 422)
    count.confirmed_shoes = accepted
    count.pairs_complete = pairs
    count.loose_shoes = loose
    count.status = "confirmado"
    count.confirmed_by = g.user.id
    count.confirmed_at = utcnow()
    if data.get("notes"):
        count.notes = str(data["notes"]).strip()[:2000]
    audit("conteo_confirmado", "ai_count", count.id, {
        "detectados_modelo": count.detected_count, "zapatos_confirmados": accepted,
        "pares": pairs, "sueltos": loose})
    db.session.commit()
    return jsonify(_payload(count))


@bp.post("/counts/<int:count_id>/apply")
@require("counts.confirm", "inventory.move")
def apply_count(count_id):
    """Concilia un conteo confirmado con el stock de una variante (genera un movimiento conteo_fisico)."""
    count = _get_count(count_id)
    if count.status != "confirmado":
        raise ApiError("Solo se puede conciliar un conteo confirmado que no se haya aplicado.", 409)
    data = json_body()
    variant_id = data.get("variant_id", count.identified_variant_id)
    if isinstance(variant_id, bool) or not isinstance(variant_id, int):
        raise ApiError("Datos no válidos.", 422, {"variant_id": "Selecciona la variante contada."})
    counted_pairs = _nonneg_int(data, "counted_pairs")
    reason = str(data.get("reason") or "").strip()[:500]
    if not reason:
        raise ApiError("Datos no válidos.", 422, {"reason": "Indica el motivo o alcance del conteo."})
    variant = lock_variant(variant_id)
    stock_before = variant.stock_quantity
    full_reason = (f"{reason} — Conteo inteligente #{count.id}: {count.confirmed_shoes} zapatos "
                   f"({count.pairs_complete} pares, {count.loose_shoes} sueltos)")
    movement = register_movement(variant_id=variant.id, movement_type="conteo_fisico",
                                 counted_quantity=counted_pairs, reason=full_reason,
                                 reference=f"CONTEO-{count.id}", count_id=count.id, commit=False)
    count.status = "aplicado"
    count.variant_id = variant.id
    count.applied_pairs = counted_pairs
    count.stock_before = stock_before
    count.applied_by = g.user.id
    count.applied_at = utcnow()
    audit("conteo_aplicado", "ai_count", count.id, {
        "variant_id": variant.id, "sku": variant.sku, "stock_antes": stock_before,
        "pares_contados": counted_pairs, "diferencia": counted_pairs - stock_before,
        "movement_id": movement.id if movement else None})
    db.session.commit()
    return jsonify({"count": _payload(count), "movement": movement.to_dict() if movement else None})


@bp.post("/counts/<int:count_id>/discard")
@require("counts.create")
def discard_count(count_id):
    count = _get_count(count_id)
    if count.status not in ("revision", "confirmado"):
        raise ApiError("Este conteo no se puede descartar.", 409)
    reason = str(json_body().get("reason") or "").strip()[:500]
    if not reason:
        raise ApiError("Datos no válidos.", 422, {"reason": "Indica por qué se descarta."})
    count.status = "descartado"
    count.notes = ((count.notes + "\n") if count.notes else "") + f"Descartado: {reason}"
    audit("conteo_descartado", "ai_count", count.id, {"motivo": reason})
    db.session.commit()
    return jsonify(_payload(count))


@bp.get("/counts/<int:count_id>/annotated.jpg")
@require("inventory.view")
def annotated_image(count_id):
    """Imagen con las cajas dibujadas (verde: aceptada del modelo, azul: manual, rojo: rechazada)."""
    count = _get_count(count_id)
    with Image.open(absolute_path(count.file)) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    line = max(2, round(min(width, height) / 300))
    for index, det in enumerate(count.detections, start=1):
        color = (220, 38, 38) if not det.accepted else ((37, 99, 235) if det.source == "manual" else (22, 163, 74))
        box = (det.x1 * width, det.y1 * height, det.x2 * width, det.y2 * height)
        draw.rectangle(box, outline=color, width=line)
        text = f"{index}" + (f" {det.confidence:.2f}" if det.confidence is not None else " manual")
        draw.text((box[0] + line + 2, box[1] + line), text, fill=color)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=88)
    buffer.seek(0)
    response = send_file(buffer, mimetype="image/jpeg", download_name=f"conteo-{count.id}.jpg")
    response.headers["Cache-Control"] = "private, no-store"
    return response
