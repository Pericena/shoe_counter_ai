from flask import Blueprint, Response, jsonify, request
from sqlalchemy import func, select

from ..audit.services import audit
from ..auth.services import require
from ..common import ApiError, query_int
from ..extensions import db
from . import pdf, queries

bp = Blueprint("reports", __name__, url_prefix="/api")


@bp.get("/reports/overview")
@require("dashboard.view")
def overview():
    return jsonify(queries.overview())


@bp.get("/reports/movements")
@require("reports.view")
def movements():
    return jsonify(queries.movement_series(request.args.get("group", "day")))


@bp.get("/reports/rotation")
@require("reports.view")
def rotation():
    return jsonify(queries.rotation(limit=query_int("limit", default=10, minimum=1, maximum=100)))


@bp.get("/reports/adjustments")
@require("reports.view")
def adjustments():
    return jsonify(queries.adjustments())


@bp.get("/reports/counts")
@require("reports.view")
def counts():
    return jsonify(queries.counts_summary())


@bp.get("/trade/records")
@require("reports.view")
def trade_records():
    limit = query_int("limit", default=50, minimum=1, maximum=500)
    offset = query_int("offset", default=0, minimum=0)
    query = queries.trade_query()
    total = db.session.execute(select(func.count()).select_from(query.order_by(None).subquery())).scalar_one()
    rows = db.session.execute(query.limit(limit).offset(offset)).scalars().all()
    return jsonify({"items": [r.to_dict() for r in rows], "total": total, "limit": limit, "offset": offset})


@bp.get("/trade/summary")
@require("reports.view")
def trade_summary():
    return jsonify(queries.trade_summary(top=query_int("top", default=10, minimum=1, maximum=50),
                                         metric=request.args.get("metric", "value_usd")))


@bp.get("/trade/options")
@require("reports.view")
def trade_options():
    return jsonify(queries.trade_filter_options())


@bp.get("/trade/synthesis")
@require("reports.view")
def trade_synthesis():
    return jsonify(queries.trade_synthesis())


@bp.get("/reports/<name>.pdf")
@require("reports.view", "exports.run")
def report_pdf(name):
    builders = {"inventario": pdf.inventory_report, "comercio": pdf.trade_report}
    if name not in builders:
        raise ApiError("Informe no disponible.", 404)
    content, rows = builders[name]()
    if rows == 0:
        raise ApiError("No hay datos para generar este informe con los filtros indicados.", 404)
    from ..imports.models import DataExport
    from flask import g
    db.session.add(DataExport(user_id=g.user.id, dataset=f"informe_{name}", file_format="pdf",
                              filters=dict(request.args), row_count=rows))
    audit("informe_pdf", "report", name, {"filtros": dict(request.args), "filas": rows})
    db.session.commit()
    return Response(content, mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=informe_{name}.pdf"})
