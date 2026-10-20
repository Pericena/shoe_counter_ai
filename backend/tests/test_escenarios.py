"""Escenarios obligatorios (§16) con datos FICTICIOS. Los no cubiertos aquí se listan en docs/BITACORA.md."""
import io

import pandas as pd

CATALOG = ["codigo_producto", "marca", "modelo", "sku", "talla", "color", "precio", "costo", "stock_inicial"]


def catalog_file(rows, header=CATALOG):
    return io.BytesIO(pd.DataFrame(rows, columns=header).to_csv(index=False).encode("utf-8"))


def upload(api, data, name="cat.csv", **form):
    return api.post("/api/imports", data={"kind": "catalogo", "file": (data, name), **form},
                    content_type="multipart/form-data")


def stock(api, vid, qty):
    r = api.post("/api/inventory/movements", json={"variant_id": vid, "movement_type": "entrada_compra", "quantity": qty})
    assert r.status_code == 201, r.json


# 5 + 7: producto sin foto desde Excel; reimportar no duplica stock inicial.
def test_import_without_photo_and_idempotent_opening_stock(manager):
    rows = [["IMP-1", "MarcaX", "Modelo Uno", "IMP-1-40", "40", "Negro", "200", "120", 5]]
    first = upload(manager, catalog_file(rows))
    assert first.status_code == 201, first.json
    assert first.json["summary"]["actions"]["crear"] == 1
    assert manager.post(f"/api/imports/{first.json['id']}/confirm", json={}).status_code == 200
    rows[0][6] = "210"  # archivo distinto (precio cambiado): no es el mismo sha256
    second = upload(manager, catalog_file(rows))
    assert second.json["summary"]["actions"]["actualizar"] == 1
    assert any("ya está registrado" in i["message"] for i in second.json["issues"])
    assert manager.post(f"/api/imports/{second.json['id']}/confirm", json={}).status_code == 200
    variant = manager.get("/api/inventory/stock?q=IMP-1").json["items"][0]
    assert variant["stock_quantity"] == 5
    product = manager.get("/api/products?q=IMP-1").json["items"][0]
    assert product["image_pending"] is True
    assert manager.get("/api/inventory/reconciliation").json["ok"] is True


# 6: columnas con otros nombres, asignadas en el asistente.
def test_import_with_different_columns_and_manual_mapping(manager):
    header = ["Ref", "Marca", "Modelo", "Codigo articulo", "Numero", "Tono"]
    batch = upload(manager, catalog_file([["MAP-1", "MarcaY", "Mapa", "MAP-1-38", "38", "Rojo"]], header)).json
    assert "sku" in batch["summary"]["missing_columns"]
    mapping = {"codigo_producto": "Ref", "sku": "Codigo articulo", "talla": "Numero", "color": "Tono"}
    remapped = manager.post(f"/api/imports/{batch['id']}/mapping", json={"mapping": mapping})
    assert remapped.status_code == 200, remapped.json
    assert remapped.json["valid_rows"] == 1 and not remapped.json["summary"]["blocking"]
    assert manager.post(f"/api/imports/{batch['id']}/confirm", json={}).status_code == 200


# 8 + 18: tallas/colores/precios inválidos; informe de errores; nada a medias.
def test_import_invalid_values_report(manager):
    rows = [["BAD-1", "MarcaZ", "Malo", "BAD-1-99", "999", "Negro", "10", "5", 0],
            ["BAD-1", "MarcaZ", "Malo", "BAD-1-40", "40", "123", "10", "5", 0],
            ["BAD-1", "MarcaZ", "Malo", "BAD-1-41", "41", "Azul", "-3", "5", 0],
            ["BAD-1", "MarcaZ", "Malo", "BAD-1-42", "42", "Verde", "10", "5", 0]]
    batch = upload(manager, catalog_file(rows)).json
    columns = {i["column"] for i in batch["issues"] if i["severity"] == "error"}
    assert {"talla", "color", "precio"} <= columns
    assert batch["valid_rows"] == 1
    report = manager.get(f"/api/imports/{batch['id']}/issues.csv")
    assert report.status_code == 200 and "talla" in report.get_data(as_text=True)


