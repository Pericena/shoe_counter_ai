from sqlalchemy import CheckConstraint, Index, text

from ..common import iso, utcnow
from ..extensions import db

PRIORITIES = ("alta", "media", "baja")
STATUSES = ("abierta", "leida", "resuelta")


class Notification(db.Model):
    """Alerta del sistema. `dedupe_key` evita repetir la misma alerta mientras siga abierta."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(f"priority IN {PRIORITIES}", name="priority_valid"),
        CheckConstraint(f"status IN {STATUSES}", name="status_valid"),
        Index("uq_notification_open_key", "dedupe_key", unique=True,
              postgresql_where=text("status <> 'resuelta'"), sqlite_where=text("status <> 'resuelta'")),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(40), nullable=False, index=True)
    priority = db.Column(db.String(10), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    action = db.Column(db.Text)
    entity_type = db.Column(db.String(40))
    entity_id = db.Column(db.String(40))
    dedupe_key = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="abierta", index=True)
    occurrences = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    read_at = db.Column(db.DateTime(timezone=True))
    read_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at = db.Column(db.DateTime(timezone=True))

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "priority": self.priority, "title": self.title,
                "message": self.message, "action": self.action, "entity_type": self.entity_type,
                "entity_id": self.entity_id, "status": self.status, "occurrences": self.occurrences,
                "created_at": iso(self.created_at), "last_seen_at": iso(self.last_seen_at),
                "read_at": iso(self.read_at), "resolved_at": iso(self.resolved_at)}
