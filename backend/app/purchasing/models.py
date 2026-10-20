from sqlalchemy import CheckConstraint

from ..common import iso, utcnow
from ..extensions import db

PO_STATUSES = ("borrador", "aprobada", "solicitada", "recibida_parcial", "recibida", "cancelada")
PO_TRANSITIONS = {
    "borrador": {"aprobada", "cancelada"},
    "aprobada": {"solicitada", "cancelada"},
    "solicitada": {"cancelada"},          # la recepción cambia a recibida_parcial / recibida
    "recibida_parcial": {"cancelada"},
    "recibida": set(),
    "cancelada": set(),
}
OPEN_PO_STATUSES = ("aprobada", "solicitada", "recibida_parcial")  # cuentan como "en tránsito / pedido"
REC_STATUSES = ("pendiente", "revisada", "aprobada", "solicitada", "recibida", "descartada")


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"
    __table_args__ = (CheckConstraint(f"status IN {PO_STATUSES}", name="status_valid"),)

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), nullable=False, unique=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="borrador", index=True)
    expected_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))
    ordered_at = db.Column(db.DateTime(timezone=True))
    received_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    supplier = db.relationship("Supplier")
    location = db.relationship("Location")
    lines = db.relationship("PurchaseOrderLine", back_populates="order", cascade="all, delete-orphan",
                            order_by="PurchaseOrderLine.id")
    creator = db.relationship("User", foreign_keys=[created_by])
    approver = db.relationship("User", foreign_keys=[approved_by])

    @property
    def total(self):
        return sum((line.unit_cost or 0) * line.quantity_ordered for line in self.lines)

    def to_dict(self, detail=True):
        data = {
            "id": self.id, "number": self.number, "status": self.status,
            "supplier_id": self.supplier_id, "supplier": self.supplier.name if self.supplier else None,
            "lead_time_days": self.supplier.lead_time_days if self.supplier else None,
            "location_id": self.location_id, "location": self.location.name if self.location else None,
            "expected_date": self.expected_date.isoformat() if self.expected_date else None, "notes": self.notes,
            "created_by": self.creator.username if self.creator else None,
            "approved_by": self.approver.username if self.approver else None, "approved_at": iso(self.approved_at),
            "ordered_at": iso(self.ordered_at), "received_at": iso(self.received_at), "created_at": iso(self.created_at),
            "total": str(self.total), "units_ordered": sum(line.quantity_ordered for line in self.lines),
            "units_received": sum(line.quantity_received for line in self.lines),
            "allowed_transitions": sorted(PO_TRANSITIONS[self.status]),
        }
        if detail:
            data["lines"] = [line.to_dict() for line in self.lines]
        return data


class PurchaseOrderLine(db.Model):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        CheckConstraint("quantity_ordered > 0", name="ordered_positive"),
        CheckConstraint("quantity_received >= 0 AND quantity_received <= quantity_ordered", name="received_valid"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="cost_non_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity_ordered = db.Column(db.Integer, nullable=False)
    quantity_received = db.Column(db.Integer, nullable=False, default=0)
    unit_cost = db.Column(db.Numeric(12, 2))

    order = db.relationship("PurchaseOrder", back_populates="lines")
    variant = db.relationship("ProductVariant")

    def to_dict(self):
        v = self.variant
        return {"id": self.id, "variant_id": self.variant_id, "sku": v.sku if v else None,
                "description": f"{v.product.brand.name} {v.product.model_name} · T{v.size} {v.color}" if v else None,
                "quantity_ordered": self.quantity_ordered, "quantity_received": self.quantity_received,
                "pending": self.quantity_ordered - self.quantity_received,
                "unit_cost": str(self.unit_cost) if self.unit_cost is not None else None}


class ReplenishmentRecommendation(db.Model):
    """Propuesta de reposición explicable: guarda todos los valores con los que se calculó."""

    __tablename__ = "replenishment_recommendations"
    __table_args__ = (CheckConstraint(f"status IN {REC_STATUSES}", name="status_valid"),)

    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"))
    computed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    history_days = db.Column(db.Integer, nullable=False)
    units_sold = db.Column(db.Integer, nullable=False)
    avg_daily_demand = db.Column(db.Numeric(10, 4), nullable=False)
    lead_time_days = db.Column(db.Integer, nullable=False)
    safety_stock = db.Column(db.Integer, nullable=False)
    reorder_point = db.Column(db.Integer, nullable=False)
    target_stock = db.Column(db.Integer, nullable=False)
    on_hand = db.Column(db.Integer, nullable=False)
    reserved = db.Column(db.Integer, nullable=False)
    on_order = db.Column(db.Integer, nullable=False)
    inventory_position = db.Column(db.Integer, nullable=False)
    suggested_qty = db.Column(db.Integer, nullable=False)
    priority = db.Column(db.String(10), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(15), nullable=False, default="pendiente", index=True)
    po_line_id = db.Column(db.Integer, db.ForeignKey("purchase_order_lines.id", ondelete="SET NULL"))
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at = db.Column(db.DateTime(timezone=True))

    variant = db.relationship("ProductVariant")
    location = db.relationship("Location")
    supplier = db.relationship("Supplier")
    reviewer = db.relationship("User")

    def to_dict(self):
        v = self.variant
        return {
            "id": self.id, "variant_id": self.variant_id, "sku": v.sku if v else None,
            "product": f"{v.product.brand.name} {v.product.model_name}" if v else None,
            "size": v.size if v else None, "color": v.color if v else None,
            "location": self.location.name if self.location else None, "location_id": self.location_id,
            "supplier": self.supplier.name if self.supplier else None, "supplier_id": self.supplier_id,
            "computed_at": iso(self.computed_at), "history_days": self.history_days, "units_sold": self.units_sold,
            "avg_daily_demand": float(self.avg_daily_demand), "lead_time_days": self.lead_time_days,
            "safety_stock": self.safety_stock, "reorder_point": self.reorder_point, "target_stock": self.target_stock,
            "on_hand": self.on_hand, "reserved": self.reserved, "on_order": self.on_order,
            "inventory_position": self.inventory_position, "suggested_qty": self.suggested_qty,
            "priority": self.priority, "reason": self.reason, "status": self.status, "po_line_id": self.po_line_id,
            "reviewed_by": self.reviewer.username if self.reviewer else None, "reviewed_at": iso(self.reviewed_at),
        }
