def move(client, variant_id, movement_type, **extra):
    return client.post("/api/inventory/movements",
                       json={"variant_id": variant_id, "movement_type": movement_type, **extra})


def stock_of(client, variant_id):
    return client.get(f"/api/variants/{variant_id}").json["stock_quantity"]


def test_entry_and_sale_update_stock_and_history(client, variant):
    vid = variant["id"]
    r = move(client, vid, "entrada_compra", quantity=10, unit_cost="100.50", reference="FAC-FICTICIA-1")
    assert r.status_code == 201
    assert r.json["movement"]["quantity"] == 10
    assert r.json["movement"]["balance_after"] == 10
    assert r.json["movement"]["created_at"].endswith("+00:00")  # fecha con zona (UTC)

    r = move(client, vid, "salida_venta", quantity=3)
    assert r.status_code == 201
    assert r.json["movement"]["quantity"] == -3
    assert stock_of(client, vid) == 7

    history = client.get(f"/api/inventory/movements?variant_id={vid}").json["items"]
    assert [m["quantity"] for m in history] == [-3, 10]


def test_sale_cannot_exceed_stock(client, variant):
    move(client, variant["id"], "entrada_compra", quantity=1)
    r = move(client, variant["id"], "salida_venta", quantity=2)
    assert r.status_code == 409
    assert stock_of(client, variant["id"]) == 1


def test_quantity_must_be_positive_for_entries(client, variant):
    assert move(client, variant["id"], "entrada_compra", quantity=0).status_code == 422
    assert move(client, variant["id"], "entrada_compra", quantity=-5).status_code == 422


def test_adjustment_requires_reason(client, variant):
    assert move(client, variant["id"], "ajuste", quantity=2).status_code == 422
    r = move(client, variant["id"], "ajuste", quantity=2, reason="Par encontrado en bodega")
    assert r.status_code == 201
    assert stock_of(client, variant["id"]) == 2


def test_returns(client, variant):
    vid = variant["id"]
    move(client, vid, "entrada_compra", quantity=5)
    move(client, vid, "salida_venta", quantity=2)
    assert move(client, vid, "devolucion_cliente", quantity=1).status_code == 201
    assert move(client, vid, "devolucion_proveedor", quantity=4).status_code == 201
    assert stock_of(client, vid) == 0


def test_physical_count_records_difference(client, variant):
    vid = variant["id"]
    move(client, vid, "entrada_compra", quantity=10)
    r = move(client, vid, "conteo_fisico", counted_quantity=8)
    assert r.status_code == 201
    assert r.json["movement"]["quantity"] == -2
    assert stock_of(client, vid) == 8

    same = move(client, vid, "conteo_fisico", counted_quantity=8)
    assert same.status_code == 200
    assert same.json["movement"] is None


def test_invalid_movement_type(client, variant):
    r = move(client, variant["id"], "regalo", quantity=1)
    assert r.status_code == 422


def test_missing_variant(client):
    assert move(client, 999, "entrada_compra", quantity=1).status_code == 404


def test_stock_view_states_and_value(client, variant):
    vid = variant["id"]
    move(client, vid, "entrada_compra", quantity=2)
    data = client.get("/api/inventory/stock").json
    assert data["summary"]["pairs"] == 2
    assert data["summary"]["inventory_value_at_cost"] == "201.00"
    assert data["items"][0]["stock_state"] == "bajo"  # 2 <= min_stock 2
    assert len(client.get("/api/inventory/stock?state=bajo").json["items"]) == 1
    assert len(client.get("/api/inventory/stock?state=agotado").json["items"]) == 0
    assert len(client.get("/api/inventory/stock?size=41").json["items"]) == 0


def test_value_flagged_incomplete_without_cost(client, product):
    v = client.post(f"/api/products/{product['id']}/variants",
                    json={"sku": "SIN-COSTO", "size": "38", "color": "Azul"}).json
    move(client, v["id"], "entrada_compra", quantity=3)
    summary = client.get("/api/inventory/stock").json["summary"]
    assert summary["inventory_value_complete"] is False


def test_reconciliation_matches_ledger(client, variant):
    vid = variant["id"]
    move(client, vid, "entrada_compra", quantity=10)
    move(client, vid, "salida_venta", quantity=4)
    move(client, vid, "conteo_fisico", counted_quantity=5)
    result = client.get("/api/inventory/reconciliation").json
    assert result["ok"] is True
    assert result["mismatches"] == []
