"""Concurrencia real: solo tiene sentido en PostgreSQL (SQLite no aplica SELECT … FOR UPDATE).

Se ejecuta con TEST_DATABASE_URL apuntando a PostgreSQL; en SQLite se omite.
"""
import threading

import pytest

from app.extensions import db
from tests.conftest import ApiClient


@pytest.fixture()
def pg_only(app):
    if db.engine.dialect.name != "postgresql":
        pytest.skip("Requiere PostgreSQL (TEST_DATABASE_URL)")


def test_concurrent_orders_cannot_oversell(pg_only, app, manager, product, variant):
    manager.patch(f"/api/products/{product['id']}", json={"is_published": True})
    manager.post("/api/inventory/movements", json={"variant_id": variant["id"], "movement_type": "entrada_compra",
                                                   "quantity": 1})
    app.config["ORDERS_PER_IP_PER_HOUR"] = 100
    clients = [ApiClient(app) for _ in range(6)]
    barrier = threading.Barrier(len(clients))
    results = []

    def buy(api):
        barrier.wait()
        response = api.post("/api/shop/orders", json={
            "customer_name": "Cliente Ficticio", "customer_email": "c@ejemplo.test",
            "items": [{"variant_id": variant["id"], "quantity": 1}]})
        results.append(response.status_code)

    threads = [threading.Thread(target=buy, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201] + [409] * (len(clients) - 1)
    assert manager.get(f"/api/variants/{variant['id']}").json["stock_quantity"] == 0
    assert manager.get("/api/inventory/reconciliation").json["ok"] is True


def test_concurrent_sales_and_entries_keep_ledger_consistent(pg_only, app, users, variant):
    from tests.conftest import logged
    manager = logged(app, "inventario_prueba")
    manager.post("/api/inventory/movements", json={"variant_id": variant["id"], "movement_type": "entrada_compra",
                                                   "quantity": 10})
    clients = [logged(app, "inventario_prueba") for _ in range(8)]
    barrier = threading.Barrier(len(clients))
    codes = []

    def move(api, index):
        barrier.wait()
        kind = "salida_venta" if index % 2 else "entrada_compra"
        codes.append(api.post("/api/inventory/movements",
                              json={"variant_id": variant["id"], "movement_type": kind, "quantity": 3}).status_code)

    threads = [threading.Thread(target=move, args=(c, i)) for i, c in enumerate(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(code in (201, 409) for code in codes)
    stock = manager.get(f"/api/variants/{variant['id']}").json["stock_quantity"]
    assert stock >= 0
    assert manager.get("/api/inventory/reconciliation").json["ok"] is True
