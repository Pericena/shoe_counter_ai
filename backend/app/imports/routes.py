"""Importación en dos pasos: validar (vista previa, sin escribir datos) → confirmar."""
import csv
import io

from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import func, select

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, json_body, query_int, utcnow
from ..extensions import db
from ..files.models import StoredFile
from ..files.services import absolute_path, save_data_file
from ..inventory.services import apply_movement, lock_variant
from ..products.models import Brand, Category, Product, ProductVariant
from .models import IMPORT_KINDS, ImportBatch, ImportIssue, TradeRecord
from .parsers import TEMPLATES, VALIDATORS, read_table

bp = Blueprint("imports", __name__, url_prefix="/api/imports")


def _validate(batch, path, sheet=None):
    try:
        frame, sheet_name, sheets = read_table(path, sheet)
    except ValueError as error:
        raise ApiError(str(error), 422)
    except Exception as error:  # noqa: BLE001 - pandas lanza tipos variados ante archivos dañados
        raise ApiError(f"No se pudo leer el archivo: {error}", 422)
    rows, issues, info = VALIDATORS[batch.kind](frame).run()
    info["sheets"] = sheets
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
    kind = request.form.get("kind")
    if kind not in IMPORT_KINDS:
        raise ApiError("Datos no válidos.", 422, {"kind": "Elige 'catalogo' o 'comercio'."})
    stored = save_data_file(request.files.get("file"))
    batch = ImportBatch(kind=kind, file_id=stored.id, user_id=g.user.id, status="validado")
    db.session.add(batch)
    db.session.flush()

    previous = db.session.execute(
        select(ImportBatch.id).join(StoredFile, StoredFile.id == ImportBatch.file_id)
        .where(StoredFile.sha256 == stored.sha256, ImportBatch.kind == kind,
               ImportBatch.status == "confirmado", ImportBatch.id != batch.id)
    ).scalar()
    rows, issues, info, sheet_name = _validate(batch, absolute_path(stored), request.form.get("sheet"))
    if previous:
        issues.insert(0, (None, None, "error",
                          f"Este mismo archivo ya se importó y confirmó en el lote #{previous}."))
        rows = []
    batch.sheet_name = sheet_name
    batch.total_rows = info["total_rows"]
    batch.valid_rows = len(rows)
    batch.rejected = len({i[0] for i in issues if i[2] == "error" and i[0] and i[0] > 1})
    batch.columns = info["mapping"]
    batch.summary = {**info, "errors": sum(1 for i in issues if i[2] == "error"),
                     "warnings": sum(1 for i in issues if i[2] == "advertencia"),
                     "blocking": bool(previous) or bool(info["missing_columns"])}
    for row, column, severity, message in issues:
        batch.issues.append(ImportIssue(row_number=row, column=column, severity=severity, message=message))
    audit("importacion_validada", "import", batch.id, {
        "tipo": kind, "archivo": stored.original_name, "filas": batch.total_rows, "validas": batch.valid_rows})
    db.session.commit()
    return jsonify(batch.to_dict(with_issues=True)), 201


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
    rows, issues, _, _ = _validate(batch, absolute_path(batch.file), batch.sheet_name)
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


def _apply_catalog(batch, rows):
    added = updated = skipped = 0
    for r in rows:
        brand = _get_or_create(Brand, r["marca"])
        category = _get_or_create(Category, r["categoria"])
        product = db.session.execute(
            select(Product).where(func.lower(Product.code) == r["codigo_producto"].lower())).scalar_one_or_none()
        if product is None:
            product = Product(code=r["codigo_producto"], brand=brand, model_name=r["modelo"], category=category,
                              footwear_type=r["tipo_calzado"], description=r["descripcion"], status="activo")
            db.session.add(product)
            db.session.flush()
        variant = db.session.execute(
            select(ProductVariant).where(func.lower(ProductVariant.sku) == r["sku"].lower())).scalar_one_or_none()
        if variant is not None and variant.product_id != product.id:
            raise ApiError(f"Fila {r['_row']}: el SKU {r['sku']} ya pertenece a otro producto "
                           f"({variant.product.code}). No se importó nada.", 409)
        fields = {"barcode": r["codigo_barras"], "size": r["talla"], "color": r["color"]}
        for key in ("costo", "precio", "stock_minimo"):
            if r[key] is not None:
                fields[{"costo": "cost", "precio": "price", "stock_minimo": "min_stock"}[key]] = r[key]
        if variant is None:
            clash = db.session.execute(select(ProductVariant).where(
                ProductVariant.product_id == product.id, func.lower(ProductVariant.size) == r["talla"].lower(),
                func.lower(ProductVariant.color) == r["color"].lower())).scalar_one_or_none()
            if clash is not None:
                raise ApiError(f"Fila {r['_row']}: el producto {product.code} ya tiene la talla {r['talla']} "
                               f"color {r['color']} con el SKU {clash.sku}. No se importó nada.", 409)
            variant = ProductVariant(product_id=product.id, sku=r["sku"], stock_quantity=0, status="activo",
                                     **{"min_stock": 0, **fields})
            db.session.add(variant)
            db.session.flush()
            added += 1
        else:
            changed = False
            for key, value in fields.items():
                if getattr(variant, key) != value:
                    setattr(variant, key, value)
                    changed = True
            if changed:
                updated += 1
            elif not r["cantidad_entrada"]:
                skipped += 1
        if r["cantidad_entrada"]:
            locked = lock_variant(variant.id)
            apply_movement(locked, "entrada_compra", r["cantidad_entrada"], unit_cost=r["costo"],
                           reason=f"Entrada por importación (fila {r['_row']})", reference=f"IMPORT-{batch.id}")
    return added, updated, skipped


TRADE_FIELDS = ("category", "is_aggregate", "value_thousand_usd", "quantity_pairs", "value_usd",
                "value_usd_per_pair_source", "value_usd_per_pair", "quality_flags")


def _apply_trade(batch, rows):
    added = updated = skipped = 0
    for r in rows:
        existing = db.session.execute(select(TradeRecord).where(
            TradeRecord.reporter == r["reporter"], TradeRecord.flow == r["flow"], TradeRecord.year == r["year"],
            TradeRecord.hs6_code == r["hs6_code"], TradeRecord.partner == r["partner"])).scalar_one_or_none()
        if existing is None:
            db.session.add(TradeRecord(source_batch_id=batch.id, reporter=r["reporter"], flow=r["flow"],
                                       year=r["year"], hs6_code=r["hs6_code"], partner=r["partner"],
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
