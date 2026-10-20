"""Importación en dos pasos: validar (vista previa, sin escribir datos) → confirmar."""
import csv
import io
import json
import re
import unicodedata

from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import func, select

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, json_body, query_int, utcnow
from ..extensions import db
from ..files.models import StoredFile
from ..files.services import absolute_path, save_data_file
from ..inventory.models import InventoryMovement, Location
from ..inventory.services import apply_movement, default_location, find_by_external_ref, lock_variant
from ..products.models import Brand, Category, PriceHistory, Product, ProductVariant, Supplier
from .models import IMPORT_KINDS, ImportBatch, ImportIssue, TradeRecord
from .parsers import TEMPLATES, VALIDATORS, detect_kind, read_table

bp = Blueprint("imports", __name__, url_prefix="/api/imports")


DUPLICATE_POLICIES = ("rechazar", "separados")


def _fold(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _plan_catalog(rows, issues):
    """Compara cada fila válida con la base de datos (sin escribir) y decide la acción.

    crear / actualizar / omitir; las filas que necesitan decisión humana se rechazan con un error
    explicativo («revisar») para que el resto pueda importarse sin dejar datos a medias.
    """
    actions, kept = {}, []
    locations = {loc.code.lower(): loc for loc in db.session.execute(select(Location)).scalars()}
    stock_seen = set()
    for r in rows:
        row = r["_row"]
        problems = []
        product = db.session.execute(
            select(Product).where(func.lower(Product.code) == r["codigo_producto"].lower())).scalar_one_or_none()
        if product is None:
            twin = next((p for p in db.session.execute(select(Product).join(Brand).where(
                func.lower(Brand.name) == r["marca"].lower())).scalars()
                if _fold(p.model_name) == _fold(r["modelo"])), None)
            if twin is not None:
                problems.append(("codigo_producto", f"Ya existe {twin.brand.name} {twin.model_name} con el código "
                                                    f"{twin.code}: usa ese código para no duplicar el producto."))
        variant = db.session.execute(
            select(ProductVariant).where(func.lower(ProductVariant.sku) == r["sku"].lower())).scalar_one_or_none()
        if variant is not None and (product is None or variant.product_id != product.id):
            problems.append(("sku", f"El SKU {r['sku']} ya pertenece a otro producto ({variant.product.code})."))
        if variant is None and product is not None:
            clash = db.session.execute(select(ProductVariant).where(
                ProductVariant.product_id == product.id, func.lower(ProductVariant.size) == r["talla"].lower(),
                func.lower(ProductVariant.color) == r["color"].lower())).scalar_one_or_none()
            if clash is not None:
                problems.append(("talla", f"{product.code} ya tiene talla {r['talla']} color {r['color']} "
                                          f"con el SKU {clash.sku}."))
        location = None
        if r.get("ubicacion"):
            location = locations.get(r["ubicacion"].lower())
            if location is None or not location.is_active:
                problems.append(("ubicacion", f"La ubicación '{r['ubicacion']}' no existe o está inactiva. "
                                              "Créala primero en Inventario › Ubicaciones."))
        if problems:
            for column, message in problems:
                issues.append((row, column, "error", f"Revisar: {message}"))
            actions[row] = "revisar"
            continue
        r["_stock_inicial_ok"] = False
        if r.get("stock_inicial"):
            loc = location or default_location()
            key = (r["sku"].lower(), loc.id)
            moved = variant is not None and db.session.execute(select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.variant_id == variant.id, InventoryMovement.location_id == loc.id)).scalar_one() > 0
            if key in stock_seen or moved:
                issues.append((row, "stock_inicial", "advertencia",
                               "El stock inicial de esta variante en esta ubicación ya está registrado: no se duplica. "
                               "Para cambiarlo usa un conteo físico o un ajuste."))
            else:
                r["_stock_inicial_ok"] = True
                stock_seen.add(key)
        if variant is None:
            actions[row] = "crear"
        else:
            changed = any(value is not None and getattr(variant, attr) != value for attr, value in (
                ("barcode", r["codigo_barras"]), ("cost", r["costo"]), ("price", r["precio"]),
                ("min_stock", r["stock_minimo"])))
            actions[row] = "actualizar" if changed or r["_stock_inicial_ok"] or r.get("cantidad_entrada") else "omitir"
        kept.append(r)
    counts = {a: sum(1 for v in actions.values() if v == a) for a in ("crear", "actualizar", "omitir", "revisar")}
    return kept, actions, counts


