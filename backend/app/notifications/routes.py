from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, json_body, query_int, utcnow
from ..extensions import db
from .models import PRIORITIES, Notification
from .services import scan

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


@bp.get("")
@require("notifications.view")
def list_notifications():
    if request.args.get("scan") == "1":
        scan()
    limit = query_int("limit", default=50, minimum=1, maximum=200)
    query = select(Notification)
    status = request.args.get("status", "pendientes")
    if status == "pendientes":
        query = query.where(Notification.status != "resuelta")
    elif status in ("abierta", "leida", "resuelta"):
        query = query.where(Notification.status == status)
    if priority := request.args.get("priority"):
        if priority not in PRIORITIES:
            raise ApiError("Prioridad no válida.")
        query = query.where(Notification.priority == priority)
    if kind := request.args.get("kind"):
        query = query.where(Notification.kind == kind)
    order = {"alta": 0, "media": 1, "baja": 2}
    rows = db.session.execute(query.order_by(Notification.id.desc()).limit(limit)).scalars().all()
    rows.sort(key=lambda n: (n.status == "leida", order[n.priority], -n.id))
    counts = dict(db.session.execute(select(Notification.priority, func.count()).where(
        Notification.status == "abierta").group_by(Notification.priority)).all())
    return jsonify({"items": [n.to_dict() for n in rows], "unread": counts,
                    "unread_total": sum(counts.values())})


@bp.post("/scan")
@require("notifications.view")
def run_scan():
    return jsonify(scan())


@bp.post("/<int:note_id>/read")
@require("notifications.view")
def mark_read(note_id):
    note = db.session.get(Notification, note_id)
    if note is None:
        raise ApiError("La notificación no existe.", 404)
    if note.status == "abierta":
        note.status, note.read_at, note.read_by = "leida", utcnow(), g.user.id
    db.session.commit()
    return jsonify(note.to_dict())


@bp.post("/read-all")
@require("notifications.view")
def mark_all_read():
    priority = json_body().get("priority")
    query = select(Notification).where(Notification.status == "abierta")
    if priority:
        query = query.where(Notification.priority == priority)
    count = 0
    for note in db.session.execute(query).scalars():
        note.status, note.read_at, note.read_by = "leida", utcnow(), g.user.id
        count += 1
    audit("notificaciones_leidas", "notification", None, {"cantidad": count})
    db.session.commit()
    return jsonify({"updated": count})
