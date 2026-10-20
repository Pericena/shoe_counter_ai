"""Tienda online (pedidos transaccionales), fotos públicas y reportes de BI. Datos ficticios."""
import io

from PIL import Image

from tests.conftest import ApiClient


def publish(manager, product_id):
    assert manager.patch(f"/api/products/{product_id}", json={"is_published": True}).status_code == 200


def stock(manager, variant_id, qty):
    manager.post("/api/inventory/movements", json={"variant_id": variant_id, "movement_type": "entrada_compra",
                                                   "quantity": qty})


def order_payload(variant_id, quantity=1):
    return {"customer_name": "Cliente Ficticio", "customer_email": "cliente@ejemplo.test",
            "items": [{"variant_id": variant_id, "quantity": quantity}]}


def test_catalog_only_shows_published_products(manager, anonymous, product, variant):
    assert anonymous.get("/api/shop/products").json["items"] == []
    publish(manager, product["id"])
    items = anonymous.get("/api/shop/products").json["items"]
    assert len(items) == 1
    public_variant = items[0]["variants"][0]
    assert "stock_quantity" not in public_variant and "cost" not in public_variant
    assert public_variant["available"] is False
    stock(manager, variant["id"], 2)
    assert anonymous.get("/api/shop/products?available=1&size=40").json["items"][0]["variants"][0]["available"] is True
    assert anonymous.get("/api/shop/products?size=44").json["items"] == []


def test_order_reserves_stock_and_lifecycle(manager, operator, anonymous, product, variant):
    publish(manager, product["id"])
    stock(manager, variant["id"], 3)
    created = anonymous.post("/api/shop/orders", json=order_payload(variant["id"], 2))
    assert created.status_code == 201, created.json
    order = created.json
    assert order["status"] == "creado"
    assert order["total_amount"] == "360.00"  # precio del servidor (180), no del cliente
    assert "customer_email" not in order  # respuesta pública sin datos personales
    # El pedido RESERVA: el físico sigue en 3, pero solo 1 está disponible para otra venta.
    current = manager.get(f"/api/variants/{variant['id']}").json
    assert (current["stock_quantity"], current["reserved_quantity"], current["available_quantity"]) == (3, 2, 1)

    lookup = anonymous.post("/api/shop/orders/lookup", json={"code": order["code"], "email": "cliente@ejemplo.test"})
    assert lookup.status_code == 200
    assert anonymous.post("/api/shop/orders/lookup", json={"code": order["code"], "email": "otro@x.test"}).status_code == 404

    order_id = manager.get("/api/orders").json["items"][0]["id"]
    assert operator.post(f"/api/orders/{order_id}/status", json={"status": "enviado"}).status_code == 409
    assert operator.post(f"/api/orders/{order_id}/status", json={"status": "pago_confirmado"}).status_code == 422
    for status, extra in (("pago_confirmado", {"payment_reference": "TRANSF-FICTICIA-1"}), ("preparado", {}),
                          ("enviado", {}), ("entregado", {})):
        response = operator.post(f"/api/orders/{order_id}/status", json={"status": status, **extra})
        assert response.status_code == 200, response.json
        if status == "enviado":  # al enviar sale el físico y se consume la reserva
            current = manager.get(f"/api/variants/{variant['id']}").json
            assert (current["stock_quantity"], current["reserved_quantity"]) == (1, 0)
    returned = operator.post(f"/api/orders/{order_id}/status", json={"status": "devuelto", "note": "Talla incorrecta"})
    assert returned.status_code == 200
    assert manager.get(f"/api/variants/{variant['id']}").json["stock_quantity"] == 3
    assert [h["to_status"] for h in returned.json["history"]] == [
        "creado", "pago_confirmado", "preparado", "enviado", "entregado", "devuelto"]
    assert manager.get("/api/inventory/reconciliation").json["ok"] is True


def test_cancel_restores_stock(manager, anonymous, product, variant):
    publish(manager, product["id"])
    stock(manager, variant["id"], 1)
    anonymous.post("/api/shop/orders", json=order_payload(variant["id"]))
    order_id = manager.get("/api/orders").json["items"][0]["id"]
    assert manager.post(f"/api/orders/{order_id}/status", json={"status": "cancelado"}).status_code == 422
    assert manager.post(f"/api/orders/{order_id}/status",
                        json={"status": "cancelado", "note": "Cliente desistió"}).status_code == 200
    current = manager.get(f"/api/variants/{variant['id']}").json
    assert (current["stock_quantity"], current["reserved_quantity"]) == (1, 0)
    types = [m["movement_type"] for m in manager.get("/api/inventory/movements").json["items"]]
    assert types[:2] == ["liberacion_reserva", "reserva"]
    assert manager.get("/api/inventory/reconciliation").json["ok"] is True


