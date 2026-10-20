from sqlalchemy import CheckConstraint, UniqueConstraint

from ..common import iso, utcnow
from ..extensions import db

IMPORT_KINDS = ("catalogo", "comercio")
IMPORT_STATUSES = ("validado", "confirmado", "descartado")


class ImportBatch(db.Model):
    """Un archivo importado. Se valida primero; solo al confirmar se escriben datos."""

    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(f"kind IN {IMPORT_KINDS}", name="kind_valid"),
        CheckConstraint(f"status IN {IMPORT_STATUSES}", name="status_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    file_id = db.Column(db.Integer, db.ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    status = db.Column(db.String(20), nullable=False, default="validado", index=True)
    sheet_name = db.Column(db.String(100))
    total_rows = db.Column(db.Integer, nullable=False, default=0)
    valid_rows = db.Column(db.Integer, nullable=False, default=0)
    added = db.Column(db.Integer, nullable=False, default=0)
    updated = db.Column(db.Integer, nullable=False, default=0)
    skipped = db.Column(db.Integer, nullable=False, default=0)
    rejected = db.Column(db.Integer, nullable=False, default=0)
    columns = db.Column(db.JSON)
    summary = db.Column(db.JSON)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    confirmed_at = db.Column(db.DateTime(timezone=True))

    file = db.relationship("StoredFile")
    user = db.relationship("User")
    issues = db.relationship("ImportIssue", back_populates="batch", cascade="all, delete-orphan",
                             order_by="(ImportIssue.row_number, ImportIssue.id)")

    def to_dict(self, with_issues=False):
        data = {
            "id": self.id, "kind": self.kind, "status": self.status,
            "file_name": self.file.original_name if self.file else None,
            "sha256": self.file.sha256 if self.file else None,
            "user": self.user.username if self.user else None, "sheet_name": self.sheet_name,
            "total_rows": self.total_rows, "valid_rows": self.valid_rows, "added": self.added,
            "updated": self.updated, "skipped": self.skipped, "rejected": self.rejected,
            "columns": self.columns, "summary": self.summary,
            "created_at": iso(self.created_at), "confirmed_at": iso(self.confirmed_at),
        }
        if with_issues:
            data["issues"] = [i.to_dict() for i in self.issues[:500]]
            data["issues_total"] = len(self.issues)
        return data


class ImportIssue(db.Model):
    __tablename__ = "import_issues"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number = db.Column(db.Integer)  # fila del archivo (1 = encabezado)
    column = db.Column(db.String(100))
    severity = db.Column(db.String(12), nullable=False)  # error | advertencia
    message = db.Column(db.String(500), nullable=False)

    batch = db.relationship("ImportBatch", back_populates="issues")

    def to_dict(self):
        return {"row": self.row_number, "column": self.column, "severity": self.severity, "message": self.message}


class TradeRecord(db.Model):
    """Estadística de comercio exterior de calzado. Independiente del inventario de la tienda."""

    __tablename__ = "trade_records"
    __table_args__ = (
        UniqueConstraint("reporter", "flow", "year", "hs6_code", "partner", "occurrence", name="uq_trade_natural_key"),
        CheckConstraint("occurrence >= 1", name="occurrence_positive"),
        CheckConstraint("value_usd IS NULL OR value_usd >= 0", name="value_non_negative"),
        CheckConstraint("quantity_pairs IS NULL OR quantity_pairs >= 0", name="quantity_non_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    reporter = db.Column(db.String(100), nullable=False, index=True)
    flow = db.Column(db.String(30), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    hs6_code = db.Column(db.String(6), nullable=False, index=True)
    category = db.Column(db.String(200))
    partner = db.Column(db.String(150), nullable=False, index=True)
    # 1 normalmente. >1 solo si se importó con la política "separados": filas con la misma clave y
    # valores distintos que el usuario declaró como operaciones distintas (n.º de aparición en el archivo).
    occurrence = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    is_aggregate = db.Column(db.Boolean, nullable=False, default=False, index=True)
    value_thousand_usd = db.Column(db.Numeric(18, 3))
    quantity_pairs = db.Column(db.Numeric(18, 2))
    value_usd = db.Column(db.Numeric(18, 2))
    value_usd_per_pair_source = db.Column(db.Numeric(14, 4))  # tal como venía en el archivo
    value_usd_per_pair = db.Column(db.Numeric(14, 4))  # recalculado (NULL si no es calculable)
    quality_flags = db.Column(db.JSON)
    source_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id", ondelete="SET NULL"), index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        num = lambda v: float(v) if v is not None else None  # noqa: E731
        return {
            "id": self.id, "reporter": self.reporter, "flow": self.flow, "year": self.year,
            "hs6_code": self.hs6_code, "category": self.category, "partner": self.partner,
            "occurrence": self.occurrence,
            "is_aggregate": self.is_aggregate, "value_thousand_usd": num(self.value_thousand_usd),
            "quantity_pairs": num(self.quantity_pairs), "value_usd": num(self.value_usd),
            "value_usd_per_pair_source": num(self.value_usd_per_pair_source),
            "value_usd_per_pair": num(self.value_usd_per_pair), "quality_flags": self.quality_flags or [],
            "source_batch_id": self.source_batch_id,
        }


class DataExport(db.Model):
    """Registro de cada exportación: quién, qué, con qué filtros y cuántas filas."""

    __tablename__ = "data_exports"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    dataset = db.Column(db.String(40), nullable=False)
    file_format = db.Column(db.String(10), nullable=False)
    filters = db.Column(db.JSON)
    row_count = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    user = db.relationship("User")

    def to_dict(self):
        return {"id": self.id, "user": self.user.username if self.user else None, "dataset": self.dataset,
                "format": self.file_format, "filters": self.filters, "row_count": self.row_count,
                "created_at": iso(self.created_at)}
