"""Análisis de calidad del inventario: movimientos atípicos, posibles duplicados y datos incompletos."""
import re
import statistics
import unicodedata
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select

from ..common import utcnow
from ..extensions import db


def _fold(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def anomalies(days=90):
    """Ajustes/bajas/conteos cuyo tamaño se aleja del patrón (|z| ≥ 3) o supera el umbral configurado."""
    from ..inventory.models import InventoryMovement
    from ..inventory.settings import get_setting

    threshold = int(get_setting("anomaly_adjust_pairs"))
    rows = db.session.execute(select(InventoryMovement).where(
        InventoryMovement.created_at >= utcnow() - timedelta(days=days),
        InventoryMovement.movement_type.in_(("ajuste", "conteo_fisico", "danado", "perdido")))).scalars().all()
    sizes = [abs(m.quantity) for m in rows]
    mean = statistics.mean(sizes) if sizes else 0
    stdev = statistics.pstdev(sizes) if len(sizes) > 1 else 0
    flagged = []
    by_user = defaultdict(int)
    for m in rows:
        z = (abs(m.quantity) - mean) / stdev if stdev else 0
        reasons = []
        if abs(m.quantity) >= threshold:
            reasons.append(f"≥ {threshold} pares")
        if z >= 3:
            reasons.append(f"z = {z:.1f} respecto a los ajustes del período")
        if reasons:
            flagged.append({**m.to_dict(), "why": reasons})
        by_user[m.user.username if m.user else "sistema"] += abs(m.quantity)
    return {"days": days, "movements_analyzed": len(rows), "mean_abs": round(mean, 2), "stdev": round(stdev, 2),
            "items": flagged, "by_user": dict(by_user)}


def duplicates():
    from ..products.models import Product, ProductVariant

    groups = defaultdict(list)
    for p in db.session.execute(select(Product)).scalars():
        groups[(p.brand_id, _fold(p.model_name))].append(p)
    products = [{"brand": items[0].brand.name, "model_name": items[0].model_name,
                 "products": [{"id": p.id, "code": p.code, "status": p.status} for p in items]}
                for items in groups.values() if len(items) > 1]
    vgroups = defaultdict(list)
    for v in db.session.execute(select(ProductVariant)).scalars():
        size = (v.size or "").replace(",", ".").rstrip("0").rstrip(".") if re.fullmatch(r"\d+([.,]\d+)?", v.size or "") else _fold(v.size)
        vgroups[(v.product_id, size, _fold(v.color))].append(v)
    variants = [{"product_id": items[0].product_id, "variants": [{"id": v.id, "sku": v.sku, "size": v.size, "color": v.color}
                                                                 for v in items]}
                for items in vgroups.values() if len(items) > 1]
    return {"products": products, "variants": variants}


def incomplete():
    from ..products.models import Product, ProductVariant

    items = []
    for p in db.session.execute(select(Product)).scalars():
        missing = [name for name, value in (("categoría", p.category_id), ("proveedor", p.supplier_id),
                                            ("tipo de calzado", p.footwear_type), ("foto", p.images)) if not value]
        if missing:
            items.append({"type": "producto", "id": p.id, "code": p.code, "missing": missing})
    for v in db.session.execute(select(ProductVariant)).scalars():
        missing = [name for name, value in (("precio", v.price), ("costo", v.cost), ("código de barras", v.barcode))
                   if value is None]
        if missing:
            items.append({"type": "variante", "id": v.id, "code": v.sku, "missing": missing})
    return {"items": items, "total": len(items)}
