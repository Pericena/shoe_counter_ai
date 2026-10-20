from datetime import date

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, json_body, utcnow
from ..extensions import db
from ..inventory.services import resolve_location
from ..products.models import ProductVariant, Supplier
from .models import PO_STATUSES, REC_STATUSES, PurchaseOrder, PurchaseOrderLine, ReplenishmentRecommendation
from .services import _number, change_po_status, compute_recommendations, create_po_from_recommendations, receive

bp = Blueprint("purchasing", __name__, url_prefix="/api")


@bp.post("/replenishment/compute")
@require("purchases.manage")
def compute():
    created = compute_recommendations()
    return jsonify({"created": len(created)})


@bp.get("/replenishment")
@require("purchases.manage")
def list_recommendations():
    query = select(ReplenishmentRecommendation)
    if status := request.args.get("status"):
        if status not in REC_STATUSES:
            raise ApiError("Estado no válido.")
        query = query.where(ReplenishmentRecommendation.status == status)
    if priority := request.args.get("priority"):
        query = query.where(ReplenishmentRecommendation.priority == priority)
    order = {"alta": 0, "media": 1, "baja": 2}
    rows = db.session.execute(query).scalars().all()
    rows.sort(key=lambda r: (order.get(r.priority, 3), -r.suggested_qty))
    return jsonify({"items": [r.to_dict() for r in rows]})


@bp.patch("/replenishment/<int:rec_id>")
@require("purchases.manage")
def update_recommendation(rec_id):
    rec = db.session.get(ReplenishmentRecommendation, rec_id)
    if rec is None:
        raise ApiError("La recomendación no existe.", 404)
    data = json_body()
    status = data.get("status")
    if status not in ("revisada", "descartada", "pendiente"):
        raise ApiError("Datos no válidos.", 422, {"status": "revisada, descartada o pendiente."})
    if rec.status in ("aprobada", "solicitada", "recibida"):
        raise ApiError("La recomendación ya tiene una orden de compra.", 409)
    if "suggested_qty" in data:
        qty = data["suggested_qty"]
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError("Datos no válidos.", 422, {"suggested_qty": "Entero mayor que 0."})
        rec.suggested_qty = qty
    rec.status, rec.reviewed_by, rec.reviewed_at = status, g.user.id, utcnow()
    audit("reposicion_revisada", "replenishment", rec.id, {"estado": status, "cantidad": rec.suggested_qty})
    db.session.commit()
    return jsonify(rec.to_dict())


@bp.post("/replenishment/to-purchase")
@require("purchases.manage")
def to_purchase():
    ids = json_body().get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids) or not ids:
        raise ApiError("Datos no válidos.", 422, {"ids": "Lista de ids de recomendaciones."})
    orders = create_po_from_recommendations(ids)
    return jsonify({"orders": [o.to_dict(detail=False) for o in orders]}), 201


@bp.get("/purchases")
@require("purchases.manage")
def list_orders():
    query = select(PurchaseOrder)
    if status := request.args.get("status"):
        if status not in PO_STATUSES:
            raise ApiError("Estado no válido.")
        query = query.where(PurchaseOrder.status == status)
    rows = db.session.execute(query.order_by(PurchaseOrder.id.desc()).limit(200)).scalars().all()
    return jsonify({"items": [o.to_dict(detail=False) for o in rows]})


@bp.post("/purchases")
@require("purchases.manage")
def create_order():
    data = json_body()
    supplier = db.session.get(Supplier, data.get("supplier_id")) if isinstance(data.get("supplier_id"), int) else None
    if supplier is None:
        raise ApiError("Datos no válidos.", 422, {"supplier_id": "Proveedor no válido."})
    location = resolve_location(data.get("location_id"))
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ApiError("La orden no tiene líneas.", 422)
    po = PurchaseOrder(number=_number("OC"), supplier_id=supplier.id, location_id=location.id, status="borrador",
                       created_by=g.user.id, notes=(str(data.get("notes") or "").strip()[:2000] or None))
    if data.get("expected_date"):
        try:
            po.expected_date = date.fromisoformat(data["expected_date"])
        except ValueError:
            raise ApiError("Datos no válidos.", 422, {"expected_date": "Formato AAAA-MM-DD."})
    for index, line in enumerate(lines):
        vid, qty = line.get("variant_id"), line.get("quantity")
        variant = db.session.get(ProductVariant, vid) if isinstance(vid, int) else None
        if variant is None or isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError("Datos no válidos.", 422, {f"lines[{index}]": "Variante y cantidad (> 0) válidas."})
        po.lines.append(PurchaseOrderLine(variant_id=variant.id, quantity_ordered=qty,
                                          unit_cost=line.get("unit_cost", variant.cost)))
    db.session.add(po)
    db.session.flush()
    audit("orden_compra_creada", "purchase_order", po.id, {"numero": po.number})
    db.session.commit()
    return jsonify(po.to_dict()), 201


def _get(po_id):
    po = db.session.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update()
                            .execution_options(populate_existing=True)).scalar_one_or_none()
    if po is None:
        raise ApiError("La orden de compra no existe.", 404)
    return po


@bp.get("/purchases/<int:po_id>")
@require("purchases.manage")
def get_order(po_id):
    return jsonify(_get(po_id).to_dict())


@bp.post("/purchases/<int:po_id>/status")
@require("purchases.manage")
def order_status(po_id):
    po = _get(po_id)
    change_po_status(po, json_body().get("status"))
    return jsonify(po.to_dict())


@bp.post("/purchases/<int:po_id>/receive")
@require("purchases.manage", "inventory.move")
def order_receive(po_id):
    po = _get(po_id)
    data = json_body()
    applied = receive(po, data.get("lines"), (str(data.get("receipt_ref") or "").strip()[:60] or None))
    return jsonify({**po.to_dict(), "lines_applied": applied})


@bp.get("/purchases/summary")
@require("purchases.manage")
def purchases_summary():
    in_transit = db.session.execute(select(func.coalesce(func.sum(
        PurchaseOrderLine.quantity_ordered - PurchaseOrderLine.quantity_received), 0)).join(PurchaseOrder)
        .where(PurchaseOrder.status.in_(("aprobada", "solicitada", "recibida_parcial")))).scalar_one()
    return jsonify({"units_in_transit": int(in_transit)})

