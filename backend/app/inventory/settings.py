"""Parámetros configurables con valores por defecto documentados (tabla `settings`)."""
from ..extensions import db
from .models import Setting

DEFAULTS = {
    # Reposición
    "replenishment_history_days": {"value": 90, "label": "Días de historial de ventas para calcular la demanda"},
    "replenishment_default_lead_days": {"value": 14, "label": "Plazo de entrega por defecto si el proveedor no lo indica (días)"},
    "replenishment_safety_days": {"value": 7, "label": "Stock de seguridad expresado en días de demanda"},
    "replenishment_cover_days": {"value": 30, "label": "Días de cobertura del stock objetivo tras reponer"},
    "replenishment_min_sales": {"value": 2, "label": "Ventas mínimas en el período para recomendar (evita comprar tallas que no se venden)"},
    # Alertas
    "low_rotation_days": {"value": 60, "label": "Días sin ventas con stock para considerar baja rotación"},
    "anomaly_adjust_pairs": {"value": 10, "label": "Ajuste o baja (pares) a partir del cual se marca como movimiento atípico"},
    # Identificación visual (umbrales SIN calibrar con fotos reales: ver /api/vision/calibration)
    "vision_high_score": {"value": 45, "label": "Similitud (0–100) a partir de la cual una coincidencia se considera fuerte"},
    "vision_low_score": {"value": 25, "label": "Similitud (0–100) por debajo de la cual no se propone la coincidencia"},
    # Reservas de pedidos online
    "reserve_on_order": {"value": True, "label": "Los pedidos online reservan stock al crearse"},
}


def get_setting(key):
    row = db.session.get(Setting, key)
    if row is not None:
        return row.value
    return DEFAULTS[key]["value"]


def all_settings():
    stored = {s.key: s.value for s in db.session.query(Setting).all()}
    return [{"key": k, "label": d["label"], "default": d["value"], "value": stored.get(k, d["value"])}
            for k, d in DEFAULTS.items()]


def set_setting(key, value, user=None):
    if key not in DEFAULTS:
        raise KeyError(key)
    default = DEFAULTS[key]["value"]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError("Debe ser verdadero o falso.")
    elif isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Debe ser un entero mayor o igual a 0.")
    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
    row.updated_by = user.id if user else None
    return row
