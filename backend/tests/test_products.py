def test_create_and_get_product(client, product):
    response = client.get(f"/api/products/{product['id']}")
    assert response.status_code == 200
    assert response.json["brand"] == "MarcaFicticia"
    assert response.json["category"] == "Deportivo"
    assert response.json["variants"] == []


def test_product_requires_fields(client):
    response = client.post("/api/products", json={"brand": ""})
    assert response.status_code == 422
    assert set(response.json["details"]) >= {"code", "brand_id", "model_name"}


def test_duplicate_product_code_conflict(client, product, brand):
    response = client.post("/api/products", json={"code": "TEST-001", "brand_id": brand["id"], "model_name": "Y"})
    assert response.status_code == 409


def test_variant_starts_with_zero_stock(variant):
    assert variant["stock_quantity"] == 0
    assert variant["stock_state"] == "agotado"
    assert variant["cost"] == "100.50"


def test_variant_size_color_unique_per_product(client, product, variant):
    response = client.post(f"/api/products/{product['id']}/variants",
                           json={"sku": "OTRO-SKU", "size": "40", "color": "Negro"})
    assert response.status_code == 409


def test_same_size_other_color_allowed(client, product, variant):
    response = client.post(f"/api/products/{product['id']}/variants",
                           json={"sku": "TEST-001-40-BLA", "size": "40", "color": "Blanco"})
    assert response.status_code == 201


def test_stock_cannot_be_set_directly(client, product, variant):
    response = client.patch(f"/api/variants/{variant['id']}", json={"stock_quantity": 50})
    assert response.status_code == 422
    response = client.post(f"/api/products/{product['id']}/variants",
                           json={"sku": "S2", "size": "41", "color": "Negro", "stock_quantity": 5})
    assert response.status_code == 422


def test_negative_price_rejected(client, product):
    response = client.post(f"/api/products/{product['id']}/variants",
                           json={"sku": "S3", "size": "42", "color": "Rojo", "price": -1})
    assert response.status_code == 422
    assert "price" in response.json["details"]


def test_variant_for_missing_product(client):
    response = client.post("/api/products/999/variants", json={"sku": "S", "size": "1", "color": "c"})
    assert response.status_code == 404


def test_product_search(client, product):
    assert client.get("/api/products?q=prueba").json["total"] == 1
    assert client.get("/api/products?q=inexistente").json["total"] == 0


def test_supplier_link(client, brand):
    supplier = client.post("/api/suppliers", json={"name": "Proveedor Ficticio"}).json
    response = client.post("/api/products", json={
        "code": "TEST-002", "brand_id": brand["id"], "model_name": "M", "supplier_id": supplier["id"]})
    assert response.status_code == 201
    assert response.json["supplier_name"] == "Proveedor Ficticio"
    bad = client.post("/api/products", json={"code": "TEST-003", "brand_id": brand["id"], "model_name": "M",
                                             "supplier_id": 999})
    assert bad.status_code == 404
