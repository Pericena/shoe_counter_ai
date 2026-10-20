from sqlalchemy import CheckConstraint

from ..common import iso, utcnow
from ..extensions import db

ORDER_STATUSES = ("creado", "pago_confirmado", "preparado", "enviado", "entregado", "cancelado", "devuelto")
# Transiciones permitidas. Cancelar repone stock; "devuelto" lo repone como devolución de cliente.
ORDER_TRANSITIONS = {
    "creado": {"pago_confirmado", "cancelado"},
    "pago_confirmado": {"preparado", "cancelado"},
    "preparado": {"enviado", "cancelado"},
    "enviado": {"entregado"},
    "entregado": {"devuelto"},
    "cancelado": set(),
    "devuelto": set(),
}
ORDER_STATUS_LABELS = {
    "creado": "Pedido creado (pendiente de pago)",
    "pago_confirmado": "Pago confirmado",
    "preparado": "Preparado",
    "enviado": "Enviado",
    "entregado": "Entregado",
    "cancelado": "Cancelado",
    "devuelto": "Devuelto",
}


class Order(db.Model):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(f"status IN {ORDER_STATUSES}", name="status_valid"),
        CheckConstraint("total_amount >= 0", name="total_non_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default="creado", index=True)
    customer_name = db.Column(db.String(150), nullable=False)
    customer_email = db.Column(db.String(150), nullable=False, index=True)
    customer_phone = db.Column(db.String(50))
    shipping_address = db.Column(db.Text)
    notes = db.Column(db.Text)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_reference = db.Column(db.String(100))  # registrada a mano por el personal; no hay cobro en línea
    # "reserva": reserva al crear y descuenta al enviar. "descuento": pedidos antiguos que descontaban al crearse.
    stock_mode = db.Column(db.String(10), nullable=False, default="reserva", server_default="descuento")
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="RESTRICT"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id")
    history = db.relationship("OrderStatusHistory", back_populates="order", cascade="all, delete-orphan",
                              order_by="OrderStatusHistory.id")

    def to_dict(self, private=True):
        data = {
            "code": self.code,
            "status": self.status,
            "status_label": ORDER_STATUS_LABELS[self.status],
            "total_amount": str(self.total_amount),
            "items": [i.to_dict() for i in self.items],
            "history": [h.to_dict(private) for h in self.history],
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }
        if private:
            data.update({
                "id": self.id,
                "customer_name": self.customer_name,
                "customer_email": self.customer_email,
                "customer_phone": self.customer_phone,
                "shipping_address": self.shipping_address,
                "notes": self.notes,
                "payment_reference": self.payment_reference,
                "allowed_transitions": sorted(ORDER_TRANSITIONS[self.status]),
                "stock_mode": self.stock_mode,
            })
        return data


class OrderItem(db.Model):
    """Copia de los datos de la variante al momento del pedido (precio y descripción)."""

    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="price_non_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False, index=True)
    sku = db.Column(db.String(60), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    size = db.Column(db.String(20), nullable=False)
    color = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    # Costo de la variante al crear el pedido (margen histórico correcto aunque el costo cambie).
    unit_cost = db.Column(db.Numeric(12, 2))

    order = db.relationship("Order", back_populates="items")

    def to_dict(self):
        return {"variant_id": self.variant_id, "sku": self.sku, "description": self.description,
                "size": self.size, "color": self.color, "quantity": self.quantity,
                "unit_price": str(self.unit_price), "line_total": str(self.line_total),
                "unit_cost": str(self.unit_cost) if self.unit_cost is not None else None}


class OrderStatusHistory(db.Model):
    __tablename__ = "order_status_history"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    order = db.relationship("Order", back_populates="history")
    user = db.relationship("User")

    def to_dict(self, private=True):
        data = {"from_status": self.from_status, "to_status": self.to_status,
                "to_label": ORDER_STATUS_LABELS[self.to_status], "created_at": iso(self.created_at)}
        if private:
            data.update({"user": self.user.username if self.user else None, "note": self.note})
        return data