def _validate(batch, path, sheet=None, policy="rechazar", mapping=None):
    try:
        frame, sheet_name, sheets = read_table(path, sheet)
    except ValueError as error:
        raise ApiError(str(error), 422)
    except Exception as error:  # noqa: BLE001 - pandas lanza tipos variados ante archivos dañados
        raise ApiError(f"No se pudo leer el archivo: {error}", 422)
    rows, issues, info = VALIDATORS[batch.kind](frame, duplicate_policy=policy, mapping_override=mapping).run()
    info["sheets"] = sheets
    info["fields"] = [{"name": name, "required": required} for name, (required, _) in VALIDATORS[batch.kind].columns.items()]
    if batch.kind == "catalogo" and rows:
        rows, actions, counts = _plan_catalog(rows, issues)
        info["actions"] = counts
        info["row_actions"] = {str(k): v for k, v in actions.items()}
        info["preview"] = [{**{k: (str(v) if v is not None and not isinstance(v, (str, int, bool)) else v)
                               for k, v in r.items() if not k.startswith("_") or k == "_row"},
                            "_action": actions.get(r["_row"])} for r in rows[:20]]
        info["without_photo"] = len({r["codigo_producto"].lower() for r in rows})
    if info["missing_columns"]:
        # ¿Encaja con el otro tipo de importación? Ayuda cuando se eligió el tipo equivocado.
        other = detect_kind(frame)
        if other and other != batch.kind:
            info["suggested_kind"] = other
            label = {"catalogo": "Catálogo de la tienda", "comercio": "Comercio exterior de calzado"}[other]
            issues.insert(0, (1, None, "error", f"Las columnas de este archivo corresponden a «{label}». "
                                                "Vuelve a subirlo eligiendo ese tipo de datos."))
    return rows, issues, info, sheet_name


def _get_batch(batch_id):
    batch = db.session.get(ImportBatch, batch_id)
    if batch is None:
        raise ApiError("La importación no existe.", 404)
    return batch


