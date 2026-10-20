from sqlalchemy import CheckConstraint, UniqueConstraint

from ..common import iso, utcnow
from ..extensions import db

PRODUCT_STATUSES = ("activo", "inactivo", "descontinuado")


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Supplier(TimestampMixin, db.Model):
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    contact_name = db.Column(db.String(150))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(150))
    notes = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "contact_name": self.contact_name,
            "phone": self.phone,
            "email": self.email,
            "notes": self.notes,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }


class Brand(db.Model):
    __tablename__ = "brands"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.name}


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.name}


class Product(TimestampMixin, db.Model):
    """Modelo comercial del zapato (marca + modelo). El stock vive en sus variantes."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(f"status IN {PRODUCT_STATUSES}", name="status_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False, unique=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False, index=True)
    model_name = db.Column(db.String(150), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    footwear_type = db.Column(db.String(100))
    description = db.Column(db.Text)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"), index=True)
    status = db.Column(db.String(20), nullable=False, default="activo")
    is_published = db.Column(db.Boolean, nullable=False, default=False)  # visible en la tienda online

    brand = db.relationship("Brand", lazy="joined")
    category = db.relationship("Category", lazy="joined")
    supplier = db.relationship("Supplier")
    variants = db.relationship("ProductVariant", back_populates="product", order_by="ProductVariant.id")
    images = db.relationship("ProductImage", back_populates="product",
                             order_by="(ProductImage.position, ProductImage.id)")

    def to_dict(self, with_variants=False):
        data = {
            "id": self.id,
            "code": self.code,
            "brand_id": self.brand_id,
            "brand": self.brand.name if self.brand else None,
            "model_name": self.model_name,
            "category_id": self.category_id,
            "category": self.category.name if self.category else None,
            "footwear_type": self.footwear_type,
            "description": self.description,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier.name if self.supplier else None,
            "status": self.status,
            "is_published": self.is_published,
            "images": [i.to_dict() for i in self.images],
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }
        if with_variants:
            data["variants"] = [v.to_dict() for v in self.variants]
        return data


class ProductImage(db.Model):
    __tablename__ = "product_images"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = db.Column(db.Integer, db.ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False, unique=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    product = db.relationship("Product", back_populates="images")
    file = db.relationship("StoredFile", lazy="joined")

    def to_dict(self):
        return {"id": self.id, "file_id": self.file_id, "position": self.position,
                "url": f"/api/public/images/{self.file_id}"}


class ProductVariant(TimestampMixin, db.Model):
    """Combinación talla + color de un producto. Unidad de stock: par comercial.

    `stock_quantity` es un saldo derivado: solo lo modifica inventory.services
    junto con un InventoryMovement en la misma transacción.
    """

    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("product_id", "size", "color", name="uq_variant_product_size_color"),
        CheckConstraint("stock_quantity >= 0", name="stock_non_negative"),
        CheckConstraint("min_stock >= 0", name="min_stock_non_negative"),
        CheckConstraint("cost IS NULL OR cost >= 0", name="cost_non_negative"),
        CheckConstraint("price IS NULL OR price >= 0", name="price_non_negative"),
        CheckConstraint(f"status IN {PRODUCT_STATUSES}", name="status_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    sku = db.Column(db.String(60), nullable=False, unique=True)
    barcode = db.Column(db.String(64), unique=True)
    size = db.Column(db.String(20), nullable=False)
    color = db.Column(db.String(50), nullable=False)
    cost = db.Column(db.Numeric(12, 2))
    price = db.Column(db.Numeric(12, 2))
    stock_quantity = db.Column(db.Integer, nullable=False, default=0)
    min_stock = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="activo")

    product = db.relationship("Product", back_populates="variants")

    @property
    def stock_state(self):
        if self.stock_quantity == 0:
            return "agotado"
        if self.stock_quantity <= self.min_stock:
            return "bajo"
        return "ok"

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "sku": self.sku,
            "barcode": self.barcode,
            "size": self.size,
            "color": self.color,
            "cost": str(self.cost) if self.cost is not None else None,
            "price": str(self.price) if self.price is not None else None,
            "stock_quantity": self.stock_quantity,
            "min_stock": self.min_stock,
            "stock_state": self.stock_state,
            "status": self.status,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }
