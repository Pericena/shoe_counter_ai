from ..common import iso, utcnow
from ..extensions import db


class AuditLog(db.Model):
    """Registro inmutable de acciones relevantes. `username` se copia por si el usuario cambia."""

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    username = db.Column(db.String(50))
    action = db.Column(db.String(60), nullable=False, index=True)
    entity_type = db.Column(db.String(50), index=True)
    entity_id = db.Column(db.String(50))
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "created_at": iso(self.created_at),
        }