@bp.get("/templates/<kind>.csv")
@require("imports.manage")
def template(kind):
    if kind not in TEMPLATES:
        raise ApiError("Tipo de importación no válido.", 404)
    buffer = io.StringIO()
    csv.writer(buffer).writerow(TEMPLATES[kind])
    return Response("﻿" + buffer.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=plantilla_{kind}.csv"})


@bp.post("")
@require("imports.manage")
def upload():
    kind = request.form.get("kind") or "auto"
    if kind not in (*IMPORT_KINDS, "auto"):
        raise ApiError("Datos no válidos.", 422, {"kind": "Elige 'auto', 'catalogo' o 'comercio'."})
    policy = request.form.get("duplicate_policy") or "rechazar"
    if policy not in DUPLICATE_POLICIES:
        raise ApiError("Datos no válidos.", 422, {"duplicate_policy": "Elige 'rechazar' o 'separados'."})
    mapping = _parse_mapping(request.form.get("mapping"))
    stored = save_data_file(request.files.get("file"))
    detected = None
    if kind == "auto":
        try:
            frame, _, _ = read_table(absolute_path(stored), request.form.get("sheet"))
        except Exception as error:  # noqa: BLE001
            raise ApiError(f"No se pudo leer el archivo: {error}", 422)
        detected = detect_kind(frame)
        if detected is None:
            raise ApiError("No se reconoce el tipo de archivo: sus columnas no coinciden con el catálogo ni con "
                           "comercio exterior. Descarga una plantilla para ver las columnas esperadas.", 422)
        kind = detected
    batch = ImportBatch(kind=kind, file_id=stored.id, user_id=g.user.id, status="validado")
    db.session.add(batch)
    db.session.flush()

    previous = db.session.execute(
        select(ImportBatch.id).join(StoredFile, StoredFile.id == ImportBatch.file_id)
        .where(StoredFile.sha256 == stored.sha256, ImportBatch.kind == kind,
               ImportBatch.status == "confirmado", ImportBatch.id != batch.id)
    ).scalar()
    rows, issues, info, sheet_name = _validate(batch, absolute_path(stored), request.form.get("sheet"), policy, mapping)
    batch.sheet_name = sheet_name
    _store_validation(batch, rows, issues, info, previous=previous, policy=policy, detected=detected, mapping=mapping)
    audit("importacion_validada", "import", batch.id, {
        "tipo": kind, "archivo": stored.original_name, "filas": batch.total_rows, "validas": batch.valid_rows})
    db.session.commit()
    return jsonify(batch.to_dict(with_issues=True)), 201


def _store_validation(batch, rows, issues, info, previous=None, policy="rechazar", detected=None, mapping=None):
    if previous:
        issues.insert(0, (None, None, "error", f"Este mismo archivo ya se importó y confirmó en el lote #{previous}."))
        rows = []
    batch.total_rows = info["total_rows"]
    batch.valid_rows = len(rows)
    batch.rejected = len({i[0] for i in issues if i[2] == "error" and i[0] and i[0] > 1})
    batch.columns = info["mapping"]
    batch.summary = {**info, "duplicate_policy": policy, "kind_detected": detected is not None,
                     "manual_mapping": mapping or {},
                     "errors": sum(1 for i in issues if i[2] == "error"),
                     "warnings": sum(1 for i in issues if i[2] == "advertencia"),
                     "blocking": bool(previous) or bool(info["missing_columns"])}
    batch.issues.clear()
    db.session.flush()
    for row, column, severity, message in issues:
        batch.issues.append(ImportIssue(row_number=row, column=column, severity=severity, message=message))


def _parse_mapping(raw):
    if raw in (None, ""):
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ApiError("Datos no válidos.", 422, {"mapping": "JSON no válido."})
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ApiError("Datos no válidos.", 422, {"mapping": "Debe ser {campo: columna_del_archivo}."})
    return {k: v for k, v in raw.items() if v}


@bp.post("/<int:batch_id>/mapping")
@require("imports.manage")
def remap(batch_id):
    """Asistente: la persona asigna columnas del archivo a campos del sistema y se vuelve a validar."""
    batch = _get_batch(batch_id)
    if batch.status != "validado":
        raise ApiError("Solo se puede reasignar columnas en una importación pendiente.", 409)
    mapping = _parse_mapping(json_body().get("mapping"))
    policy = (batch.summary or {}).get("duplicate_policy", "rechazar")
    rows, issues, info, _ = _validate(batch, absolute_path(batch.file), batch.sheet_name, policy, mapping)
    _store_validation(batch, rows, issues, info, policy=policy, mapping=mapping,
                      detected=True if (batch.summary or {}).get("kind_detected") else None)
    audit("importacion_columnas", "import", batch.id, {"asignacion": mapping})
    db.session.commit()
    return jsonify(batch.to_dict(with_issues=True))


@bp.get("/<int:batch_id>/issues.csv")
@require("imports.manage")
def issues_csv(batch_id):
    """Informe de errores y advertencias para corregir el archivo original."""
    batch = _get_batch(batch_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["fila", "columna", "severidad", "mensaje", "accion"])
    actions = (batch.summary or {}).get("row_actions", {})
    for issue in batch.issues:
        writer.writerow([issue.row_number or "", issue.column or "", issue.severity, issue.message,
                         actions.get(str(issue.row_number), "")])
    return Response("\ufeff" + buffer.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=incidencias_importacion_{batch.id}.csv"})


@bp.get("")
@require("imports.manage")
def list_batches():
    limit = query_int("limit", default=20, minimum=1, maximum=100)
    offset = query_int("offset", default=0, minimum=0)
    query = select(ImportBatch)
    if kind := request.args.get("kind"):
        query = query.where(ImportBatch.kind == kind)
    total = db.session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.session.execute(query.order_by(ImportBatch.id.desc()).limit(limit).offset(offset)).scalars().all()
    return jsonify({"items": [b.to_dict() for b in rows], "total": total, "limit": limit, "offset": offset})


@bp.get("/<int:batch_id>")
@require("imports.manage")
def get_batch(batch_id):
    return jsonify(_get_batch(batch_id).to_dict(with_issues=True))


@bp.post("/<int:batch_id>/discard")
@require("imports.manage")
def discard(batch_id):
    batch = _get_batch(batch_id)
    if batch.status != "validado":
        raise ApiError("Solo se puede descartar una importación pendiente de confirmar.", 409)
    batch.status = "descartado"
    audit("importacion_descartada", "import", batch.id)
    db.session.commit()
    return jsonify(batch.to_dict())


@bp.post("/<int:batch_id>/confirm")
@require("imports.manage")
def confirm(batch_id):
    batch = db.session.execute(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if batch is None:
        raise ApiError("La importación no existe.", 404)
    if batch.status != "validado":
        raise ApiError("Esta importación ya fue confirmada o descartada.", 409)
    if (batch.summary or {}).get("blocking") or batch.valid_rows == 0:
        raise ApiError("No hay filas válidas para importar. Corrige el archivo y vuelve a subirlo.", 422)
    json_body()  # exige cuerpo JSON (y por tanto CSRF) explícito
    rows, issues, _, _ = _validate(batch, absolute_path(batch.file), batch.sheet_name,
                                   (batch.summary or {}).get("duplicate_policy", "rechazar"),
                                   (batch.summary or {}).get("manual_mapping") or None)
    if len(rows) != batch.valid_rows:
        raise ApiError("El archivo cambió desde la validación. Súbelo de nuevo.", 409)
    counters = _apply_catalog(batch, rows) if batch.kind == "catalogo" else _apply_trade(batch, rows)
    batch.added, batch.updated, batch.skipped = counters
    batch.status = "confirmado"
    batch.confirmed_at = utcnow()
    audit("importacion_confirmada", "import", batch.id, {
        "tipo": batch.kind, "añadidos": batch.added, "actualizados": batch.updated,
        "omitidos": batch.skipped, "rechazados": batch.rejected})
    db.session.commit()
    return jsonify(batch.to_dict(with_issues=True))


def _get_or_create(model, name):
    if not name:
        return None
    item = db.session.execute(select(model).where(func.lower(model.name) == name.lower())).scalar_one_or_none()
    if item is None:
        item = model(name=name)
        db.session.add(item)
        db.session.flush()
    return item


PRODUCT_TEXT_FIELDS = {"nombre": "name", "subcategoria": "subcategory", "segmento": "segment", "material": "material",
                       "temporada": "season", "coleccion": "collection", "sistema_tallas": "size_system",
                       "ref_proveedor": "supplier_ref", "tipo_calzado": "footwear_type", "descripcion": "description"}


def _apply_catalog(batch, rows):
    """Escribe las filas ya planificadas. Todo o nada: cualquier fallo revierte el lote completo."""
    added = updated = skipped = 0
    locations = {loc.code.lower(): loc for loc in db.session.execute(select(Location)).scalars()}
    for r in rows:
        brand = _get_or_create(Brand, r["marca"])
        category = _get_or_create(Category, r["categoria"])
        supplier = _get_or_create(Supplier, r.get("proveedor"))
        product = db.session.execute(
            select(Product).where(func.lower(Product.code) == r["codigo_producto"].lower())).scalar_one_or_none()
        if product is None:
            product = Product(code=r["codigo_producto"], brand=brand, model_name=r["modelo"], category=category,
                              status="activo")
            db.session.add(product)
        for column, attr in PRODUCT_TEXT_FIELDS.items():
            if r.get(column) and getattr(product, attr) is None:  # completa vacíos; no pisa lo editado a mano
                setattr(product, attr, r[column])
        if supplier is not None and product.supplier_id is None:
            product.supplier = supplier
        if product.category_id is None and category is not None:
            product.category = category
        db.session.flush()
        variant = db.session.execute(
            select(ProductVariant).where(func.lower(ProductVariant.sku) == r["sku"].lower())).scalar_one_or_none()
        if variant is not None and variant.product_id != product.id:
            raise ApiError(f"Fila {r['_row']}: el SKU {r['sku']} ya pertenece a otro producto "
                           f"({variant.product.code}). No se importó nada.", 409)
        fields = {"size": r["talla"], "color": r["color"]}
        if r["codigo_barras"]:
            fields["barcode"] = r["codigo_barras"]
        for key in ("costo", "precio", "stock_minimo"):
            if r[key] is not None:
                fields[{"costo": "cost", "precio": "price", "stock_minimo": "min_stock"}[key]] = r[key]
        if variant is None:
            variant = ProductVariant(product_id=product.id, sku=r["sku"], stock_quantity=0, status="activo",
                                     **{"min_stock": 0, **fields})
            db.session.add(variant)
            db.session.flush()
            if variant.cost is not None or variant.price is not None:
                db.session.add(PriceHistory(variant_id=variant.id, cost=variant.cost, price=variant.price,
                                            source=f"importacion:{batch.id}", user_id=g.user.id))
            added += 1
        else:
            changed = False
            price_changed = False
            for key, value in fields.items():
                if getattr(variant, key) != value:
                    setattr(variant, key, value)
                    changed = True
                    price_changed = price_changed or key in ("cost", "price")
            if price_changed:
                db.session.add(PriceHistory(variant_id=variant.id, cost=variant.cost, price=variant.price,
                                            source=f"importacion:{batch.id}", user_id=g.user.id))
            if changed:
                updated += 1
            elif not r["cantidad_entrada"] and not r.get("_stock_inicial_ok"):
                skipped += 1
        location = locations.get((r.get("ubicacion") or "").lower()) or default_location()
        if r.get("_stock_inicial_ok"):
            ref = f"stock-inicial:{variant.id}:{location.id}"
            if find_by_external_ref("importacion", ref) is None:
                apply_movement(lock_variant(variant.id), "stock_inicial", r["stock_inicial"], unit_cost=r["costo"],
                               location=location, channel="importacion", external_ref=ref,
                               reason=f"Stock inicial por importación (fila {r['_row']})", reference=f"IMPORT-{batch.id}")
        if r["cantidad_entrada"]:
            apply_movement(lock_variant(variant.id), "entrada_compra", r["cantidad_entrada"], unit_cost=r["costo"],
                           location=location, channel="importacion", external_ref=f"IMPORT-{batch.id}:{r['_row']}",
                           reason=f"Entrada por importación (fila {r['_row']})", reference=f"IMPORT-{batch.id}")
    return added, updated, skipped


TRADE_FIELDS = ("category", "is_aggregate", "value_thousand_usd", "quantity_pairs", "value_usd",
                "value_usd_per_pair_source", "value_usd_per_pair", "quality_flags")


def _apply_trade(batch, rows):
    added = updated = skipped = 0
    for r in rows:
        existing = db.session.execute(select(TradeRecord).where(
            TradeRecord.reporter == r["reporter"], TradeRecord.flow == r["flow"], TradeRecord.year == r["year"],
            TradeRecord.hs6_code == r["hs6_code"], TradeRecord.partner == r["partner"],
            TradeRecord.occurrence == r["occurrence"])).scalar_one_or_none()
        if existing is None:
            db.session.add(TradeRecord(source_batch_id=batch.id, reporter=r["reporter"], flow=r["flow"],
                                       year=r["year"], hs6_code=r["hs6_code"], partner=r["partner"],
                                       occurrence=r["occurrence"],
                                       **{k: r[k] for k in TRADE_FIELDS}))
            added += 1
            continue
        changed = False
        for key in TRADE_FIELDS:
            old, new = getattr(existing, key), r[key]
            same = (old == new) if key in ("category", "is_aggregate", "quality_flags") else (
                (old is None and new is None) or (old is not None and new is not None and float(old) == float(new)))
            if not same:
                setattr(existing, key, new)
                changed = True
        if changed:
            existing.source_batch_id = batch.id
            updated += 1
        else:
            skipped += 1
    return added, updated, skipped
