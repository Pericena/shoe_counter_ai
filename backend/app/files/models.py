from sqlalchemy import CheckConstraint

from ..common import iso, utcnow
from ..extensions import db

FILE_PURPOSES = ("producto", "conteo", "importacion")


class StoredFile(db.Model):
    """Metadatos de un archivo guardado en STORAGE_DIR. La ruta nunca se expone al cliente."""

    __tablename__ = "stored_files"
    __table_args__ = (
        CheckConstraint(f"purpose IN {FILE_PURPOSES}", name="purpose_valid"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    purpose = db.Column(db.String(20), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    relative_path = db.Column(db.String(300), nullable=False, unique=True)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "purpose": self.purpose,
            "original_name": self.original_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
            "created_at": iso(self.created_at),
        }
