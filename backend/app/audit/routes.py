from flask import Blueprint, jsonify, request
from sqlalchemy import func, select

from ..auth.services import require
from ..common import parse_date_range, query_int
from ..extensions import db
from .models import AuditLog

bp = Blueprint("audit", __name__, url_prefix="/api/audit")


@bp.get("")
@require("audit.view")
def list_audit():
    limit = query_int("limit", default=50, minimum=1, maximum=500)
    offset = query_int("offset", default=0, minimum=0)
    query = select(AuditLog)
    if action := request.args.get("action"):
        query = query.where(AuditLog.action == action)
    if username := request.args.get("username"):
        query = query.where(AuditLog.username == username.strip().lower())
    if entity_type := request.args.get("entity_type"):
        query = query.where(AuditLog.entity_type == entity_type)
    start, end = parse_date_range()
    if start:
        query = query.where(AuditLog.created_at >= start)
    if end:
        query = query.where(AuditLog.created_at < end)
    total = db.session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.session.execute(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).scalars().all()
    actions = db.session.execute(select(AuditLog.action).distinct().order_by(AuditLog.action)).scalars().all()
    return jsonify({"items": [r.to_dict() for r in rows], "total": total, "limit": limit,
                    "offset": offset, "actions": actions})
