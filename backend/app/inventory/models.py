from sqlalchemy import CheckConstraint, Index, text

from ..common import iso, utcnow
from ..extensions import db

# Tipo de movimiento -> signo de la cantidad FÍSICA (+1 entra, -1 sale, 0 ambos/no aplica).
MOVEMENT_TYPES = {
    "stock_inicial": 1,          # apertura documentada (importación o alta inicial)
    "entrada_compra": 1,         # compra / recepción de mercancía
    "salida_venta": -1,          # venta (TPV o manual)
    "devolucion_cliente": 1,     # devolución reintegrable al stock
    "devolucion_proveedor": -1,
    "transferencia_salida": -1,  # sale de una ubicación…
    "transferencia_entrada": 1,  # …y entra en otra (mismo documento)
    "ajuste": 0,                 # corrección autorizada con motivo
    "conteo_fisico": 0,          # diferencia de inventario físico
    "danado": -1,                # producto dañado (baja)
    "perdido": -1,               # producto perdido / robo (baja)
    "reserva": 0,                # reserva de un pedido: no mueve stock físico, sube el reservado
    "liberacion_reserva": 0,     # cancelación de un pedido: baja el reservado
    "salida_pedido": -1,         # entrega de un pedido online: consume la reserva
    "cancelacion_pedido": 1,     # (histórico) reposición de pedidos del modelo anterior sin reservas
}
# Tipos que solo genera el sistema (pedidos, transferencias, importación, TPV); no se registran a mano.
SYSTEM_MOVEMENT_TYPES = {"salida_pedido", "cancelacion_pedido", "reserva", "liberacion_reserva",
                         "transferencia_salida", "transferencia_entrada"}
# Tipos permitidos con el permiso de venta; el resto exige inventory.move.
SALES_MOVEMENT_TYPES = {"salida_venta", "devolucion_cliente"}
OUTBOUND_SALES_TYPES = ("salida_venta", "salida_pedido")
CHANNELS = ("tienda", "tpv", "online", "importacion", "ia", "compras", "sistema", "integracion")
LOCATION_KINDS = ("tienda", "almacen", "deposito")


class Location(db.Model):
    """Tienda, almacén o depósito. El stock se lleva por variante y ubicación."""

    __tablename__ = "locations"
    __table_args__ = (CheckConstraint(f"kind IN {LOCATION_KINDS}", name="kind_valid"),)

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="tienda")
    address = db.Column(db.String(300))
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self):
        return {"id": self.id, "code": self.code, "name": self.name, "kind": self.kind, "address": self.address,
                "is_default": self.is_default, "is_active": self.is_active}


class StockLevel(db.Model):
    """Existencias de una variante en una ubicación.

    físico (on_hand) = pares presentes · reservado = comprometido con pedidos · disponible = físico − reservado.
    Solo inventory.services lo modifica, siempre junto con un InventoryMovement.
    """

    __tablename__ = "stock_levels"
    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="on_hand_non_negative"),
        CheckConstraint("reserved >= 0", name="reserved_non_negative"),
        CheckConstraint("reserved <= on_hand", name="reserved_le_on_hand"),
    )

    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id", ondelete="RESTRICT"), primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="RESTRICT"), primary_key=True)
    on_hand = db.Column(db.Integer, nullable=False, default=0)
    reserved = db.Column(db.Integer, nullable=False, default=0)
    bin = db.Column(db.String(60))  # estante / pasillo / caja dentro de la ubicación
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    location = db.relationship("Location")
    variant = db.relationship("ProductVariant", back_populates="levels")

    @property
    def available(self):
        return self.on_hand - self.reserved

    def to_dict(self):
        return {"location_id": self.location_id, "location": self.location.name if self.location else None,
                "location_code": self.location.code if self.location else None, "bin": self.bin,
                "on_hand": self.on_hand, "reserved": self.reserved, "available": self.available}


class InventoryMovement(db.Model):
    """Libro mayor de inventario. Es la fuente auditable del stock: nunca se edita ni borra."""

    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity <> 0 OR reserved_delta <> 0", name="movement_not_empty"),
        CheckConstraint("balance_after >= 0", name="balance_non_negative"),
        CheckConstraint(f"movement_type IN {tuple(MOVEMENT_TYPES)}", name="type_valid"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost_non_negative"),
        CheckConstraint(f"channel IN {CHANNELS}", name="channel_valid"),
        # Idempotencia: un mismo evento externo (canal + referencia) solo puede registrarse una vez.
        Index("uq_movement_channel_external_ref", "channel", "external_ref", unique=True,
              postgresql_where=text("external_ref IS NOT NULL"), sqlite_where=text("external_ref IS NOT NULL")),
    )

    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(
        db.Integer, db.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True)
    counterpart_location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="RESTRICT"))
    movement_type = db.Column(db.String(30), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)        # Δ físico (pares), con signo
    reserved_delta = db.Column(db.Integer, nullable=False, default=0)  # Δ reservado (pares), con signo
    stock_before = db.Column(db.Integer, nullable=False, default=0)    # físico total de la variante antes
    balance_after = db.Column(db.Integer, nullable=False)              # físico total de la variante después
    location_balance_after = db.Column(db.Integer)                     # físico en la ubicación después
    unit_cost = db.Column(db.Numeric(12, 2))
    reason = db.Column(db.Text)
    reference = db.Column(db.String(100))                              # documento relacionado
    channel = db.Column(db.String(20), nullable=False, default="tienda")
    external_ref = db.Column(db.String(150))                           # referencia externa (idempotencia)
    evidence_file_id = db.Column(db.Integer, db.ForeignKey("stored_files.id", ondelete="SET NULL"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    count_id = db.Column(db.Integer, db.ForeignKey("ai_counts.id", ondelete="SET NULL"), index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="SET NULL"), index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    variant = db.relationship("ProductVariant")
    user = db.relationship("User")
    location = db.relationship("Location", foreign_keys=[location_id])
    counterpart_location = db.relationship("Location", foreign_keys=[counterpart_location_id])

    def to_dict(self):
        variant = self.variant
        return {
            "id": self.id,
            "variant_id": self.variant_id,
            "sku": variant.sku if variant else None,
            "product": f"{variant.product.brand.name} {variant.product.model_name}" if variant else None,
            "size": variant.size if variant else None,
            "color": variant.color if variant else None,
            "location": self.location.name if self.location else None,
            "location_id": self.location_id,
            "counterpart_location": self.counterpart_location.name if self.counterpart_location else None,
            "movement_type": self.movement_type,
            "quantity": self.quantity,
            "reserved_delta": self.reserved_delta,
            "stock_before": self.stock_before,
            "balance_after": self.balance_after,
            "location_balance_after": self.location_balance_after,
            "unit_cost": str(self.unit_cost) if self.unit_cost is not None else None,
            "reason": self.reason,
            "reference": self.reference,
            "channel": self.channel,
            "external_ref": self.external_ref,
            "evidence_file_id": self.evidence_file_id,
            "user": self.user.username if self.user else None,
            "count_id": self.count_id,
            "order_id": self.order_id,
            "created_at": iso(self.created_at),
        }


class Setting(db.Model):
    """Parámetros configurables (umbrales de alertas, reposición, política de reservas…)."""

    __tablename__ = "settings"

    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.JSON, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

