"""KPI de negocio calculados desde la base de datos (solo lectura).

Cada KPI tiene definición, fórmula, período y fuente en KPI_DEFINITIONS (se muestran en la interfaz).
Reglas: ingresos ≠ margen; físico ≠ disponible; sin costos no se calcula margen (se informa la cobertura).
"""
from collections import defaultdict
from datetime import timedelta, timezone
from decimal import Decimal

from flask import request
from sqlalchemy import func, select

from ..common import iso, parse_date_range, query_int, utcnow
from ..extensions import db

KPI_DEFINITIONS = [
    # Inventario (foto actual)
    {"id": "inventory_value_cost", "name": "Valor del inventario a costo", "formula": "Σ costo × pares físicos (variantes con costo)", "period": "actual", "source": "product_variants / stock_levels"},
    {"id": "inventory_value_price", "name": "Valor potencial de venta", "formula": "Σ precio × pares físicos (variantes con precio)", "period": "actual", "source": "product_variants / stock_levels"},
    {"id": "pairs_on_hand", "name": "Pares físicos", "formula": "Σ físico", "period": "actual", "source": "stock_levels"},
    {"id": "pairs_available", "name": "Pares disponibles", "formula": "Σ (físico − reservado)", "period": "actual", "source": "stock_levels"},
    {"id": "pairs_reserved", "name": "Pares reservados", "formula": "Σ reservado por pedidos abiertos", "period": "actual", "source": "stock_levels"},
    {"id": "pairs_in_transit", "name": "Pares en tránsito", "formula": "Σ (pedido − recibido) de órdenes aprobadas/solicitadas", "period": "actual", "source": "purchase_order_lines"},
    {"id": "zero_stock_variants", "name": "Variantes sin stock", "formula": "variantes activas con disponible = 0", "period": "actual", "source": "product_variants"},
    {"id": "below_reorder", "name": "Bajo punto de reposición", "formula": "recomendaciones de reposición pendientes", "period": "último cálculo", "source": "replenishment_recommendations"},
    {"id": "low_rotation", "name": "Baja rotación", "formula": "variantes con stock y sin ventas en N días (Configuración)", "period": "N días", "source": "inventory_movements"},
    {"id": "inventory_age_days", "name": "Antigüedad media del inventario", "formula": "Σ(días desde la última entrada × pares) / Σ pares", "period": "actual", "source": "inventory_movements"},
    {"id": "count_differences", "name": "Diferencias de inventario físico", "formula": "Σ |diferencia| de conteos físicos", "period": "filtro de fechas", "source": "inventory_movements (conteo_fisico)"},
    # Ventas
    {"id": "revenue_net", "name": "Ingresos netos", "formula": "ventas TPV/integración (total con descuentos) + pedidos online pagados − reembolsos de devoluciones", "period": "filtro de fechas", "source": "sales, orders, sale_returns"},
    {"id": "units_sold", "name": "Pares vendidos", "formula": "Σ cantidad de líneas de venta + líneas de pedidos pagados", "period": "filtro de fechas", "source": "sale_items, order_items"},
    {"id": "cogs", "name": "Costo de la mercancía vendida", "formula": "Σ costo unitario registrado al vender × cantidad (solo líneas con costo)", "period": "filtro de fechas", "source": "sale_items.unit_cost, order_items.unit_cost"},
    {"id": "gross_margin", "name": "Margen bruto", "formula": "ingresos de líneas con costo − su costo; % = margen / esos ingresos", "period": "filtro de fechas", "source": "derivado"},
    {"id": "avg_ticket", "name": "Ticket promedio", "formula": "ingresos TPV / n.º de tickets", "period": "filtro de fechas", "source": "sales"},
    {"id": "returns", "name": "Devoluciones y cancelaciones", "formula": "pares devueltos (TPV + online) y pedidos cancelados", "period": "filtro de fechas", "source": "return_items, orders"},
    # Reposición
    {"id": "replenishment_suggested", "name": "Pares sugeridos para comprar", "formula": "Σ cantidad sugerida de recomendaciones pendientes/revisadas", "period": "último cálculo", "source": "replenishment_recommendations"},
    {"id": "supplier_on_time", "name": "Cumplimiento de plazos", "formula": "órdenes recibidas con fecha ≤ prevista / órdenes recibidas con fecha prevista", "period": "histórico", "source": "purchase_orders"},
    {"id": "stockout_days", "name": "Días sin stock", "formula": "Σ días con físico = 0 reconstruidos del libro de movimientos", "period": "filtro de fechas", "source": "inventory_movements"},
    # IA
    {"id": "ai_images", "name": "Imágenes procesadas", "formula": "conteos + análisis de registro + lecturas de etiqueta", "period": "filtro de fechas", "source": "ai_counts, vision_analyses, stored_files"},
    {"id": "ai_false_positives", "name": "Detecciones falsas", "formula": "cajas del modelo rechazadas en la revisión", "period": "filtro de fechas", "source": "ai_detections"},
    {"id": "ai_missed", "name": "Zapatos omitidos", "formula": "cajas añadidas a mano en la revisión", "period": "filtro de fechas", "source": "ai_detections"},
    {"id": "ai_count_mae", "name": "Error medio de conteo", "formula": "media de |detectados − confirmados| en conteos confirmados con modelo", "period": "filtro de fechas", "source": "ai_counts"},
    {"id": "ai_identification_precision", "name": "Acierto de identificación visual", "formula": "propuestas top-1 aceptadas / propuestas top-1 revisadas", "period": "histórico", "source": "identification_feedback"},
]


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def period():
    start, end = parse_date_range()
    end = end or (utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    start = start or end - timedelta(days=30)
    return start, end


def _filters():
    return {"location_id": query_int("location_id"), "category_id": query_int("category_id"),
            "brand_id": query_int("brand_id"), "channel": request.args.get("channel") or None,
            "size": request.args.get("size") or None, "color": (request.args.get("color") or "").lower() or None}


def _variant_ok(variant, f):
    p = variant.product
    return ((f["category_id"] is None or p.category_id == f["category_id"]) and
            (f["brand_id"] is None or p.brand_id == f["brand_id"]) and
            (f["size"] is None or variant.size == f["size"]) and
            (f["color"] is None or variant.color.lower() == f["color"]))


def inventory_kpis(f):
    from ..inventory.models import InventoryMovement, StockLevel
    from ..inventory.settings import get_setting
    from ..products.models import Product, ProductVariant
    from ..purchasing.models import OPEN_PO_STATUSES, PurchaseOrder, PurchaseOrderLine, ReplenishmentRecommendation

    levels = db.session.execute(select(StockLevel)).scalars().all()
    by_variant = defaultdict(lambda: [0, 0])
    for lv in levels:
        if f["location_id"] is None or lv.location_id == f["location_id"]:
            by_variant[lv.variant_id][0] += lv.on_hand
            by_variant[lv.variant_id][1] += lv.reserved
    variants = [v for v in db.session.execute(select(ProductVariant)).scalars() if _variant_ok(v, f)]
    value_cost = value_price = Decimal("0")
    on_hand = reserved = zero = 0
    missing_cost = 0
    for v in variants:
        oh, rs = by_variant[v.id]
        on_hand, reserved = on_hand + oh, reserved + rs
        if v.cost is not None:
            value_cost += v.cost * oh
        elif oh:
            missing_cost += 1
        if v.price is not None:
            value_price += v.price * oh
        if v.status == "activo" and oh - rs <= 0:
            zero += 1
    ids = {v.id for v in variants}
    transit_q = (select(PurchaseOrderLine.variant_id, func.sum(PurchaseOrderLine.quantity_ordered - PurchaseOrderLine.quantity_received))
                 .join(PurchaseOrder).where(PurchaseOrder.status.in_(OPEN_PO_STATUSES)))
    if f["location_id"]:
        transit_q = transit_q.where(PurchaseOrder.location_id == f["location_id"])
    transit = sum(int(q or 0) for vid, q in db.session.execute(transit_q.group_by(PurchaseOrderLine.variant_id)) if vid in ids)
    below = sum(1 for r in db.session.execute(select(ReplenishmentRecommendation).where(
        ReplenishmentRecommendation.status.in_(("pendiente", "revisada")))).scalars() if r.variant_id in ids)
    # Antigüedad: días desde la última entrada positiva, ponderada por pares.
    last_in = dict(db.session.execute(select(InventoryMovement.variant_id, func.max(InventoryMovement.created_at))
                                      .where(InventoryMovement.quantity > 0).group_by(InventoryMovement.variant_id)).all())
    now = utcnow()
    weighted = pairs = 0
    rotation_days = int(get_setting("low_rotation_days"))
    since = now - timedelta(days=rotation_days)
    sold_recent = {vid for (vid,) in db.session.execute(select(InventoryMovement.variant_id).where(
        InventoryMovement.created_at >= since, InventoryMovement.movement_type.in_(("salida_venta", "salida_pedido"))).distinct())}
    low_rotation = 0
    for v in variants:
        oh = by_variant[v.id][0]
        entry = _aware(last_in.get(v.id))
        if oh and entry:
            weighted += (now - entry).days * oh
            pairs += oh
            if v.id not in sold_recent and entry < since:
                low_rotation += 1
    start, end = period()
    diffs = db.session.execute(select(func.coalesce(func.sum(func.abs(InventoryMovement.quantity)), 0)).where(
        InventoryMovement.movement_type == "conteo_fisico", InventoryMovement.created_at >= start,
        InventoryMovement.created_at < end)).scalar_one()
    active_products = db.session.execute(select(func.count()).select_from(Product).where(Product.status == "activo")).scalar_one()
    return {
        "inventory_value_cost": str(value_cost.quantize(Decimal("0.01"))), "variants_without_cost": missing_cost,
        "inventory_value_price": str(value_price.quantize(Decimal("0.01"))),
        "pairs_on_hand": on_hand, "pairs_reserved": reserved, "pairs_available": on_hand - reserved,
        "pairs_in_transit": transit, "active_products": active_products, "variants": len(variants),
        "zero_stock_variants": zero, "below_reorder": below, "low_rotation": low_rotation,
        "low_rotation_days": rotation_days,
        "inventory_age_days": round(weighted / pairs, 1) if pairs else None,
        "count_differences": int(diffs or 0),
    }


def sales_kpis(f):
    from ..products.models import ProductVariant
    from ..sales.models import Sale, SaleReturn
    from ..shop.models import Order, OrderItem

    start, end = period()
    paid = ("pago_confirmado", "preparado", "enviado", "entregado", "devuelto")
    lines = []  # (fecha, canal, ubicación, variante, cantidad, ingresos, costo|None, ticket)
    sales_q = select(Sale).where(Sale.created_at >= start, Sale.created_at < end)
    if f["location_id"]:
        sales_q = sales_q.where(Sale.location_id == f["location_id"])
    tickets = 0
    tpv_revenue = Decimal("0")
    for sale in db.session.execute(sales_q).scalars():
        if f["channel"] and sale.channel != f["channel"]:
            continue
        counted = False
        for item in sale.items:
            if not _variant_ok(item.variant, f):
                continue
            counted = True
            lines.append((sale.created_at, sale.channel, sale.location_id, item.variant, item.quantity, item.line_total,
                          (item.unit_cost * item.quantity) if item.unit_cost is not None else None))
            tpv_revenue += item.line_total
        tickets += int(counted)
    if f["channel"] in (None, "online"):
        orders_q = select(Order).where(Order.created_at >= start, Order.created_at < end, Order.status.in_(paid))
        if f["location_id"]:
            orders_q = orders_q.where(Order.location_id == f["location_id"])
        for order in db.session.execute(orders_q).scalars():
            for item in order.items:
                variant = db.session.get(ProductVariant, item.variant_id)
                if variant is None or not _variant_ok(variant, f):
                    continue
                lines.append((order.created_at, "online", order.location_id, variant, item.quantity, item.line_total,
                              (item.unit_cost * item.quantity) if item.unit_cost is not None else None))
    refunds = Decimal("0")
    returned_units = 0
    for ret in db.session.execute(select(SaleReturn).where(SaleReturn.created_at >= start, SaleReturn.created_at < end)).scalars():
        if f["location_id"] and ret.sale.location_id != f["location_id"]:
            continue
        refunds += ret.refund_amount
        returned_units += sum(i.quantity for i in ret.items)
    online_returned = db.session.execute(select(func.coalesce(func.sum(OrderItem.quantity), 0)).join(Order).where(
        Order.status == "devuelto", Order.updated_at >= start, Order.updated_at < end)).scalar_one()
    online_refunds = db.session.execute(select(func.coalesce(func.sum(Order.total_amount), 0)).where(
        Order.status == "devuelto", Order.updated_at >= start, Order.updated_at < end)).scalar_one()
    cancelled = db.session.execute(select(func.count()).select_from(Order).where(
        Order.status == "cancelado", Order.updated_at >= start, Order.updated_at < end)).scalar_one()
    from ..inventory.models import Location
    location_names = {loc.id: loc.name for loc in db.session.execute(select(Location)).scalars()}
    gross = sum((ln[5] for ln in lines), Decimal("0"))
    with_cost = [ln for ln in lines if ln[6] is not None]
    revenue_with_cost = sum((ln[5] for ln in with_cost), Decimal("0"))
    cogs = sum((ln[6] for ln in with_cost), Decimal("0"))
    margin = revenue_with_cost - cogs
    net = gross - refunds - Decimal(str(online_refunds or 0))

    def group(key):
        acc = defaultdict(lambda: {"units": 0, "revenue": Decimal("0")})
        for ln in lines:
            k = key(ln)
            acc[k]["units"] += ln[4]
            acc[k]["revenue"] += ln[5]
        return sorted(({"key": k, "units": v["units"], "revenue": str(v["revenue"])} for k, v in acc.items()),
                      key=lambda r: -r["units"])

    group_by = request.args.get("group", "day")
    def bucket(moment):
        moment = _aware(moment)
        if group_by == "month":
            return f"{moment:%Y-%m}"
        if group_by == "week":
            return (moment - timedelta(days=moment.weekday())).date().isoformat()
        return moment.date().isoformat()

    return {
        "from": iso(start), "to": iso(end),
        "revenue_gross": str(gross), "refunds": str(refunds + Decimal(str(online_refunds or 0))), "revenue_net": str(net),
        "units_sold": sum(ln[4] for ln in lines), "tickets": tickets,
        "avg_ticket": str((tpv_revenue / tickets).quantize(Decimal("0.01"))) if tickets else None,
        "cogs": str(cogs), "gross_margin": str(margin),
        "gross_margin_pct": round(float(margin / revenue_with_cost * 100), 1) if revenue_with_cost else None,
        "cost_coverage_pct": round(len(with_cost) / len(lines) * 100, 1) if lines else None,
        "returned_units": returned_units + int(online_returned or 0), "orders_cancelled": cancelled,
        "series": sorted(group(lambda ln: bucket(ln[0])), key=lambda r: r["key"]),
        "top_products": group(lambda ln: f"{ln[3].product.brand.name} {ln[3].product.model_name}")[:10],
        "by_brand": group(lambda ln: ln[3].product.brand.name),
        "by_size": group(lambda ln: ln[3].size),
        "by_color": group(lambda ln: ln[3].color),
        "by_channel": group(lambda ln: ln[1]),
        "by_location": group(lambda ln: location_names.get(ln[2], str(ln[2]))),
        "has_data": bool(lines),
    }


def replenishment_kpis():
    from ..products.models import Supplier
    from ..purchasing.models import PurchaseOrder, ReplenishmentRecommendation

    recs = db.session.execute(select(ReplenishmentRecommendation).where(
        ReplenishmentRecommendation.status.in_(("pendiente", "revisada")))).scalars().all()
    received = db.session.execute(select(PurchaseOrder).where(PurchaseOrder.status == "recibida",
                                                              PurchaseOrder.expected_date.isnot(None))).scalars().all()
    on_time = sum(1 for po in received if po.received_at and _aware(po.received_at).date() <= po.expected_date)
    leads = [s.lead_time_days for s in db.session.execute(select(Supplier)).scalars() if s.lead_time_days is not None]
    return {
        "recommendations_open": len(recs), "replenishment_suggested": sum(r.suggested_qty for r in recs),
        "high_priority": sum(1 for r in recs if r.priority == "alta"),
        "avg_supplier_lead_days": round(sum(leads) / len(leads), 1) if leads else None,
        "supplier_on_time_pct": round(on_time / len(received) * 100, 1) if received else None,
        "received_orders_with_date": len(received),
        "stockout_days": stockout_days(),
    }


def stockout_days():
    """Días-variante con stock físico 0 en el período, reconstruidos del libro (solo variantes con historia)."""
    from ..inventory.models import InventoryMovement

    start, end = period()
    rows = db.session.execute(select(InventoryMovement.variant_id, InventoryMovement.created_at, InventoryMovement.balance_after)
                              .order_by(InventoryMovement.variant_id, InventoryMovement.created_at, InventoryMovement.id)).all()
    timeline = defaultdict(list)
    for vid, at, bal in rows:
        timeline[vid].append((_aware(at), bal))
    total = 0.0
    for events in timeline.values():
        balance, cursor = None, start
        for at, bal in events:
            if at <= start:
                balance = bal
                continue
            if at >= end:
                break
            if balance == 0:
                total += (at - cursor).total_seconds()
            balance, cursor = bal, at
        if balance == 0:
            total += (end - cursor).total_seconds()
    return round(total / 86400, 1)


def ai_kpis():
    from ..ai.detector import model_status
    from ..ai.models import AICount, AIDetection
    from ..files.models import StoredFile
    from ..vision.models import VisionAnalysis
    from ..vision.services import calibration

    start, end = period()
    counts = db.session.execute(select(AICount).where(AICount.created_at >= start, AICount.created_at < end)).scalars().all()
    ids = [c.id for c in counts]
    rejected = manual = 0
    if ids:
        rejected = db.session.execute(select(func.count()).select_from(AIDetection).where(
            AIDetection.count_id.in_(ids), AIDetection.source == "modelo", AIDetection.accepted.is_(False))).scalar_one()
        manual = db.session.execute(select(func.count()).select_from(AIDetection).where(
            AIDetection.count_id.in_(ids), AIDetection.source == "manual", AIDetection.accepted.is_(True))).scalar_one()
    errors = [abs(c.detected_count - c.confirmed_shoes) for c in counts
              if c.detected_count is not None and c.confirmed_shoes is not None]
    analyses = db.session.execute(select(func.count()).select_from(VisionAnalysis).where(
        VisionAnalysis.created_at >= start, VisionAnalysis.created_at < end)).scalar_one()
    labels = db.session.execute(select(func.count()).select_from(StoredFile).where(
        StoredFile.purpose == "etiqueta", StoredFile.created_at >= start, StoredFile.created_at < end)).scalar_one()
    status, _ = model_status()
    cal = calibration()
    top1 = [row for row in cal["table"] if row["threshold"] == 10]
    return {
        "ai_images": len(counts) + analyses + labels, "counts": len(counts), "vision_analyses": analyses, "label_reads": labels,
        "ai_false_positives": rejected, "ai_missed": manual,
        "ai_count_mae": round(sum(errors) / len(errors), 3) if errors else None, "ai_count_reviewed": len(errors),
        "pending_review": sum(1 for c in counts if c.status in ("revision", "confirmado")),
        "ai_identification_precision": top1[0]["precision"] if top1 else None, "identification_decisions": cal["decisions"],
        "model": {"installed": status["installed"], "version": status.get("version"),
                  "test_metrics": (status.get("metadata") or {}).get("metrics", {}).get("test")},
    }


def all_kpis():
    f = _filters()
    return {"filters": f, "inventory": inventory_kpis(f), "sales": sales_kpis(f), "replenishment": replenishment_kpis(),
            "ai": ai_kpis(), "definitions": KPI_DEFINITIONS, "generated_at": iso(utcnow())}

