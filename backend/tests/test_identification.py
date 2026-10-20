"""Producto reconocido → ficha completa y relación con el inventario. Datos FICTICIOS."""
import io

import zxingcpp

from tests.test_ai import FakeDetector
from tests.test_ocr_live import label_image


def ean():
    return zxingcpp.create_barcode("779000000001", zxingcpp.BarcodeFormat.EAN13).text


def stock(api, vid, qty):
    api.post("/api/inventory/movements", json={"variant_id": vid, "movement_type": "entrada_compra", "quantity": qty})


def test_product_overview(manager, product, variant):
    other = manager.post(f"/api/products/{product['id']}/variants",
                         json={"sku": "TEST-001-41-BLA", "size": "41", "color": "Blanco", "price": "200"}).json
    stock(manager, variant["id"], 5)
    manager.post("/api/inventory/movements", json={"variant_id": variant["id"], "movement_type": "salida_venta", "quantity": 2})
    card = manager.get(f"/api/products/{product['id']}/overview").json
    assert card["product"]["brand"] == "MarcaFicticia" and card["product"]["category"] == "Deportivo"
    assert card["totals"]["pairs"] == 3 and card["totals"]["sold_last_30_days"] == 2
    assert card["totals"]["value_at_cost"] == "301.50" and card["totals"]["value_at_price"] == "540.00"
    assert card["sizes"] == ["40", "41"] and card["colors"] == ["Blanco", "Negro"]
    assert card["matrix"]["Negro"]["40"]["stock"] == 3 and card["matrix"]["Negro"]["41"] is None
    assert card["matrix"]["Blanco"]["41"]["variant_id"] == other["id"]
    assert len(card["recent_movements"]) == 2
    stock_items = manager.get("/api/inventory/stock").json["items"]
    sold = {i["sku"]: i["sold_recent"] for i in stock_items}
    assert sold["TEST-001-40-NEG"] == 2 and sold["TEST-001-41-BLA"] == 0


def test_label_reader_returns_product_card(manager, variant):
    manager.patch(f"/api/variants/{variant['id']}", json={"barcode": ean()})
    stock(manager, variant["id"], 4)
    body = manager.post("/api/ocr/analyze", data={"image": (label_image("779000000001"), "e.png")},
                        content_type="multipart/form-data").json
    assert body["method"] == "codigo"
    card = body["cards"][0]
    assert card["product"]["model_name"] == "Modelo Prueba" and card["product"]["brand"] == "MarcaFicticia"
    assert card["totals"]["pairs"] == 4
    assert card["highlight_variant_ids"] == [variant["id"]]


def test_count_identifies_product_from_barcode_in_photo(manager, variant, monkeypatch):
    monkeypatch.setattr("app.ai.routes.get_detector", lambda: FakeDetector())
    manager.patch(f"/api/variants/{variant['id']}", json={"barcode": ean()})
    stock(manager, variant["id"], 6)
    count = manager.post("/api/ai/counts", data={"image": (label_image("779000000001"), "foto.png")},
                         content_type="multipart/form-data").json
    assert count["identified_variant_id"] == variant["id"]
    assert count["identification"]["method"] == "codigo"
    assert count["identified"]["product"]["brand"] == "MarcaFicticia"
    assert count["comparison"]["system_pairs"] == 6 and count["comparison"]["photo_shoes"] == 3
    # Identificar no toca el stock.
    assert manager.get(f"/api/variants/{variant['id']}").json["stock_quantity"] == 6
    # Al conciliar, la variante identificada es la predeterminada.
    manager.post(f"/api/ai/counts/{count['id']}/confirm", json={"pairs_complete": 1, "loose_shoes": 1})
    applied = manager.post(f"/api/ai/counts/{count['id']}/apply", json={"counted_pairs": 5, "reason": "Caja completa"})
    assert applied.status_code == 200 and applied.json["count"]["variant_id"] == variant["id"]
    assert applied.json["movement"]["quantity"] == -1


def test_count_with_live_selection_and_manual_correction(manager, product, variant, monkeypatch):
    monkeypatch.setattr("app.ai.routes.get_detector", lambda: FakeDetector())
    from tests.test_ai import jpeg_bytes
    count = manager.post("/api/ai/counts", data={"image": (jpeg_bytes(), "f.jpg"), "variant_id": str(variant["id"])},
                         content_type="multipart/form-data").json
    assert count["identification"]["method"] == "seleccion_en_vivo"
    other = manager.post(f"/api/products/{product['id']}/variants", json={"sku": "OTRA", "size": "42", "color": "Rojo"}).json
    changed = manager.put(f"/api/ai/counts/{count['id']}/identify", json={"variant_id": other["id"]}).json
    assert changed["identified_sku"] == "OTRA" and changed["identification"]["method"] == "manual"
    assert manager.put(f"/api/ai/counts/{count['id']}/identify", json={"variant_id": 999}).status_code == 404
    bad = manager.post("/api/ai/counts", data={"image": (jpeg_bytes(), "f.jpg"), "variant_id": "999"},
                       content_type="multipart/form-data")
    assert bad.status_code == 422