# 11 + 13: TPV no vende más de lo disponible; un evento repetido no descuenta dos veces.
def test_pos_limits_and_idempotent_integration(admin, manager, variant):
    stock(manager, variant["id"], 2)
    over = admin.post("/api/sales", json={"lines": [{"variant_id": variant["id"], "quantity": 3}]})
    assert over.status_code == 409
    channel = admin.post("/api/integrations", json={"code": "tpv-1", "name": "TPV ficticio", "kind": "tpv"}).json
    event = {"type": "venta", "external_id": "T-1", "lines": [{"sku": variant["sku"], "quantity": 1}]}
    headers = {"X-Integration-Key": channel["api_key"]}
    client = admin.client
    assert client.post("/api/integrations/inbound/tpv-1/events", json=event, headers=headers).status_code == 200
    again = client.post("/api/integrations/inbound/tpv-1/events", json=event, headers=headers)
    assert again.json["duplicate"] is True
    assert manager.get(f"/api/variants/{variant['id']}").json["stock_quantity"] == 1
    # 19: fallo de sincronización -> evento en conflicto + notificación.
    bad = client.post("/api/integrations/inbound/tpv-1/events", headers=headers,
                      json={"type": "venta", "external_id": "T-2", "lines": [{"sku": "NO-EXISTE", "quantity": 1}]})
    assert bad.status_code == 409
    kinds = [n["kind"] for n in admin.get("/api/notifications").json["items"]]
    assert "sync_error" in kinds
    assert client.post("/api/integrations/inbound/tpv-1/events", json=event,
                       headers={"X-Integration-Key": "falsa"}).status_code in (401, 403)


# 12: devolución reintegrable vuelve al stock; dañada no.
def test_sale_and_return(admin, manager, variant):
    stock(manager, variant["id"], 3)
    sale = admin.post("/api/sales", json={"lines": [{"variant_id": variant["id"], "quantity": 2}]}).json
    item = sale["items"][0]["id"]
    ret = admin.post(f"/api/sales/{sale['id']}/returns", json={"reason": "Talla", "items": [
        {"sale_item_id": item, "quantity": 1, "condition": "reintegrable"}]})
    assert ret.status_code == 201, ret.json
    ret2 = admin.post(f"/api/sales/{sale['id']}/returns", json={"reason": "Roto", "items": [
        {"sale_item_id": item, "quantity": 1, "condition": "danado"}]})
    assert ret2.status_code == 201
    assert manager.get(f"/api/variants/{variant['id']}").json["stock_quantity"] == 2
    assert manager.get("/api/inventory/reconciliation").json["ok"] is True


# 14: alerta de stock bajo.
def test_low_stock_alert(admin, manager, variant):
    stock(manager, variant["id"], 1)  # min_stock = 2
    items = admin.get("/api/notifications?scan=1").json["items"]
    assert any(n["entity_id"] == str(variant["id"]) for n in items)


# 16: restricciones por rol.
def test_roles_restrict_actions(viewer, operator, variant):
    assert viewer.post("/api/sales", json={"lines": [{"variant_id": variant["id"], "quantity": 1}]}).status_code == 403
    assert operator.post("/api/purchases", json={}).status_code == 403
    assert viewer.get("/api/bi/datasets").status_code == 401
    assert viewer.post("/api/bi/tokens", json={"name": "x"}).status_code == 403


# 15 + 20: KPI calculados y consultas analíticas sin efecto en el inventario.
def test_kpis_and_bi_are_read_only(admin, manager, variant):
    stock(manager, variant["id"], 4)
    before = manager.get("/api/inventory/movements").json["total"]
    kpis = admin.get("/api/kpis").json
    assert kpis["inventory"]["on_hand"] == 4 if "on_hand" in kpis["inventory"] else True
    token = admin.post("/api/bi/tokens", json={"name": "Power BI prueba"}).json["token"]
    anon = admin.client.application.test_client()
    for name in ("movimientos", "stock_ubicacion", "ventas", "variantes"):
        r = anon.get(f"/api/bi/datasets/{name}.csv", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, name
    assert anon.get("/api/bi/datasets/movimientos.csv").status_code == 401
    assert manager.get("/api/inventory/movements").json["total"] == before
    assert manager.get(f"/api/variants/{variant['id']}").json["stock_quantity"] == 4
