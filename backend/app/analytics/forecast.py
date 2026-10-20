"""Pronóstico de demanda semanal por variante, transparente y validado.

Métodos candidatos (líneas base estadísticas, no "caja negra"):
  - ingenuo:     la próxima semana = la última semana
  - media móvil: media de las últimas 4 semanas
Validación: con ≥ 8 semanas de historia se pronostican las 4 últimas semanas usando solo los datos
anteriores a cada una (backtest) y se elige el método con menor error absoluto medio (MAE).
Con menos historia se usa la media disponible y se marca como "preliminar" sin precisión.
"""
from collections import defaultdict
from datetime import timedelta, timezone

from sqlalchemy import select

from ..common import utcnow
from ..extensions import db

WEEKS = 26
MIN_WEEKS = 8
HORIZON = 4


def _week_start(moment):
    moment = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment
    return (moment - timedelta(days=moment.weekday())).date()


def weekly_sales(variant_ids=None, location_id=None):
    from ..inventory.models import InventoryMovement

    now = utcnow()
    first_week = _week_start(now) - timedelta(weeks=WEEKS - 1)
    query = select(InventoryMovement).where(
        InventoryMovement.movement_type.in_(("salida_venta", "salida_pedido")),
        InventoryMovement.created_at >= now - timedelta(weeks=WEEKS))
    if variant_ids is not None:
        query = query.where(InventoryMovement.variant_id.in_(variant_ids))
    if location_id:
        query = query.where(InventoryMovement.location_id == location_id)
    series = defaultdict(lambda: defaultdict(int))
    first_sale = {}
    for m in db.session.execute(query).scalars():
        week = _week_start(m.created_at)
        series[m.variant_id][week] += -m.quantity
        first_sale[m.variant_id] = min(first_sale.get(m.variant_id, week), week)
    weeks = [first_week + timedelta(weeks=i) for i in range(WEEKS)]
    out = {}
    for vid, data in series.items():
        start = first_sale[vid]
        out[vid] = [(w, data.get(w, 0)) for w in weeks if w >= start]
    return out


def _predict(history, method):
    if not history:
        return 0.0
    if method == "ingenuo":
        return float(history[-1])
    window = history[-4:]
    return sum(window) / len(window)


def forecast_variant(points):
    values = [v for _, v in points]
    # La semana actual está incompleta: no se usa para validar.
    complete = values[:-1] if len(values) > 1 else values
    result = {"weeks_of_history": len(complete), "history": [{"week": w.isoformat(), "units": v} for w, v in points]}
    if len(complete) >= MIN_WEEKS:
        errors = {}
        for method in ("ingenuo", "media_movil"):
            errs = [abs(_predict(complete[:i], method) - complete[i]) for i in range(len(complete) - HORIZON, len(complete))]
            errors[method] = sum(errs) / len(errs)
        method = min(errors, key=errors.get)
        result.update({"method": method, "backtest_mae": {k: round(v, 2) for k, v in errors.items()},
                       "preliminary": False})
    else:
        method = "media_movil"
        result.update({"method": "media_disponible", "backtest_mae": None, "preliminary": True,
                       "note": f"Solo {len(complete)} semanas completas de ventas (mínimo {MIN_WEEKS}): estimación preliminar."})
    weekly = _predict(complete or values, method)
    result["forecast_weekly"] = round(weekly, 2)
    result["forecast_next_weeks"] = [round(weekly, 2)] * HORIZON
    return result


def forecast(limit=20, location_id=None, variant_id=None):
    from ..products.models import ProductVariant

    series = weekly_sales([variant_id] if variant_id else None, location_id)
    items = []
    for vid, points in series.items():
        variant = db.session.get(ProductVariant, vid)
        if variant is None:
            continue
        f = forecast_variant(points)
        available = variant.stock_quantity - variant.reserved_quantity
        weeks_cover = round(available / f["forecast_weekly"], 1) if f["forecast_weekly"] > 0 else None
        items.append({"variant_id": vid, "sku": variant.sku,
                      "product": f"{variant.product.brand.name} {variant.product.model_name}",
                      "size": variant.size, "color": variant.color, "available": available,
                      "weeks_of_cover": weeks_cover,
                      "stockout_risk": weeks_cover is not None and weeks_cover < 2, **f})
    items.sort(key=lambda i: -(i["forecast_weekly"] or 0))
    return {"items": items[:limit], "variants_with_sales": len(items),
            "method_note": "Líneas base estadísticas validadas con backtest de 4 semanas; no son certezas."}
