from flask import g, has_request_context

from ..extensions import db
from .models import AuditLog


def client_ip():
    from flask import request
    return (request.remote_addr or "desconocida")[:64]


def audit(action, entity_type=None, entity_id=None, details=None, user=None, commit=False):
    """Añade un registro de auditoría a la transacción actual (o la confirma si commit=True)."""
    if user is None and has_request_context():
        user = getattr(g, "user", None)
    entry = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
        ip_address=client_ip() if has_request_context() else None,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry
