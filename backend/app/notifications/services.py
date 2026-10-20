"""Generación de alertas. `scan()` evalúa las reglas sobre los datos reales y resuelve las que ya no aplican."""
import re
import unicodedata
from datetime import timedelta

from flask import current_app
from sqlalchemy import func, select

from ..common import utcnow
from ..extensions import db
from .models import Notification

# Tipos gestionados por scan(): se resuelven solos cuando la condición desaparece.
SCANNED_KINDS = ("stock_bajo", "agotado", "reposicion_urgente", "sin_foto", "datos_incompletos", "posible_duplicado",
                 "importacion_errores", "conteo_diferencia", "aprobacion_pendiente", "devolucion_pendiente",
                 "recepcion_atrasada", "baja_rotacion", "anomalia_movimiento", "vision_no_disponible")


def notify(kind, priority, title, message, action, entity_type=None, entity_id=None, dedupe_key=None):
    """Crea la alerta o, si ya hay una abierta con la misma clave, solo actualiza la repetición."""
    key = dedupe_key or f"{kind}:{entity_type}:{entity_id}"
    existing = db.session.execute(select(Notification).where(
        Notification.dedupe_key == key, Notification.status != "resuelta")).scalar_one_or_none()
    if existing is not None:
        existing.occurrences += 1
        existing.last_seen_at = utcnow()
        existing.message = message
        return existing, False
    note = Notification(kind=kind, priority=priority, title=title[:200], message=message, action=action,
                        entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None,
                        dedupe_key=key)
    db.session.add(note)
    db.session.flush()
    if priority == "alta":
        _email_admins(note)
    return note, True


def _email_admins(note):
    """Canal adicional opcional: solo si SMTP está configurado."""
    cfg = current_app.config
    if not (cfg.get("SMTP_HOST") and cfg.get("SMTP_FROM")):
        return
    try:
        import smtplib
        from email.message import EmailMessage

        from ..auth.models import Role, User
        emails = [u.email for u in db.session.execute(select(User).join(Role).where(
            Role.code == "admin", User.is_active.is_(True), User.email.isnot(None))).scalars()]
        if not emails:
            return
        message = EmailMessage()
        message["Subject"] = f"[Shoe Counter AI] {note.title}"
        message["From"], message["To"] = cfg["SMTP_FROM"], ", ".join(emails)
        message.set_content(f"{note.message}\n\nAcción recomendada: {note.action or '-'}")
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=10) as smtp:
            if cfg.get("SMTP_STARTTLS"):
                smtp.starttls()
            if cfg.get("SMTP_USER"):
                smtp.login(cfg["SMTP_USER"], cfg.get("SMTP_PASSWORD") or "")
            smtp.send_message(message)
    except Exception as error:  # noqa: BLE001 - el correo es opcional
        current_app.logger.warning("No se pudo enviar la alerta por correo: %s", error)


