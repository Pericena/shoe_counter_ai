from sqlalchemy import CheckConstraint, Index, text

from ..common import iso, utcnow
from ..extensions import db

PAYMENT_METHODS = ("efectivo", "tarjeta", "qr", "transferencia", "otro")
RETURN_CONDITIONS = ("reintegrable", "danado", "revision")


class Sale(db.Model):
    """Venta (ticket) del punto de venta o recibida de una integración. Descuenta stock una sola vez."""

    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("total >= 0", name="total_non_negative"),
        CheckConstraint(f"payment_method IN {PAYMENT_METHODS}", name="payment_valid"),
        Index("uq_sale_channel_external_ref", "channel", "external_ref", unique=True,
              postgresql_where=text("external_ref IS NOT NULL"), sqlite_where=text("external_ref IS NOT NULL")),
    )

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), nullable=False, unique=True)
    channel = db.Column(db.String(20), nullable=False, default="tpv")
    external_ref = db.Column(db.String(150))
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    customer_name = db.Column(db.String(150))
    payment_method = db.Column(db.String(20), nullable=False, default="efectivo")
    payment_reference = db.Column(db.String(100))
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    discount_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    items = db.relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan", order_by="SaleItem.id")
    returns = db.relationship("SaleReturn", back_populates="sale", order_by="SaleReturn.id")
    location = db.relationship("Location")
    user = db.relationship("User")

    def to_dict(self, detail=True):
        data = {
            "id": self.id, "number": self.number, "channel": self.channel, "external_ref": self.external_ref,
            "location": self.location.name if self.location else None, "location_id": self.location_id,
            "user": self.user.username if self.user else None, "customer_name": self.customer_name,
            "payment_method": self.payment_method, "payment_reference": self.payment_reference,
            "subtotal": str(self.subtotal), "discount_total": str(self.discount_total), "total": str(self.total),
            "units": sum(i.quantity for i in self.items),
            "returned_units": sum(i.returned_quantity for i in self.items),
            "created_at": iso(self.created_at),
        }
        if detail:
            data["items"] = [i.to_dict() for i in self.items]
            data["returns"] = [r.to_dict() for r in self.returns]
        return data


class SaleItem(db.Model):
    __tablename__ = "sale_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("returned_quantity >= 0 AND returned_quantity <= quantity", name="returned_valid"),
        CheckConstraint("unit_price >= 0 AND discount >= 0", name="amounts_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    discount = db.Column(db.Numeric(12, 2), nullable=False, default=0)   # descuento total de la línea
    unit_cost = db.Column(db.Numeric(12, 2))                             # costo al momento de vender (para el margen)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    returned_quantity = db.Column(db.Integer, nullable=False, default=0)

    sale = db.relationship("Sale", back_populates="items")
    variant = db.relationship("ProductVariant")

    def to_dict(self):
        v = self.variant
        return {"id": self.id, "variant_id": self.variant_id, "sku": v.sku if v else None,
                "description": f"{v.product.brand.name} {v.product.model_name} · T{v.size} {v.color}" if v else None,
                "quantity": self.quantity, "unit_price": str(self.unit_price), "discount": str(self.discount),
                "unit_cost": str(self.unit_cost) if self.unit_cost is not None else None,
                "line_total": str(self.line_total), "returned_quantity": self.returned_quantity}


class SaleReturn(db.Model):
    __tablename__ = "sale_returns"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), nullable=False, unique=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    reason = db.Column(db.Text, nullable=False)
    refund_amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    sale = db.relationship("Sale", back_populates="returns")
    user = db.relationship("User")
    items = db.relationship("ReturnItem", back_populates="sale_return", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "number": self.number, "reason": self.reason, "refund_amount": str(self.refund_amount),
                "user": self.user.username if self.user else None, "created_at": iso(self.created_at),
                "items": [i.to_dict() for i in self.items]}


class ReturnItem(db.Model):
    """Inspección: reintegrable → vuelve al stock; dañado → no vuelve; revisión → pendiente de decidir."""

    __tablename__ = "return_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(f"condition IN {RETURN_CONDITIONS}", name="condition_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    return_id = db.Column(db.Integer, db.ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    sale_item_id = db.Column(db.Integer, db.ForeignKey("sale_items.id", ondelete="RESTRICT"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    condition = db.Column(db.String(15), nullable=False)
    resolution = db.Column(db.String(15))  # para "revision": reintegrable | danado
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at = db.Column(db.DateTime(timezone=True))

    sale_return = db.relationship("SaleReturn", back_populates="items")
    sale_item = db.relationship("SaleItem")

    def to_dict(self):
        return {"id": self.id, "sale_item_id": self.sale_item_id, "sku": self.sale_item.variant.sku if self.sale_item else None,
                "quantity": self.quantity, "condition": self.condition, "resolution": self.resolution,
                "pending": self.condition == "revision" and self.resolution is None, "resolved_at": iso(self.resolved_at)}
