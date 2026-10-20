from sqlalchemy import CheckConstraint

from ..common import iso, utcnow
from ..extensions import db

ANALYSIS_STATUSES = ("analizado", "vinculado", "creado", "descartado")


class ImageFeature(db.Model):
    """Características visuales de una imagen (de referencia del catálogo o de una consulta)."""

    __tablename__ = "image_features"

    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey("stored_files.id", ondelete="CASCADE"), nullable=False, unique=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), index=True)  # NULL = consulta
    box = db.Column(db.JSON)  # recorte usado (caja normalizada) o NULL si es la imagen completa
    color_hist = db.Column(db.LargeBinary, nullable=False)
    orb = db.Column(db.LargeBinary, nullable=False)
    orb_count = db.Column(db.Integer, nullable=False)
    colors = db.Column(db.JSON)
    version = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class VisionAnalysis(db.Model):
    """Una sesión de registro inteligente: imágenes analizadas, propuestas y decisión final de la persona."""

    __tablename__ = "vision_analyses"
    __table_args__ = (CheckConstraint(f"status IN {ANALYSIS_STATUSES}", name="status_valid"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    file_ids = db.Column(db.JSON, nullable=False)
    result = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(15), nullable=False, default="analizado", index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"))
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    decided_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    def to_dict(self):
        return {"id": self.id, "status": self.status, "file_ids": self.file_ids, "result": self.result,
                "product_id": self.product_id, "created_at": iso(self.created_at), "decided_at": iso(self.decided_at)}


class IdentificationFeedback(db.Model):
    """Resultado de cada propuesta: base para calibrar umbrales y medir aciertos reales."""

    __tablename__ = "identification_feedback"
    __table_args__ = (CheckConstraint("outcome IN ('aceptada', 'rechazada')", name="outcome_valid"),)

    id = db.Column(db.Integer, primary_key=True)
    analysis_id = db.Column(db.Integer, db.ForeignKey("vision_analyses.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    rank = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Float, nullable=False)
    outcome = db.Column(db.String(10), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