def _fold(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def scan():
    """Evalúa todas las reglas. Devuelve {creadas, activas, resueltas}."""
    from ..ai.detector import model_status
    from ..ai.models import AICount
    from ..imports.models import ImportBatch
    from ..inventory.models import InventoryMovement
    from ..inventory.settings import get_setting
    from ..products.models import Product, ProductVariant
    from ..purchasing.models import PurchaseOrder, ReplenishmentRecommendation
    from ..sales.models import ReturnItem

    now = utcnow()
    active, created = set(), 0

    def hit(kind, priority, title, message, action, entity_type, entity_id, key=None):
        nonlocal created
        key = key or f"{kind}:{entity_type}:{entity_id}"
        active.add(key)
        _, new = notify(kind, priority, title, message, action, entity_type, entity_id, key)
        created += int(new)

    variants = db.session.execute(select(ProductVariant).where(ProductVariant.status == "activo")).scalars().all()
    moved = {vid for (vid,) in db.session.execute(select(InventoryMovement.variant_id).distinct())}
    for v in variants:
        label = f"{v.product.brand.name} {v.product.model_name} · {v.sku} (T{v.size} {v.color})"
        available = v.stock_quantity - v.reserved_quantity
        if available <= 0 and v.id in moved:
            hit("agotado", "alta", f"Agotado: {v.sku}", f"{label} no tiene stock disponible "
                f"(físico {v.stock_quantity}, reservado {v.reserved_quantity}).",
                "Revisa la reposición o retírala de la tienda online.", "variant", v.id)
        elif 0 < available <= v.min_stock:
            hit("stock_bajo", "media", f"Stock bajo: {v.sku}", f"{label}: {available} disponibles, mínimo {v.min_stock}.",
                "Calcula la reposición y genera la orden de compra si corresponde.", "variant", v.id)
        missing = [name for name, value in (("precio", v.price), ("costo", v.cost)) if value is None]
        if missing:
            hit("datos_incompletos", "baja", f"Datos incompletos: {v.sku}", f"{label} no tiene {' ni '.join(missing)}.",
                "Completa los datos de la variante.", "variant", v.id)

    products = db.session.execute(select(Product).where(Product.status.in_(("activo", "pendiente_revision")))).scalars().all()
    groups = {}
    for p in products:
        if not p.images:
            hit("sin_foto", "baja", f"Producto sin fotografía: {p.code}", f"{p.brand.name} {p.model_name} no tiene fotos.",
                "Sube una foto o usa el Registro inteligente para asociar imágenes.", "product", p.id)
        if p.category_id is None or p.supplier_id is None:
            faltan = [n for n, val in (("categoría", p.category_id), ("proveedor", p.supplier_id)) if val is None]
            hit("datos_incompletos", "baja", f"Datos incompletos: {p.code}",
                f"{p.brand.name} {p.model_name} no tiene {' ni '.join(faltan)}.", "Completa la ficha del producto.",
                "product", p.id)
        groups.setdefault((p.brand_id, _fold(p.model_name)), []).append(p)
    for (_, model), items in groups.items():
        if len(items) > 1:
            codes = ", ".join(p.code for p in items)
            hit("posible_duplicado", "media", f"Posible producto duplicado: {items[0].model_name}",
                f"Misma marca y modelo en los productos {codes}.", "Revisa si son el mismo producto y unifica las variantes.",
                "product", items[0].id, key=f"posible_duplicado:{items[0].brand_id}:{model}")

    for rec in db.session.execute(select(ReplenishmentRecommendation).where(
            ReplenishmentRecommendation.status == "pendiente", ReplenishmentRecommendation.priority == "alta")).scalars():
        hit("reposicion_urgente", "alta", f"Reposición urgente: {rec.variant.sku}", rec.reason,
            f"Revisa la propuesta (sugerido {rec.suggested_qty} pares) en Compras y reposición.", "replenishment", rec.id)

    week = now - timedelta(days=7)
    for batch in db.session.execute(select(ImportBatch).where(
            ImportBatch.created_at >= week, ImportBatch.status == "validado", ImportBatch.rejected > 0)).scalars():
        hit("importacion_errores", "media", f"Importación #{batch.id} con errores",
            f"{batch.rejected} filas rechazadas de {batch.total_rows} en «{batch.file.original_name}».",
            "Descarga el informe de errores, corrige el archivo y vuelve a importarlo.", "import", batch.id)

    for c in db.session.execute(select(AICount).where(AICount.status == "aplicado", AICount.applied_at >= week)).scalars():
        if c.applied_pairs is not None and c.stock_before is not None and c.applied_pairs != c.stock_before:
            diff = c.applied_pairs - c.stock_before
            hit("conteo_diferencia", "media", f"Conteo #{c.id} con diferencia ({diff:+d})",
                f"{c.variant.sku if c.variant else '-'}: sistema {c.stock_before}, contado {c.applied_pairs}.",
                "Investiga la diferencia (ventas sin registrar, mercancía mal ubicada…).", "ai_count", c.id)

    drafts = db.session.execute(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status == "borrador")).scalar_one()
    if drafts:
        hit("aprobacion_pendiente", "media", f"{drafts} órdenes de compra por aprobar",
            "Hay órdenes de compra en borrador.", "Revísalas y apruébalas o cancélalas.", "purchase_order", "borradores")
    pending_returns = db.session.execute(select(func.count()).select_from(ReturnItem).where(
        ReturnItem.condition == "revision", ReturnItem.resolution.is_(None))).scalar_one()
    if pending_returns:
        hit("devolucion_pendiente", "media", f"{pending_returns} devoluciones pendientes de inspección",
            "Hay productos devueltos en revisión.", "Decide si se reintegran al stock o se dan de baja.", "return", "pendientes")
    for po in db.session.execute(select(PurchaseOrder).where(
            PurchaseOrder.status.in_(("solicitada", "recibida_parcial")), PurchaseOrder.expected_date.isnot(None),
            PurchaseOrder.expected_date < now.date())).scalars():
        hit("recepcion_atrasada", "media", f"Compra {po.number} pendiente de recepción",
            f"Fecha prevista {po.expected_date.isoformat()} ({po.supplier.name}).", "Contacta al proveedor o registra la recepción.",
            "purchase_order", po.id)

    rotation_days = int(get_setting("low_rotation_days"))
    since = now - timedelta(days=rotation_days)
    recent_sales = {vid for (vid,) in db.session.execute(select(InventoryMovement.variant_id).where(
        InventoryMovement.created_at >= since, InventoryMovement.movement_type.in_(("salida_venta", "salida_pedido"))).distinct())}
    first_entry = dict(db.session.execute(select(InventoryMovement.variant_id, func.min(InventoryMovement.created_at))
                                          .where(InventoryMovement.quantity > 0).group_by(InventoryMovement.variant_id)).all())
    for v in variants:
        entry = first_entry.get(v.id)
        if entry is not None and entry.tzinfo is None:
            from datetime import timezone
            entry = entry.replace(tzinfo=timezone.utc)
        if v.stock_quantity > 0 and v.id not in recent_sales and entry is not None and entry < since:
            hit("baja_rotacion", "baja", f"Baja rotación: {v.sku}",
                f"{v.stock_quantity} pares sin ventas en {rotation_days} días.",
                "Valora promociones, traslado a otra tienda o no reponer.", "variant", v.id)

    threshold = int(get_setting("anomaly_adjust_pairs"))
    for m in db.session.execute(select(InventoryMovement).where(
            InventoryMovement.created_at >= week, InventoryMovement.movement_type.in_(("ajuste", "conteo_fisico", "danado", "perdido")),
            func.abs(InventoryMovement.quantity) >= threshold)).scalars():
        hit("anomalia_movimiento", "alta", f"Movimiento atípico: {m.movement_type} {m.quantity:+d}",
            f"{m.variant.sku}: {m.reason or 'sin motivo'} (usuario {m.user.username if m.user else 'sistema'}).",
            "Verifica que el ajuste esté justificado.", "movement", m.id)

    status, _ = model_status()
    if not status["installed"]:
        hit("vision_no_disponible", "media", "Detector de zapatos no disponible", status.get("message", ""),
            "Instala o selecciona un modelo (docs/04-ia-detector.md). El conteo manual sigue funcionando.", "ai", "modelo")

    resolved = 0
    for note in db.session.execute(select(Notification).where(
            Notification.status != "resuelta", Notification.kind.in_(SCANNED_KINDS))).scalars():
        if note.dedupe_key not in active:
            note.status, note.resolved_at = "resuelta", now
            resolved += 1
    db.session.commit()
    return {"created": created, "active": len(active), "resolved": resolved}

