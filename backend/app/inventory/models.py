from sqlalchemy import CheckConstraint

from ..common import iso, utcnow
from ..extensions import db

# Tipo de movimiento -> signo permitido de la cantidad (+1 entra, -1 sale, 0 ambos).
MOVEMENT_TYPES = {
    "entrada_compra": 1,
    "salida_venta": -1,
    "devolucion_cliente": 1,
    "devolucion_proveedor": -1,
    "ajuste": 0,
    "conteo_fisico": 0,
    "salida_pedido": -1,       # pedido de la tienda online (reserva al crear el pedido)
    "cancelacion_pedido": 1,   # reposición al cancelar un pedido
}
# Tipos que solo genera el sistema (tienda online); no se registran a mano.
SYSTEM_MOVEMENT_TYPES = {"salida_pedido", "cancelacion_pedido"}
# Tipos permitidos con el permiso de venta (operador); el resto exige inventory.move.
SALES_MOVEMENT_TYPES = {"salida_venta", "devolucion_cliente"}
OUTBOUND_SALES_TYPES = ("salida_venta", "salida_pedido")


class InventoryMovement(db.Model):
    """Libro mayor de inventario. Es la fuente auditable del stock: nunca se edita ni borra."""

    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity <> 0", name="quantity_not_zero"),
        CheckConstraint("balance_after >= 0", name="balance_non_negative"),
        CheckConstraint(f"movement_type IN {tuple(MOVEMENT_TYPES)}", name="type_valid"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost_non_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(
        db.Integer, db.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    movement_type = db.Column(db.String(30), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)  # con signo: + entra, - sale (pares)
    balance_after = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2))
    reason = db.Column(db.Text)
    reference = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    count_id = db.Column(db.Integer, db.ForeignKey("ai_counts.id", ondelete="SET NULL"), index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="SET NULL"), index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    variant = db.relationship("ProductVariant")
    user = db.relationship("User")

    def to_dict(self):
        variant = self.variant
        return {
            "id": self.id,
            "variant_id": self.variant_id,
            "sku": variant.sku if variant else None,
            "product": f"{variant.product.brand.name} {variant.product.model_name}" if variant else None,
            "size": variant.size if variant else None,
            "color": variant.color if variant else None,
            "movement_type": self.movement_type,
            "quantity": self.quantity,
            "balance_after": self.balance_after,
            "unit_cost": str(self.unit_cost) if self.unit_cost is not None else None,
            "reason": self.reason,
            "reference": self.reference,
            "user": self.user.username if self.user else None,
            "count_id": self.count_id,
            "order_id": self.order_id,
            "created_at": iso(self.created_at),
        }