def test_last_unit_cannot_be_sold_twice(manager, anonymous, app, product, variant):
    publish(manager, product["id"])
    stock(manager, variant["id"], 1)
    first = anonymous.post("/api/shop/orders", json=order_payload(variant["id"]))
    second = ApiClient(app).post("/api/shop/orders", json=order_payload(variant["id"]))
    assert first.status_code == 201
    assert second.status_code == 409
    assert manager.get(f"/api/variants/{variant['id']}").json["available_quantity"] == 0
    assert manager.get("/api/orders").json["total"] == 1  # el pedido fallido no queda a medias


def test_order_rollback_when_one_line_fails(manager, anonymous, product, variant):
    publish(manager, product["id"])
    other = manager.post(f"/api/products/{product['id']}/variants",
                         json={"sku": "TEST-001-41-NEG", "size": "41", "color": "Negro", "price": "180"}).json
    stock(manager, variant["id"], 5)
    payload = order_payload(variant["id"], 2)
    payload["items"].append({"variant_id": other["id"], "quantity": 1})  # sin stock
    response = anonymous.post("/api/shop/orders", json=payload)
    assert response.status_code == 409
    assert manager.get(f"/api/variants/{variant['id']}").json["stock_quantity"] == 5


def test_order_validation(manager, anonymous, product, variant):
    publish(manager, product["id"])
    assert anonymous.post("/api/shop/orders", json={**order_payload(variant["id"]), "items": []}).status_code == 422
    assert anonymous.post("/api/shop/orders", json={**order_payload(variant["id"]),
                                                    "customer_email": "no-es-correo"}).status_code == 422
    assert anonymous.post("/api/shop/orders", json=order_payload(variant["id"], 50)).status_code == 422
    unpublished = anonymous.post("/api/shop/orders", json=order_payload(999))
    assert unpublished.status_code == 409


def test_order_rate_limit(app, manager, product, variant):
    publish(manager, product["id"])
    app.config["ORDERS_PER_IP_PER_HOUR"] = 2
    api = ApiClient(app)
    codes = [api.post("/api/shop/orders", json=order_payload(variant["id"])).status_code for _ in range(3)]
    assert codes[-1] == 429


def test_product_photos_public_only_when_published(manager, anonymous, product):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 20, 30)).save(buffer, "PNG")
    buffer.seek(0)
    uploaded = manager.post(f"/api/products/{product['id']}/images", data={"image": (buffer, "foto.png")},
                            content_type="multipart/form-data")
    assert uploaded.status_code == 201
    url = uploaded.json["url"]
    assert manager.get(url).status_code == 200
    assert anonymous.get(url).status_code == 404
    publish(manager, product["id"])
    assert anonymous.get(url).status_code == 200


def test_overview_empty_and_with_data(manager, variant):
    empty = manager.get("/api/reports/overview").json
    assert empty["inventory"]["pairs"] == 0
    assert empty["recent_movements"] == []
    assert empty["ai_model"]["installed"] is False
    stock(manager, variant["id"], 3)
    data = manager.get("/api/reports/overview").json
    assert data["inventory"]["pairs"] == 3
    assert data["inventory"]["inventory_value_at_cost"] == "301.50"
    assert data["last_30_days"]["entries"] == 3


def test_movement_series_and_rotation(manager, variant):
    vid = variant["id"]
    assert manager.get("/api/reports/rotation").json["has_data"] is False
    stock(manager, vid, 10)
    manager.post("/api/inventory/movements", json={"variant_id": vid, "movement_type": "salida_venta", "quantity": 4})
    series = manager.get("/api/reports/movements?group=month").json
    assert sum(p["entradas"] for p in series["series"]) == 10
    assert sum(p["ventas"] for p in series["series"]) == 4
    rotation = manager.get("/api/reports/rotation").json
    assert rotation["has_data"] is True
    item = rotation["items"][0]
    assert item["units_sold"] == 4
    assert item["stock_start"] == 0 and item["stock_end"] == 6
    assert item["rotation"] == round(4 / 3, 2)
    assert manager.get("/api/reports/movements?group=hora").status_code == 400


def test_adjustments_report(manager, variant):
    vid = variant["id"]
    stock(manager, vid, 5)
    manager.post("/api/inventory/movements", json={"variant_id": vid, "movement_type": "conteo_fisico",
                                                   "counted_quantity": 4})
    report = manager.get("/api/reports/adjustments").json
    assert report["total_negative"] == 1
    assert report["physical_counts_with_difference"] == 1


def test_reports_require_permission(app, users):
    from tests.conftest import logged
    viewer = logged(app, "consulta_prueba")
    assert viewer.get("/api/reports/overview").status_code == 200
    assert viewer.get("/api/reports/inventario.pdf").status_code == 403  # requiere exports.run
