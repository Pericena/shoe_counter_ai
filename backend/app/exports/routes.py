"""Exportación CSV/XLSX con los filtros de la petición. Nunca genera archivos vacíos."""
import csv
import io
from datetime import datetime, timezone

import pandas as pd
from flask import Blueprint, Response, g, jsonify, request
from sqlalchemy import select

from ..ai.models import AICount
from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, parse_date_range, query_int
from ..extensions import db
from ..imports.models import DataExport, ImportIssue
from ..products.models import Brand, Product
from ..shop.models import Order

bp = Blueprint("exports", __name__, url_prefix="/api/exports")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe(value):
    """Evita la inyección de fórmulas al abrir el archivo en Excel."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _products():
    query = select(Product).join(Brand).order_by(Brand.name, Product.model_name)
    if (category_id := query_int("category_id")) is not None:
        query = query.where(Product.category_id == category_id)
    rows = []
    for p in db.session.execute(query).scalars():
        rows.append({"codigo": p.code, "marca": p.brand.name, "modelo": p.model_name,
                     "categoria": p.category.name if p.category else None, "tipo": p.footwear_type,
                     "proveedor": p.supplier.name if p.supplier else None, "estado": p.status,
                     "publicado": p.is_published, "variantes": len(p.variants),
                     "pares": sum(v.stock_quantity for v in p.variants)})
    return rows


def _stock():
    from ..inventory.routes import stock_item, stock_query
    keys = ("product_code", "brand", "model_name", "category", "sku", "barcode", "size", "color", "cost", "price",
            "stock_quantity", "min_stock", "stock_state", "inventory_value")
    return [{k: stock_item(v)[k] for k in keys} for v in db.session.execute(stock_query()).scalars()]


def _movements():
    from ..inventory.routes import movements_query
    keys = ("created_at", "sku", "product", "size", "color", "movement_type", "quantity", "balance_after",
            "unit_cost", "reason", "reference", "user")
    return [{k: m.to_dict()[k] for k in keys} for m in db.session.execute(movements_query()).scalars()]


def _counts():
    query = select(AICount).order_by(AICount.id)
    start, end = parse_date_range()
    if start:
        query = query.where(AICount.created_at >= start)
    if end:
        query = query.where(AICount.created_at < end)
    keys = ("id", "created_at", "user", "status", "model_version", "detected_count", "accepted_count",
            "manual_added", "rejected_count", "confirmed_shoes", "pairs_complete", "loose_shoes", "variant_sku",
            "stock_before", "applied_pairs", "difference", "confirmed_by", "applied_by", "notes")
    return [{k: c.to_dict(with_detections=False)[k] for k in keys} for c in db.session.execute(query).scalars()]


def _orders():
    query = select(Order).order_by(Order.id)
    if state := request.args.get("status"):
        query = query.where(Order.status == state)
    start, end = parse_date_range()
    if start:
        query = query.where(Order.created_at >= start)
    if end:
        query = query.where(Order.created_at < end)
    rows = []
    for o in db.session.execute(query).scalars():
        for item in o.items:
            rows.append({"pedido": o.code, "fecha": o.to_dict()["created_at"], "estado": o.status,
                         "cliente": o.customer_name, "correo": o.customer_email, "sku": item.sku,
                         "descripcion": item.description, "talla": item.size, "color": item.color,
                         "cantidad": item.quantity, "precio_unitario": str(item.unit_price),
                         "total_linea": str(item.line_total), "total_pedido": str(o.total_amount)})
    return rows


def _trade():
    from ..reports.queries import trade_query
    rows = []
    for r in db.session.execute(trade_query()).scalars():
        d = r.to_dict()
        rows.append({"País_reportante": d["reporter"], "Flujo_comercial": d["flow"], "Año": d["year"],
                     "Código_SA6": d["hs6_code"], "Categoría_calzado": d["category"],
                     "Socio_comercial": d["partner"], "Es_agregado": d["is_aggregate"],
                     "Valor_miles_USD": d["value_thousand_usd"], "Cantidad_pares": d["quantity_pairs"],
                     "Valor_USD": d["value_usd"], "Valor_USD_por_par_archivo": d["value_usd_per_pair_source"],
                     "Valor_USD_por_par_recalculado": d["value_usd_per_pair"],
                     "Banderas_calidad": ", ".join(d["quality_flags"])})
    return rows


def _trade_summary():
    from ..reports.queries import trade_summary
    summary = trade_summary(top=50)
    return [{"Año": r["year"], "Flujo": r["flow"], "Valor_USD": r["value_usd"], "Cantidad_pares": r["quantity_pairs"],
             "Filas": r["rows"]} for r in summary["by_year_flow"]]


def _trade_quality():
    batch_id = query_int("batch_id")
    query = select(ImportIssue).order_by(ImportIssue.batch_id, ImportIssue.row_number)
    if batch_id is not None:
        query = query.where(ImportIssue.batch_id == batch_id)
    return [{"lote": i.batch_id, "fila": i.row_number, "columna": i.column, "severidad": i.severity,
             "mensaje": i.message} for i in db.session.execute(query).scalars()]


DATASETS = {
    "productos": (_products, "products.view"),
    "existencias": (_stock, "inventory.view"),
    "movimientos": (_movements, "inventory.view"),
    "conteos": (_counts, "inventory.view"),
    "pedidos": (_orders, "orders.view"),
    "comercio": (_trade, "reports.view"),
    "comercio_resumen": (_trade_summary, "reports.view"),
    "calidad_importaciones": (_trade_quality, "imports.manage"),
}


@bp.get("/<dataset>")
@require("exports.run")
def export(dataset):
    if dataset not in DATASETS:
        raise ApiError("Conjunto de datos no disponible.", 404, {"disponibles": sorted(DATASETS)})
    builder, permission = DATASETS[dataset]
    if not g.user.has(permission):
        raise ApiError("No tienes permiso para esta acción.", 403, {"required": [permission]})
    file_format = request.args.get("format", "csv")
    if file_format not in ("csv", "xlsx"):
        raise ApiError("'format' debe ser csv o xlsx.")
    rows = builder()
    if not rows:
        raise ApiError("No hay datos para exportar con los filtros indicados.", 404)
    filters = {k: v for k, v in request.args.items() if k != "format"}
    stamp = datetime.now(timezone.utc)
    filename = f"{dataset}_{stamp:%Y%m%d_%H%M%S}.{file_format}"
    frame = pd.DataFrame(rows).map(_safe)

    if file_format == "csv":
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False, quoting=csv.QUOTE_MINIMAL)
        content, mimetype = ("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv; charset=utf-8"
    else:
        buffer = io.BytesIO()
        meta = pd.DataFrame([
            {"campo": "Conjunto", "valor": dataset},
            {"campo": "Generado (UTC)", "valor": f"{stamp:%Y-%m-%d %H:%M:%S}"},
            {"campo": "Usuario", "valor": g.user.username},
            {"campo": "Filas", "valor": len(rows)},
            {"campo": "Filtros", "valor": ", ".join(f"{k}={v}" for k, v in filters.items()) or "sin filtros"},
            {"campo": "Origen", "valor": "Base de datos de Shoe Counter AI"},
        ]).map(_safe)
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Datos", index=False)
            meta.to_excel(writer, sheet_name="Metadatos", index=False)
        content = buffer.getvalue()
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    db.session.add(DataExport(user_id=g.user.id, dataset=dataset, file_format=file_format, filters=filters,
                              row_count=len(rows)))
    audit("exportacion", "export", dataset, {"formato": file_format, "filtros": filters, "filas": len(rows)})
    db.session.commit()
    return Response(content, mimetype=mimetype, headers={"Content-Disposition": f"attachment; filename={filename}"})


@bp.get("")
@require("exports.run")
def history():
    rows = db.session.execute(select(DataExport).order_by(DataExport.id.desc()).limit(50)).scalars().all()
    return jsonify({"items": [r.to_dict() for r in rows], "datasets": sorted(DATASETS)})
