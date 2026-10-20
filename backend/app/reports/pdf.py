"""Informes PDF con ReportLab. Solo contienen datos calculados de la base de datos."""
import io
from datetime import datetime, timezone

from flask import g, request
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..extensions import db
from . import queries

HEADER_BG = colors.HexColor("#1f3a5f")


def _doc(title, landscape_mode=False):
    buffer = io.BytesIO()
    size = landscape(A4) if landscape_mode else A4
    doc = SimpleDocTemplate(buffer, pagesize=size, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=title, author="Shoe Counter AI")
    return buffer, doc


def _meta(styles, title):
    user = getattr(g, "user", None)
    filters = ", ".join(f"{k}={v}" for k, v in request.args.items()) or "sin filtros"
    return [
        Paragraph(title, styles["Title"]),
        Paragraph(f"Generado: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · Usuario: "
                  f"{user.username if user else '-'} · Filtros: {filters}", styles["Normal"]),
        Spacer(1, 0.4 * cm),
    ]


def _table(data, widths=None):
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d2dc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f9")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def inventory_report():
    from ..inventory.routes import stock_item, stock_query

    styles = getSampleStyleSheet()
    rows = db.session.execute(stock_query()).scalars().all()
    summary = queries.inventory_summary()
    buffer, doc = _doc("Informe de inventario", landscape_mode=True)
    story = _meta(styles, "Informe de inventario")
    story.append(Paragraph(
        f"Productos: {summary['products']} · Variantes: {summary['variants']} · Pares: {summary['pairs']} · "
        f"Valor a costo: {summary['inventory_value_at_cost']} · Stock bajo: {summary['low']} · "
        f"Agotados: {summary['out']}", styles["Normal"]))
    if summary["variants_with_stock_without_cost"]:
        story.append(Paragraph(f"Atención: {summary['variants_with_stock_without_cost']} variantes con stock no "
                               "tienen costo; el valor del inventario está incompleto.", styles["Normal"]))
    story.append(Spacer(1, 0.3 * cm))
    data = [["SKU", "Marca", "Modelo", "Categoría", "Talla", "Color", "Pares", "Mín.", "Estado", "Costo", "Valor"]]
    for v in rows:
        item = stock_item(v)
        data.append([item["sku"], item["brand"], item["model_name"][:30], item["category"] or "-", item["size"],
                     item["color"], item["stock_quantity"], item["min_stock"], item["stock_state"],
                     item["cost"] or "-", item["inventory_value"] or "-"])
    story.append(_table(data))
    doc.build(story)
    return buffer.getvalue(), len(rows)


def trade_report():
    styles = getSampleStyleSheet()
    synthesis = queries.trade_synthesis()
    if not synthesis.get("available"):
        return b"", 0
    summary = queries.trade_summary(top=10)
    buffer, doc = _doc("Síntesis ejecutiva — comercio de calzado")
    story = _meta(styles, "Síntesis ejecutiva — comercio exterior de calzado")
    story.append(Paragraph("Hallazgos principales", styles["Heading2"]))
    for text in synthesis["findings"]:
        story.append(Paragraph(f"• {text}", styles["Normal"]))
    story.append(Paragraph("Limitaciones de los datos", styles["Heading2"]))
    for text in synthesis["limitations"]:
        story.append(Paragraph(f"• {text}", styles["Normal"]))
    story.append(Paragraph("Pregunta estratégica", styles["Heading2"]))
    story.append(Paragraph(synthesis["strategic_question"], styles["Normal"]))
    story.append(Paragraph("Recomendación", styles["Heading2"]))
    story.append(Paragraph(synthesis["recommendation"], styles["Normal"]))
    story.append(Paragraph("Valor y cantidad por año y flujo", styles["Heading2"]))
    data = [["Año", "Flujo", "Valor USD", "Pares", "Filas"]]
    for r in summary["by_year_flow"]:
        data.append([r["year"], r["flow"], f"{r['value_usd']:,.0f}", f"{r['quantity_pairs']:,.0f}", r["rows"]])
    story.append(_table(data))
    story.append(Paragraph("Principales socios (por valor USD)", styles["Heading2"]))
    data = [["Socio", "Flujo", "Valor USD", "Pares"]]
    for r in summary["top_partners"]:
        data.append([r["partner"], r["flow"], f"{r['value_usd']:,.0f}", f"{r['quantity_pairs']:,.0f}"])
    story.append(_table(data))
    story.append(Paragraph("Valor aproximado por par (USD) — solo filas con valor y cantidad > 0, sin agregados",
                           styles["Heading2"]))
    data = [["Año", "Flujo", "USD por par", "Pares usados"]]
    for r in summary["value_per_pair_by_year"]:
        data.append([r["year"], r["flow"], f"{r['value_per_pair']:.2f}", f"{r['pairs_used']:,.0f}"])
    story.append(_table(data))
    doc.build(story)
    return buffer.getvalue(), summary["records"]
