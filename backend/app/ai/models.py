from sqlalchemy import CheckConstraint

from ..common import iso, utcnow
from ..extensions import db

COUNT_STATUSES = ("revision", "confirmado", "aplicado", "descartado")
DETECTION_SOURCES = ("modelo", "manual")


class AICount(db.Model):
    """Conteo inteligente: foto + detecciones + revisión humana. Nunca altera el stock por sí solo."""

    __tablename__ = "ai_counts"
    __table_args__ = (
        CheckConstraint(f"status IN {COUNT_STATUSES}", name="status_valid"),
        CheckConstraint("detected_count IS NULL OR detected_count >= 0", name="detected_non_negative"),
        CheckConstraint("confirmed_shoes IS NULL OR confirmed_shoes >= 0", name="confirmed_non_negative"),
        CheckConstraint("pairs_complete IS NULL OR pairs_complete >= 0", name="pairs_non_negative"),
        CheckConstraint("loose_shoes IS NULL OR loose_shoes >= 0", name="loose_non_negative"),
        CheckConstraint("applied_pairs IS NULL OR applied_pairs >= 0", name="applied_non_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status = db.Column(db.String(20), nullable=False, default="revision", index=True)
    model_version = db.Column(db.String(80))  # NULL = sin modelo: conteo 100 % manual
    confidence_threshold = db.Column(db.Float)
    inference_ms = db.Column(db.Integer)
    detected_count = db.Column(db.Integer)  # zapatos individuales detectados por el modelo
    confirmed_shoes = db.Column(db.Integer)  # zapatos aceptados por la persona
    pairs_complete = db.Column(db.Integer)
    loose_shoes = db.Column(db.Integer)
    notes = db.Column(db.Text)
    # Producto reconocido en la propia foto (código de barras/etiqueta) o elegido desde la cámara en vivo.
    identified_variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id", ondelete="SET NULL"), index=True)
    identification = db.Column(db.JSON)  # método, códigos leídos y candidatas
    confirmed_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at = db.Column(db.DateTime(timezone=True))
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id", ondelete="SET NULL"), index=True)
    applied_pairs = db.Column(db.Integer)
    stock_before = db.Column(db.Integer)
    applied_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    applied_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    detections = db.relationship("AIDetection", back_populates="count", cascade="all, delete-orphan",
                                 order_by="AIDetection.id")
    user = db.relationship("User", foreign_keys=[user_id])
    confirmer = db.relationship("User", foreign_keys=[confirmed_by])
    applier = db.relationship("User", foreign_keys=[applied_by])
    variant = db.relationship("ProductVariant", foreign_keys=[variant_id])
    identified_variant = db.relationship("ProductVariant", foreign_keys=[identified_variant_id])
    file = db.relationship("StoredFile")

    def to_dict(self, with_detections=True):
        accepted = [d for d in self.detections if d.accepted]
        data = {
            "id": self.id,
            "file_id": self.file_id,
            "image_url": f"/api/files/{self.file_id}",
            "image_width": self.file.width if self.file else None,
            "image_height": self.file.height if self.file else None,
            "user": self.user.username if self.user else None,
            "status": self.status,
            "model_version": self.model_version,
            "confidence_threshold": self.confidence_threshold,
            "inference_ms": self.inference_ms,
            "detected_count": self.detected_count,
            "accepted_count": len(accepted),
            "manual_added": sum(1 for d in accepted if d.source == "manual"),
            "rejected_count": sum(1 for d in self.detections if d.source == "modelo" and not d.accepted),
            "confirmed_shoes": self.confirmed_shoes,
            "pairs_complete": self.pairs_complete,
            "loose_shoes": self.loose_shoes,
            "notes": self.notes,
            "identified_variant_id": self.identified_variant_id,
            "identified_sku": self.identified_variant.sku if self.identified_variant else None,
            "identification": self.identification,
            "confirmed_by": self.confirmer.username if self.confirmer else None,
            "confirmed_at": iso(self.confirmed_at),
            "variant_id": self.variant_id,
            "variant_sku": self.variant.sku if self.variant else None,
            "applied_pairs": self.applied_pairs,
            "stock_before": self.stock_before,
            "difference": (self.applied_pairs - self.stock_before)
            if self.applied_pairs is not None and self.stock_before is not None else None,
            "applied_by": self.applier.username if self.applier else None,
            "applied_at": iso(self.applied_at),
            "created_at": iso(self.created_at),
        }
        if with_detections:
            data["detections"] = [d.to_dict() for d in self.detections]
        return data


class AIDetection(db.Model):
    """Caja normalizada (0–1). Las del modelo se aceptan o rechazan; las manuales las añade la persona."""

    __tablename__ = "ai_detections"
    __table_args__ = (
        CheckConstraint(f"source IN {DETECTION_SOURCES}", name="source_valid"),
        CheckConstraint("x1 >= 0 AND y1 >= 0 AND x2 <= 1 AND y2 <= 1 AND x1 < x2 AND y1 < y2", name="box_valid"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
    )

    id = db.Column(db.Integer, primary_key=True)
    count_id = db.Column(db.Integer, db.ForeignKey("ai_counts.id", ondelete="CASCADE"), nullable=False, index=True)
    x1 = db.Column(db.Float, nullable=False)
    y1 = db.Column(db.Float, nullable=False)
    x2 = db.Column(db.Float, nullable=False)
    y2 = db.Column(db.Float, nullable=False)
    confidence = db.Column(db.Float)
    label = db.Column(db.String(50), nullable=False, default="zapato")
    source = db.Column(db.String(10), nullable=False, default="modelo")
    accepted = db.Column(db.Boolean, nullable=False, default=True)
    # Producto asociado a esta caja (confirmado por la persona). Permite conteos de varios modelos en una foto.
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id", ondelete="SET NULL"), index=True)

    count = db.relationship("AICount", back_populates="detections")

    def to_dict(self):
        return {"id": self.id, "x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2,
                "confidence": self.confidence, "label": self.label, "source": self.source,
                "accepted": self.accepted, "variant_id": self.variant_id}
