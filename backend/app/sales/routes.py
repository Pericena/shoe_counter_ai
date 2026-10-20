from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from ..auth.services import require
from ..common import ApiError, json_body, parse_date_range, query_int
from ..extensions import db
from .models import ReturnItem, Sale
from .services import create_return, create_sale, resolve_return_item

bp = Blueprint("sales", __name__, url_prefix="/api")


@bp.post("/sales")
@require("pos.sell")
def new_sale():
    data = json_body()
    sale, created = create_sale(
        lines=data.get("lines"), location_id=data.get("location_id"), payment_method=data.get("payment_method", "efectivo"),
        payment_reference=(str(data.get("payment_reference") or "").strip()[:100] or None),
        customer_name=(str(data.get("customer_name") or "").strip()[:150] or None),
        external_ref=(str(data.get("external_ref") or "").strip()[:150] or None),
        allow_price_override=g.user.has("prices.manage"))
    return jsonify({**sale.to_dict(), "duplicate": not created}), 201 if created else 200


@bp.get("/sales")
@require("inventory.view")
def list_sales():
    limit = query_int("limit", default=25, minimum=1, maximum=200)
    offset = query_int("offset", default=0, minimum=0)
    query = select(Sale)
    if (location_id := query_int("location_id")) is not None:
        query = query.where(Sale.location_id == location_id)
    if channel := request.args.get("channel"):
        query = query.where(Sale.channel == channel)
    if q := request.args.get("q"):
        query = query.where(func.lower(Sale.number).like(f"%{q.strip().lower()}%"))
    start, end = parse_date_range()
    if start:
        query = query.where(Sale.created_at >= start)
    if end:
        query = query.where(Sale.created_at < end)
    total = db.session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.session.execute(query.order_by(Sale.id.desc()).limit(limit).offset(offset)).scalars().all()
    return jsonify({"items": [s.to_dict(detail=False) for s in rows], "total": total, "limit": limit, "offset": offset})


@bp.get("/sales/<int:sale_id>")
@require("inventory.view")
def get_sale(sale_id):
    sale = db.session.get(Sale, sale_id)
    if sale is None:
        raise ApiError("La venta no existe.", 404)
    return jsonify(sale.to_dict())


@bp.post("/sales/<int:sale_id>/returns")
@require("returns.manage")
def new_return(sale_id):
    data = json_body()
    record = create_return(sale_id, items=data.get("items"), reason=str(data.get("reason") or "").strip()[:1000])
    return jsonify(record.to_dict()), 201


@bp.get("/returns/pending")
@require("returns.manage")
def pending_returns():
    rows = db.session.execute(select(ReturnItem).where(ReturnItem.condition == "revision", ReturnItem.resolution.is_(None))
                              .order_by(ReturnItem.id)).scalars().all()
    return jsonify({"items": [{**r.to_dict(), "sale_number": r.sale_item.sale.number,
                               "return_number": r.sale_return.number, "reason": r.sale_return.reason} for r in rows]})


@bp.post("/returns/items/<int:item_id>/resolve")
@require("returns.manage")
def resolve(item_id):
    item = resolve_return_item(item_id, json_body().get("resolution"))
    return jsonify(item.to_dict())
