"""Cálculo de indicadores. Todo sale de la base de datos; nada se estima ni se rellena.

Fórmulas (documentadas también en docs/06-bi-reportes.md):
  - Valor de inventario      = Σ costo_variante × pares_en_stock   (solo variantes con costo)
  - Entradas / salidas       = Σ |cantidad| de movimientos positivos / negativos en el período
  - Unidades vendidas        = Σ |cantidad| de 'salida_venta' + 'salida_pedido'
                               − devoluciones de cliente del período
  - Stock medio del período  = (stock al inicio + stock al final) / 2, reconstruido del libro mayor
  - Rotación                 = unidades vendidas / stock medio   (no se calcula si el stock medio es 0)
  - Error de conteo IA       = |detectados por el modelo − zapatos confirmados por la persona|
  - Valor por par (comercio) = Σ Valor_USD / Σ Cantidad_pares, solo filas con ambos > 0 y sin agregados
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import request
from sqlalchemy import func, select

from ..ai.models import AICount
from ..common import ApiError, iso, parse_date_range, utcnow
from ..extensions import db
from ..imports.models import ImportBatch, TradeRecord
from ..inventory.models import InventoryMovement
from ..products.models import Brand, Product, ProductVariant
from ..shop.models import Order

SALE_TYPES = ("salida_venta", "salida_pedido")


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def period(default_days=30):
    start, end = parse_date_range()
    end = end or (utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    start = start or end - timedelta(days=default_days)
    return start, end


def inventory_summary():
    variants = db.session.execute(select(ProductVariant)).scalars().all()
    value = Decimal("0")
    missing_cost = 0
    for v in variants:
        if v.cost is None:
            missing_cost += 1 if v.stock_quantity else 0
        else:
            value += v.cost * v.stock_quantity
    return {
        "products": db.session.execute(select(func.count()).select_from(Product)).scalar_one(),
        "variants": len(variants),
        "pairs": sum(v.stock_quantity for v in variants),
        "inventory_value_at_cost": str(value.quantize(Decimal("0.01"))),
        "variants_with_stock_without_cost": missing_cost,
        "low": sum(1 for v in variants if 0 < v.stock_quantity <= v.min_stock),
        "out": sum(1 for v in variants if v.stock_quantity == 0),
    }


def movement_filters(query):
    from ..common import query_int
    if (category_id := query_int("category_id")) is not None:
        query = query.where(Product.category_id == category_id)
    if (product_id := query_int("product_id")) is not None:
        query = query.where(ProductVariant.product_id == product_id)
    if (brand_id := query_int("brand_id")) is not None:
        query = query.where(Product.brand_id == brand_id)
    return query


def movements_in(start, end):
    query = (select(InventoryMovement).join(ProductVariant).join(Product)
             .where(InventoryMovement.created_at >= start, InventoryMovement.created_at < end))
    return db.session.execute(movement_filters(query)).scalars().all()


def _bucket(moment, group):
    moment = _aware(moment)
    if group == "month":
        return f"{moment:%Y-%m}"
    if group == "week":
        monday = (moment - timedelta(days=moment.weekday())).date()
        return monday.isoformat()
    return moment.date().isoformat()


def movement_series(group):
    if group not in ("day", "week", "month"):
        raise ApiError("'group' debe ser day, week o month.")
    start, end = period()
    series = defaultdict(lambda: {"entradas": 0, "salidas": 0, "ventas": 0, "ajustes": 0})
    by_type = defaultdict(int)
    for m in movements_in(start, end):
        key = _bucket(m.created_at, group)
        if m.quantity > 0:
            series[key]["entradas"] += m.quantity
        else:
            series[key]["salidas"] += -m.quantity
        if m.movement_type in SALE_TYPES:
            series[key]["ventas"] += -m.quantity
        if m.movement_type in ("ajuste", "conteo_fisico"):
            series[key]["ajustes"] += m.quantity
        by_type[m.movement_type] += m.quantity
    return {
        "from": iso(start), "to": iso(end), "group": group,
        "series": [{"period": k, **v} for k, v in sorted(series.items())],
        "totals_by_type": dict(by_type),
    }


def rotation(limit=10):
    start, end = period(default_days=90)
    moves = movements_in(start, end)
    sold = defaultdict(int)
    returned = defaultdict(int)
    for m in moves:
        if m.movement_type in SALE_TYPES:
            sold[m.variant_id] += -m.quantity
        elif m.movement_type == "devolucion_cliente":
            returned[m.variant_id] += m.quantity
    if not sold:
        return {"from": iso(start), "to": iso(end), "items": [], "has_data": False,
                "message": "No hay ventas registradas en el período; no se calcula la rotación."}
    ids = list(sold)
    from ..inventory.services import ledger_balance_before
    at_start = ledger_balance_before(ids, start)
    at_end = ledger_balance_before(ids, end)
    variants = {v.id: v for v in db.session.execute(select(ProductVariant).where(ProductVariant.id.in_(ids))).scalars()}
    items = []
    for vid in ids:
        v = variants[vid]
        net = sold[vid] - returned[vid]
        avg = (at_start.get(vid, 0) + at_end.get(vid, 0)) / 2
        items.append({
            "variant_id": vid, "sku": v.sku, "product": f"{v.product.brand.name} {v.product.model_name}",
            "size": v.size, "color": v.color, "units_sold": sold[vid], "returns": returned[vid],
            "net_units": net, "stock_start": at_start.get(vid, 0), "stock_end": at_end.get(vid, 0),
            "average_stock": avg, "rotation": round(net / avg, 2) if avg > 0 else None,
        })
    items.sort(key=lambda i: -i["net_units"])
    return {"from": iso(start), "to": iso(end), "items": items[:limit], "has_data": True}


def adjustments():
    start, end = period(default_days=90)
    rows = [m for m in movements_in(start, end) if m.movement_type in ("ajuste", "conteo_fisico")]
    rows.sort(key=lambda m: _aware(m.created_at), reverse=True)
    return {
        "from": iso(start), "to": iso(end),
        "total_positive": sum(m.quantity for m in rows if m.quantity > 0),
        "total_negative": sum(-m.quantity for m in rows if m.quantity < 0),
        "physical_counts_with_difference": sum(1 for m in rows if m.movement_type == "conteo_fisico"),
        "items": [m.to_dict() for m in rows[:200]],
    }


def counts_summary():
    start, end = period(default_days=90)
    counts = db.session.execute(select(AICount).where(AICount.created_at >= start, AICount.created_at < end)).scalars().all()
    by_status = defaultdict(int)
    by_model = defaultdict(list)
    for c in counts:
        by_status[c.status] += 1
        if c.detected_count is not None and c.confirmed_shoes is not None:
            error = abs(c.detected_count - c.confirmed_shoes)

            by_model[c.model_version].append((error, c.confirmed_shoes))
    def stats(values):
        if not values:
            return None
        errs = [e for e, _ in values]
        total_true = sum(t for _, t in values)
        return {"counts": len(values), "mae": round(sum(errs) / len(errs), 3),
                "exact_rate": round(sum(1 for e in errs if e == 0) / len(errs), 3),
                "relative_error": round(sum(errs) / total_true, 3) if total_true else None}
    return {
        "from": iso(start), "to": iso(end), "total": len(counts), "by_status": dict(by_status),
        "manual_only": sum(1 for c in counts if c.model_version is None),
        "accuracy": stats([pair for values in by_model.values() for pair in values]),
        "by_model": {k or "sin_modelo": stats(v) for k, v in by_model.items()},
        "applied_differences": [
            {"count_id": c.id, "sku": c.variant.sku if c.variant else None, "stock_before": c.stock_before,
             "counted": c.applied_pairs, "difference": c.applied_pairs - c.stock_before}
            for c in counts if c.status == "aplicado" and c.stock_before is not None],
    }


def overview():
    now = utcnow()
    last30 = now - timedelta(days=30)
    recent = db.session.execute(select(InventoryMovement).order_by(InventoryMovement.id.desc()).limit(10)).scalars().all()
    alerts = db.session.execute(
        select(ProductVariant).join(Product).join(Brand)
        .where(ProductVariant.stock_quantity <= ProductVariant.min_stock, ProductVariant.status == "activo")
        .order_by(ProductVariant.stock_quantity, Brand.name).limit(10)).scalars().all()
    moves = db.session.execute(select(InventoryMovement).where(InventoryMovement.created_at >= last30)).scalars().all()
    imports = db.session.execute(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(5)).scalars().all()
    orders_open = db.session.execute(select(func.count()).select_from(Order).where(
        Order.status.in_(("creado", "pago_confirmado", "preparado", "enviado")))).scalar_one()
    counts_pending = db.session.execute(select(func.count()).select_from(AICount).where(
        AICount.status.in_(("revision", "confirmado")))).scalar_one()
    from ..ai.detector import model_status
    model, _ = model_status()
    return {
        "inventory": inventory_summary(),
        "last_30_days": {
            "entries": sum(m.quantity for m in moves if m.quantity > 0),
            "exits": sum(-m.quantity for m in moves if m.quantity < 0),
            "units_sold": sum(-m.quantity for m in moves if m.movement_type in SALE_TYPES),
            "movements": len(moves),
        },
        "alerts": [{"variant_id": v.id, "sku": v.sku, "product": f"{v.product.brand.name} {v.product.model_name}",
                    "size": v.size, "color": v.color, "stock": v.stock_quantity, "min_stock": v.min_stock,
                    "state": v.stock_state} for v in alerts],
        "recent_movements": [m.to_dict() for m in recent],
        "recent_imports": [b.to_dict() for b in imports],
        "orders_open": orders_open,
        "counts_pending": counts_pending,
        "ai_model": {"installed": model["installed"], "version": model.get("version"),
                     "message": model.get("message")},
        "trade_records": db.session.execute(select(func.count()).select_from(TradeRecord)).scalar_one(),
    }


# ---------- Comercio exterior ----------

def trade_query():
    from ..common import query_int
    query = select(TradeRecord)
    if (y1 := query_int("year_from")) is not None:
        query = query.where(TradeRecord.year >= y1)
    if (y2 := query_int("year_to")) is not None:
        query = query.where(TradeRecord.year <= y2)
    if flow := request.args.get("flow"):
        query = query.where(TradeRecord.flow == flow)
    if category := request.args.get("category"):
        query = query.where(TradeRecord.category == category)
    if partner := request.args.get("partner"):
        query = query.where(TradeRecord.partner == partner)
    if reporter := request.args.get("reporter"):
        query = query.where(TradeRecord.reporter == reporter)
    if hs6 := request.args.get("hs6"):
        query = query.where(TradeRecord.hs6_code == hs6)
    if request.args.get("include_aggregates") != "1":
        query = query.where(TradeRecord.is_aggregate.is_(False))
    return query.order_by(TradeRecord.year, TradeRecord.flow, TradeRecord.partner, TradeRecord.hs6_code)


def _f(value):
    return float(value) if value is not None else 0.0


def trade_summary(top=10, metric="value_usd"):
    if metric not in ("value_usd", "quantity_pairs"):
        raise ApiError("'metric' debe ser value_usd o quantity_pairs.")
    records = db.session.execute(trade_query()).scalars().all()
    by_year_flow = defaultdict(lambda: {"value_usd": 0.0, "quantity_pairs": 0.0, "rows": 0})
    by_partner = defaultdict(lambda: {"value_usd": 0.0, "quantity_pairs": 0.0})
    by_category = defaultdict(lambda: {"value_usd": 0.0, "quantity_pairs": 0.0})
    per_pair_year = defaultdict(lambda: [0.0, 0.0])
    per_pair_category = defaultdict(lambda: [0.0, 0.0])
    flags = defaultdict(int)
    for r in records:
        key = (r.year, r.flow)
        by_year_flow[key]["value_usd"] += _f(r.value_usd)
        by_year_flow[key]["quantity_pairs"] += _f(r.quantity_pairs)
        by_year_flow[key]["rows"] += 1
        by_partner[(r.partner, r.flow)]["value_usd"] += _f(r.value_usd)
        by_partner[(r.partner, r.flow)]["quantity_pairs"] += _f(r.quantity_pairs)
        cat = r.category or f"SA {r.hs6_code}"
        by_category[(cat, r.flow)]["value_usd"] += _f(r.value_usd)
        by_category[(cat, r.flow)]["quantity_pairs"] += _f(r.quantity_pairs)
        if r.value_usd and r.quantity_pairs and r.value_usd > 0 and r.quantity_pairs > 0 and not r.is_aggregate:
            per_pair_year[(r.year, r.flow)][0] += float(r.value_usd)
            per_pair_year[(r.year, r.flow)][1] += float(r.quantity_pairs)
            per_pair_category[(cat, r.flow)][0] += float(r.value_usd)
            per_pair_category[(cat, r.flow)][1] += float(r.quantity_pairs)
        for flag in r.quality_flags or []:
            flags[flag] += 1

    years = sorted({y for y, _ in by_year_flow})
    flows = sorted({f for _, f in by_year_flow})
    yearly = [{"year": y, "flow": f, **by_year_flow[(y, f)]} for y in years for f in flows if (y, f) in by_year_flow]
    variation = []
    for f in flows:
        previous = None
        for y in years:
            current = by_year_flow.get((y, f))
            if current is None:
                previous = None
                continue
            if previous and previous["value_usd"] > 0:
                variation.append({"flow": f, "year": y,
                                  "value_change_pct": round((current["value_usd"] / previous["value_usd"] - 1) * 100, 2)})
            previous = current
    partners = sorted(({"partner": p, "flow": f, **v} for (p, f), v in by_partner.items()),
                      key=lambda i: -i[metric])[:top]
    categories = sorted(({"category": c, "flow": f, **v} for (c, f), v in by_category.items()),
                        key=lambda i: -i["value_usd"])
    per_pair = [{"year": y, "flow": f, "value_per_pair": round(v / q, 4), "pairs_used": q}
                for (y, f), (v, q) in sorted(per_pair_year.items()) if q > 0]
    per_pair_cat = [{"category": c, "flow": f, "value_per_pair": round(v / q, 4), "pairs_used": q}
                    for (c, f), (v, q) in sorted(per_pair_category.items()) if q > 0]
    total = len(records)
    complete = sum(1 for r in records if r.value_usd is not None and r.quantity_pairs)
    return {
        "records": total,
        "metric": metric,
        "by_year_flow": yearly,
        "annual_variation": variation,
        "top_partners": partners,
        "by_category": categories,
        "value_per_pair_by_year": per_pair,
        "value_per_pair_by_category": per_pair_cat,
        "quality": {"flags": dict(flags), "complete_rows": complete,
                    "completeness": round(complete / total, 4) if total else None,
                    "aggregates_excluded": request.args.get("include_aggregates") != "1"},
    }


def trade_filter_options():
    def distinct(column):
        return [v for v in db.session.execute(select(column).distinct().order_by(column)).scalars() if v is not None]
    return {"years": distinct(TradeRecord.year), "flows": distinct(TradeRecord.flow),
            "categories": distinct(TradeRecord.category), "partners": distinct(TradeRecord.partner),
            "reporters": distinct(TradeRecord.reporter)}


def _es(value, decimals=0):
    """Número con formato español (miles con punto, decimales con coma)."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def trade_synthesis():
    """Síntesis ejecutiva trazable: cada frase cita el cálculo del que sale."""
    summary = trade_summary(top=5)
    if summary["records"] == 0:
        return {"available": False, "message": "No hay datos comerciales importados con estos filtros."}
    findings = []
    yearly = summary["by_year_flow"]
    totals = defaultdict(float)
    for row in yearly:
        totals[row["flow"]] += row["value_usd"]
    if totals:
        parts = ", ".join(f"{flow}: {_es(value)} USD" for flow, value in sorted(totals.items()))
        findings.append(f"Valor total por flujo en el período filtrado — {parts} (suma de Valor_USD, sin agregados).")
    if summary["top_partners"]:
        leader = summary["top_partners"][0]
        total_flow = totals.get(leader["flow"], 0) or 1
        findings.append(f"Principal socio: {leader['partner']} ({leader['flow']}) con {_es(leader['value_usd'])} USD, "
                        f"{_es(leader['value_usd'] / total_flow * 100, 1)} % del valor de ese flujo.")
    if summary["annual_variation"]:
        last = summary["annual_variation"][-1]
        findings.append(f"Variación anual más reciente: {last['flow']} {last['year']} "
                        f"{'+' if last['value_change_pct'] > 0 else ''}{_es(last['value_change_pct'], 1)} % respecto al año anterior.")
    elif summary["value_per_pair_by_year"]:
        p = summary["value_per_pair_by_year"][-1]
        findings.append(f"Valor aproximado por par en {p['year']} ({p['flow']}): {_es(p['value_per_pair'], 2)} USD.")
    limitations = []
    quality = summary["quality"]
    if quality["completeness"] is not None and quality["completeness"] < 1:
        limitations.append(f"Solo el {_es(quality['completeness'] * 100)} % de las filas tiene valor y cantidad de pares; "
                           "el valor por par se calcula únicamente con esas filas.")
    if quality["flags"]:
        flags = ", ".join(f"{k} ({v})" for k, v in quality["flags"].items())
        limitations.append(f"Banderas de calidad detectadas en la importación: {flags}.")
    limitations.append("Son estadísticas de comercio exterior agregadas por país: no describen las ventas, "
                       "costos ni stock de la tienda y no permiten atribuir causas internas a ninguna empresa.")
    years = sorted({row["year"] for row in yearly})
    if years:
        limitations.append(f"Cobertura: {len(years)} año(s) ({years[0]}–{years[-1]}) y {summary['records']} filas; "
                           "el valor por par es un promedio que mezcla códigos SA6 con productos distintos.")
    return {
        "available": True,
        "findings": findings[:3],
        "limitations": limitations[:2],
        "strategic_question": ("¿Qué categorías y socios concentran el valor importado y cómo se compara su valor "
                               "por par con el precio de venta y el costo de nuestras variantes equivalentes?"),
        "recommendation": ("Contrastar el valor por par importado de las categorías principales con el costo "
                           "registrado de las variantes de la tienda antes de fijar precios o volúmenes de compra; "
                           "decidir solo con filas completas y sin agregados."),
        "filters": {k: v for k, v in request.args.items()},
        "visualizations": ["Importaciones vs. exportaciones por año", "Principales socios",
                           "Valor aproximado por par por año"],
        "records_used": summary["records"],
        "generated_at": iso(datetime.now(timezone.utc)),
    }
