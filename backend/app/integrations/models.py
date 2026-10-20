from sqlalchemy import CheckConstraint, UniqueConstraint

from ..common import iso, utcnow
from ..extensions import db

INTEGRATION_KINDS = ("tpv", "ecommerce")
EVENT_TYPES = ("venta", "devolucion")
EVENT_STATUSES = ("procesado", "error", "conflicto")


class IntegrationChannel(db.Model):
    """Sistema externo (TPV o e-commerce) autorizado a enviar eventos. La clave solo se guarda como hash."""

    __tablename__ = "integration_channels"
    __table_args__ = (CheckConstraint(f"kind IN {INTEGRATION_KINDS}", name="kind_valid"),)

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(15), nullable=False)
    adapter = db.Column(db.String(30), nullable=False, default="generico")
    api_key_hash = db.Column(db.String(64), nullable=False, unique=True)
    api_key_prefix = db.Column(db.String(12), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_event_at = db.Column(db.DateTime(timezone=True))

    location = db.relationship("Location")

    def to_dict(self):
        return {"id": self.id, "code": self.code, "name": self.name, "kind": self.kind, "adapter": self.adapter,
                "api_key_prefix": self.api_key_prefix, "location": self.location.name if self.location else None,
                "location_id": self.location_id, "is_active": self.is_active, "created_at": iso(self.created_at),
                "last_event_at": iso(self.last_event_at)}


class IntegrationEvent(db.Model):
    """Registro de cada evento recibido. (canal, tipo, id externo) es único: los reintentos no duplican."""

    __tablename__ = "integration_events"
    __table_args__ = (
        UniqueConstraint("channel_id", "event_type", "external_id", name="uq_integration_event"),
        CheckConstraint(f"status IN {EVENT_STATUSES}", name="status_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("integration_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = db.Column(db.String(20), nullable=False)
    external_id = db.Column(db.String(150), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(15), nullable=False, index=True)
    error = db.Column(db.Text)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id", ondelete="SET NULL"))
    attempts = db.Column(db.Integer, nullable=False, default=1)
    received_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    processed_at = db.Column(db.DateTime(timezone=True))

    channel = db.relationship("IntegrationChannel")

    def to_dict(self):
        return {"id": self.id, "channel": self.channel.code if self.channel else None, "event_type": self.event_type,
                "external_id": self.external_id, "status": self.status, "error": self.error, "sale_id": self.sale_id,
                "attempts": self.attempts, "received_at": iso(self.received_at), "processed_at": iso(self.processed_at),
                "payload": self.payload}
