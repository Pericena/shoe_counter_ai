"""Datos analíticos de solo lectura para Power BI (u otra herramienta de BI).

Dos vías (ver docs/11-power-bi.md):
  1. API protegida: GET /api/bi/datasets/<conjunto>.csv|json con sesión (permiso bi.view) o con un
     token de lectura (cabecera Authorization: Bearer …). Solo ejecuta SELECT.
  2. Vistas SQL en el esquema `analytics` de PostgreSQL + un usuario de base de datos con permiso
     exclusivamente de lectura sobre ese esquema (`flask --app run bi create-reader`).
Ninguna de las dos puede modificar existencias.
"""
import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select

from ..common import iso, utcnow
from ..extensions import db


class BiToken(db.Model):
    __tablename__ = "bi_tokens"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    prefix = db.Column(db.String(12), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_used_at = db.Column(db.DateTime(timezone=True))
    revoked_at = db.Column(db.DateTime(timezone=True))

    def to_dict(self):
        return {"id": self.id, "name": self.name, "prefix": self.prefix, "created_at": iso(self.created_at),
                "last_used_at": iso(self.last_used_at), "revoked_at": iso(self.revoked_at)}


def new_token():
    token = "bi_" + secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest(), token[:10]


def check_token(token):
    if not token:
        return None
    row = db.session.execute(select(BiToken).where(
        BiToken.token_hash == hashlib.sha256(token.encode()).hexdigest(), BiToken.revoked_at.is_(None))).scalar_one_or_none()
    if row is not None:
        row.last_used_at = utcnow()
    return row


def _num(v):
    return float(v) if v is not None else None


def ds_productos():
    from ..products.models import Product
    for p in db.session.execute(select(Product).order_by(Product.id)).scalars():
        yield {"producto_id": p.id, "codigo": p.code, "nombre": p.name or f"{p.brand.name} {p.model_name}",
               "marca": p.brand.name, "modelo": p.model_name, "categoria": p.category.name if p.category else None,
               "subcategoria": p.subcategory, "tipo": p.footwear_type, "segmento": p.segment, "material": p.material,
               "temporada": p.season, "coleccion": p.collection, "proveedor_id": p.supplier_id, "estado": p.status,
               "publicado": p.is_published, "tiene_foto": bool(p.images), "creado": iso(p.created_at)}


def ds_variantes():
    from ..products.models import ProductVariant
    for v in db.session.execute(select(ProductVariant).order_by(ProductVariant.id)).scalars():
        yield {"variante_id": v.id, "producto_id": v.product_id, "sku": v.sku, "codigo_barras": v.barcode,
               "talla": v.size, "color": v.color, "costo": _num(v.cost), "precio": _num(v.price),
               "stock_minimo": v.min_stock, "fisico": v.stock_quantity, "reservado": v.reserved_quantity,
               "disponible": v.stock_quantity - v.reserved_quantity, "estado": v.status}


def ds_ubicaciones():
    from ..inventory.models import Location
    for loc in db.session.execute(select(Location).order_by(Location.id)).scalars():
        yield {"ubicacion_id": loc.id, "codigo": loc.code, "nombre": loc.name, "tipo": loc.kind, "activa": loc.is_active}


def ds_proveedores():
    from ..products.models import Supplier
    for s in db.session.execute(select(Supplier).order_by(Supplier.id)).scalars():
        yield {"proveedor_id": s.id, "nombre": s.name, "plazo_entrega_dias": s.lead_time_days}


def ds_stock_ubicacion():
    from ..inventory.models import StockLevel
    for lv in db.session.execute(select(StockLevel)).scalars():
        yield {"variante_id": lv.variant_id, "ubicacion_id": lv.location_id, "estante": lv.bin, "fisico": lv.on_hand,
               "reservado": lv.reserved, "disponible": lv.on_hand - lv.reserved}


def ds_movimientos():
    from ..inventory.models import InventoryMovement
    for m in db.session.execute(select(InventoryMovement).order_by(InventoryMovement.id)).scalars():
        yield {"movimiento_id": m.id, "fecha": iso(m.created_at), "dia": m.created_at.date().isoformat(),
               "variante_id": m.variant_id, "ubicacion_id": m.location_id, "tipo": m.movement_type, "canal": m.channel,
               "cantidad": m.quantity, "reservado_delta": m.reserved_delta, "stock_antes": m.stock_before,
               "stock_despues": m.balance_after, "costo_unitario": _num(m.unit_cost), "referencia": m.reference,
               "usuario": m.user.username if m.user else None}


def ds_ventas():
    from ..sales.models import Sale
    from ..shop.models import Order
    for sale in db.session.execute(select(Sale).order_by(Sale.id)).scalars():
        for item in sale.items:
            yield {"documento": sale.number, "fecha": iso(sale.created_at), "dia": sale.created_at.date().isoformat(),
                   "canal": sale.channel, "ubicacion_id": sale.location_id, "variante_id": item.variant_id,
                   "cantidad": item.quantity, "devuelto": item.returned_quantity, "precio_unitario": _num(item.unit_price),
                   "descuento": _num(item.discount), "ingreso": _num(item.line_total), "costo_unitario": _num(item.unit_cost),
                   "metodo_pago": sale.payment_method}
    for order in db.session.execute(select(Order).order_by(Order.id)).scalars():
        if order.status in ("creado", "cancelado"):
            continue
        for item in order.items:
            yield {"documento": order.code, "fecha": iso(order.created_at), "dia": order.created_at.date().isoformat(),
                   "canal": "online", "ubicacion_id": order.location_id, "variante_id": item.variant_id,
                   "cantidad": item.quantity, "devuelto": item.quantity if order.status == "devuelto" else 0,
                   "precio_unitario": _num(item.unit_price), "descuento": 0.0, "ingreso": _num(item.line_total),
                   "costo_unitario": _num(item.unit_cost), "metodo_pago": "online"}


def ds_compras():
    from ..purchasing.models import PurchaseOrder
    for po in db.session.execute(select(PurchaseOrder).order_by(PurchaseOrder.id)).scalars():
        for line in po.lines:
            yield {"orden": po.number, "estado": po.status, "proveedor_id": po.supplier_id, "ubicacion_id": po.location_id,
                   "creada": iso(po.created_at), "prevista": po.expected_date.isoformat() if po.expected_date else None,
                   "recibida": iso(po.received_at), "variante_id": line.variant_id, "pedido": line.quantity_ordered,
                   "recibido": line.quantity_received, "costo_unitario": _num(line.unit_cost)}


def ds_conteos():
    from ..ai.models import AICount
    for c in db.session.execute(select(AICount).order_by(AICount.id)).scalars():
        yield {"conteo_id": c.id, "fecha": iso(c.created_at), "estado": c.status, "modelo": c.model_version,
               "detectados": c.detected_count, "confirmados": c.confirmed_shoes, "pares": c.pairs_complete,
               "sueltos": c.loose_shoes, "variante_id": c.variant_id or c.identified_variant_id,
               "stock_antes": c.stock_before, "contado": c.applied_pairs}


def ds_calendario():
    from ..inventory.models import InventoryMovement
    first = db.session.execute(select(InventoryMovement.created_at).order_by(InventoryMovement.created_at).limit(1)).scalar()
    start = (first or utcnow()).date()
    end = utcnow().date()
    day = start
    while day <= end:
        yield {"dia": day.isoformat(), "anio": day.year, "mes": day.month, "semana_iso": day.isocalendar()[1],
               "dia_semana": day.isoweekday(), "trimestre": (day.month - 1) // 3 + 1}
        day += timedelta(days=1)


DATASETS = {
    "productos": ds_productos, "variantes": ds_variantes, "ubicaciones": ds_ubicaciones, "proveedores": ds_proveedores,
    "stock_ubicacion": ds_stock_ubicacion, "movimientos": ds_movimientos, "ventas": ds_ventas, "compras": ds_compras,
    "conteos": ds_conteos, "calendario": ds_calendario,
}

# Vistas equivalentes para conexión directa de Power BI a PostgreSQL (solo lectura).
PG_VIEWS = {
    "dim_producto": """SELECT p.id AS producto_id, p.code AS codigo, COALESCE(p.name, b.name || ' ' || p.model_name) AS nombre,
        b.name AS marca, p.model_name AS modelo, c.name AS categoria, p.subcategory AS subcategoria,
        p.footwear_type AS tipo, p.segment AS segmento, p.material, p.season AS temporada, p.collection AS coleccion,
        p.supplier_id AS proveedor_id, p.status AS estado, p.is_published AS publicado, p.created_at AS creado
        FROM products p JOIN brands b ON b.id = p.brand_id LEFT JOIN categories c ON c.id = p.category_id""",
    "dim_variante": """SELECT v.id AS variante_id, v.product_id AS producto_id, v.sku, v.barcode AS codigo_barras,
        v.size AS talla, v.color, v.cost AS costo, v.price AS precio, v.min_stock AS stock_minimo, v.status AS estado
        FROM product_variants v""",
    "dim_ubicacion": "SELECT id AS ubicacion_id, code AS codigo, name AS nombre, kind AS tipo, is_active AS activa FROM locations",
    "dim_proveedor": "SELECT id AS proveedor_id, name AS nombre, lead_time_days AS plazo_entrega_dias FROM suppliers",
    "dim_fecha": """SELECT d::date AS dia, EXTRACT(YEAR FROM d)::int AS anio, EXTRACT(MONTH FROM d)::int AS mes,
        EXTRACT(WEEK FROM d)::int AS semana_iso, EXTRACT(ISODOW FROM d)::int AS dia_semana,
        EXTRACT(QUARTER FROM d)::int AS trimestre
        FROM generate_series(COALESCE((SELECT MIN(created_at) FROM inventory_movements), now())::date,
                             now()::date, interval '1 day') AS d""",
    "fact_stock": """SELECT variant_id AS variante_id, location_id AS ubicacion_id, bin AS estante, on_hand AS fisico,
        reserved AS reservado, on_hand - reserved AS disponible FROM stock_levels""",
    "fact_movimientos": """SELECT m.id AS movimiento_id, m.created_at AS fecha, m.created_at::date AS dia, m.variant_id AS variante_id,
        m.location_id AS ubicacion_id, m.movement_type AS tipo, m.channel AS canal, m.quantity AS cantidad,
        m.reserved_delta AS reservado_delta, m.stock_before AS stock_antes, m.balance_after AS stock_despues,
        m.unit_cost AS costo_unitario, m.reference AS referencia FROM inventory_movements m""",
    "fact_ventas": """SELECT s.number AS documento, s.created_at AS fecha, s.created_at::date AS dia, s.channel AS canal,
        s.location_id AS ubicacion_id, i.variant_id AS variante_id, i.quantity AS cantidad, i.returned_quantity AS devuelto,
        i.unit_price AS precio_unitario, i.discount AS descuento, i.line_total AS ingreso, i.unit_cost AS costo_unitario
        FROM sales s JOIN sale_items i ON i.sale_id = s.id
        UNION ALL
        SELECT o.code, o.created_at, o.created_at::date, 'online', o.location_id, i.variant_id, i.quantity,
        CASE WHEN o.status = 'devuelto' THEN i.quantity ELSE 0 END, i.unit_price, 0, i.line_total, i.unit_cost
        FROM orders o JOIN order_items i ON i.order_id = o.id WHERE o.status NOT IN ('creado', 'cancelado')""",
    "fact_compras": """SELECT po.number AS orden, po.status AS estado, po.supplier_id AS proveedor_id, po.location_id AS ubicacion_id,
        po.created_at AS creada, po.expected_date AS prevista, po.received_at AS recibida, l.variant_id AS variante_id,
        l.quantity_ordered AS pedido, l.quantity_received AS recibido, l.unit_cost AS costo_unitario
        FROM purchase_orders po JOIN purchase_order_lines l ON l.order_id = po.id""",
    "fact_conteos": """SELECT id AS conteo_id, created_at AS fecha, status AS estado, model_version AS modelo,
        detected_count AS detectados, confirmed_shoes AS confirmados, pairs_complete AS pares, loose_shoes AS sueltos,
        COALESCE(variant_id, identified_variant_id) AS variante_id, stock_before AS stock_antes, applied_pairs AS contado
        FROM ai_counts""",
}
