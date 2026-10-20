"""Autenticación, sesiones, CSRF, límite de intentos, permisos por rol y auditoría. Datos ficticios."""
import pytest

from app.audit.models import AuditLog
from app.auth.models import User
from app.extensions import db
from tests.conftest import PASSWORD, ApiClient, logged, make_user


def test_login_logout(app, users):
    api = ApiClient(app)
    response = api.login("admin_prueba")
    assert response.status_code == 200
    assert response.json["user"]["role"] == "admin"
    assert "users.manage" in response.json["permissions"]
    assert api.get("/api/inventory/stock").status_code == 200
    assert api.post("/api/auth/logout").status_code == 200
    assert api.get("/api/inventory/stock").status_code == 401


def test_wrong_password_and_unknown_user_same_message(app, users):
    api = ApiClient(app)
    bad = api.login("admin_prueba", "incorrecta-123")
    unknown = api.login("no_existe", "incorrecta-123")
    assert bad.status_code == unknown.status_code == 401
    assert bad.json["error"] == unknown.json["error"]


def test_inactive_user_cannot_login(app, users):
    users["consulta"].is_active = False
    db.session.commit()
    assert ApiClient(app).login("consulta_prueba").status_code == 401


def test_session_cookie_flags(app, users):
    api = ApiClient(app)
    response = api.login("admin_prueba")
    cookie = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_lockout_after_repeated_failures(app, users):
    api = ApiClient(app)
    for _ in range(app.config["LOGIN_MAX_FAILURES_USER"]):
        assert api.login("operador_prueba", "incorrecta-123").status_code == 401
    # Bloqueado incluso con la contraseña correcta.
    assert api.login("operador_prueba").status_code == 429


def test_private_routes_require_login(anonymous):
    for path in ("/api/inventory/stock", "/api/products", "/api/users", "/api/audit", "/api/reports/overview",
                 "/api/ai/counts", "/api/imports", "/api/orders", "/api/exports/existencias"):
        assert anonymous.get(path).status_code == 401, path


def test_public_routes(anonymous):
    assert anonymous.get("/api/health").status_code == 200
    assert anonymous.get("/api/shop/products").status_code == 200


def test_csrf_required_for_unsafe_methods(app, users):
    api = ApiClient(app)
    api.login("admin_prueba")
    response = api.client.post("/api/brands", json={"name": "SinToken"})
    assert response.status_code == 403
    response = api.post("/api/brands", json={"name": "ConToken"})
    assert response.status_code == 201


def test_login_requires_csrf(app, users):
    api = ApiClient(app)
    response = api.client.post("/api/auth/login", json={"username": "admin_prueba", "password": PASSWORD})
    assert response.status_code == 403


@pytest.mark.parametrize("role,path,payload,expected", [
    ("consulta", "/api/brands", {"name": "X"}, 403),
    ("operador", "/api/brands", {"name": "X"}, 403),
    ("inventario", "/api/brands", {"name": "X"}, 201),
    ("inventario", "/api/users", {}, 403),
    ("consulta", "/api/inventory/movements", {"variant_id": 1, "movement_type": "entrada_compra", "quantity": 1}, 403),
])
def test_role_permissions(app, users, role, path, payload, expected):
    api = logged(app, f"{role}_prueba")
    assert api.post(path, json=payload).status_code == expected


def test_operator_can_sell_but_not_receive(operator, manager, variant):
    vid = variant["id"]
    assert manager.post("/api/inventory/movements",
                        json={"variant_id": vid, "movement_type": "entrada_compra", "quantity": 5}).status_code == 201
    sale = operator.post("/api/inventory/movements", json={"variant_id": vid, "movement_type": "salida_venta", "quantity": 1})
    assert sale.status_code == 201
    assert sale.json["movement"]["user"] == "operador_prueba"
    entry = operator.post("/api/inventory/movements", json={"variant_id": vid, "movement_type": "entrada_compra", "quantity": 1})
    assert entry.status_code == 403
    adjust = operator.post("/api/inventory/movements",
                           json={"variant_id": vid, "movement_type": "ajuste", "quantity": 1, "reason": "x"})
    assert adjust.status_code == 403


def test_system_movement_types_cannot_be_posted(manager, variant):
    r = manager.post("/api/inventory/movements",
                     json={"variant_id": variant["id"], "movement_type": "salida_pedido", "quantity": 1})
    assert r.status_code == 422


def test_admin_user_management(admin, app):
    created = admin.post("/api/users", json={"username": "nuevo.usuario", "full_name": "Persona Ficticia",
                                            "role": "operador", "password": "Temporal-Ficticia-99"})
    assert created.status_code == 201
    assert created.json["must_change_password"] is True
    weak = admin.post("/api/users", json={"username": "debil", "full_name": "X", "role": "operador",
                                         "password": "123"})
    assert weak.status_code == 422
    duplicate = admin.post("/api/users", json={"username": "nuevo.usuario", "full_name": "X", "role": "operador",
                                              "password": "Temporal-Ficticia-99"})
    assert duplicate.status_code == 409

    # Con contraseña temporal solo puede cambiarla.
    api = ApiClient(app)
    api.login("nuevo.usuario", "Temporal-Ficticia-99")
    assert api.get("/api/inventory/stock").status_code == 403
    changed = api.post("/api/auth/change-password",
                       json={"current_password": "Temporal-Ficticia-99", "new_password": "Definitiva-Ficticia-77"})
    assert changed.status_code == 200
    api.csrf = changed.json["csrf_token"]
    assert api.get("/api/inventory/stock").status_code == 200


def test_password_change_invalidates_other_sessions(app, users):
    first = logged(app, "consulta_prueba")
    second = logged(app, "consulta_prueba")
    response = first.post("/api/auth/change-password",
                          json={"current_password": PASSWORD, "new_password": "OtraClave-Ficticia-55"})
    assert response.status_code == 200
    first.csrf = response.json["csrf_token"]
    assert first.get("/api/inventory/stock").status_code == 200
    assert second.get("/api/inventory/stock").status_code == 401


def test_role_change_takes_effect_immediately(admin, app, users):
    api = logged(app, "inventario_prueba")
    assert api.post("/api/brands", json={"name": "Antes"}).status_code == 201
    uid = users["inventario"].id
    assert admin.patch(f"/api/users/{uid}", json={"role": "consulta"}).status_code == 200
    # La sesión anterior se invalida al cambiar el rol.
    assert api.post("/api/brands", json={"name": "Despues"}).status_code == 401


def test_last_admin_cannot_be_removed(admin, users):
    uid = users["admin"].id
    assert admin.patch(f"/api/users/{uid}", json={"is_active": False}).status_code == 422
    assert admin.patch(f"/api/users/{uid}", json={"role": "consulta"}).status_code == 422


def test_password_reset_without_smtp_is_explicit(anonymous):
    response = anonymous.post("/api/auth/password-reset/request", json={"email": "x@ejemplo.test"})
    assert response.status_code == 200
    assert response.json["email_enabled"] is False


def test_password_reset_token_flow(app, users):
    from app.auth.services import create_reset_token
    user = users["consulta"]
    token = create_reset_token(user)
    db.session.commit()
    api = ApiClient(app)
    assert api.post("/api/auth/password-reset/confirm",
                    json={"token": token, "new_password": "Recuperada-Ficticia-31"}).status_code == 200
    assert api.post("/api/auth/password-reset/confirm",
                    json={"token": token, "new_password": "OtraVez-Ficticia-31"}).status_code == 400
    assert api.login("consulta_prueba", "Recuperada-Ficticia-31").status_code == 200


def test_passwords_are_hashed(users):
    user = db.session.get(User, users["admin"].id)
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("scrypt:")


def test_audit_records_actions(admin, app):
    admin.post("/api/brands", json={"name": "Auditada"})
    ApiClient(app).login("admin_prueba", "incorrecta-123")
    actions = {a.action for a in db.session.query(AuditLog).all()}
    assert {"login", "marca_creada", "login_fallido"} <= actions
    response = admin.get("/api/audit?action=login")
    assert response.status_code == 200
    assert response.json["total"] >= 1


def test_audit_requires_permission(manager):
    assert manager.get("/api/audit").status_code == 403


def test_cli_create_admin(app, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "Consola-Ficticia-2026")
    runner = app.test_cli_runner()
    result = runner.invoke(args=["users", "create-admin", "--username", "jefe"])
    assert result.exit_code == 0, result.output
    assert ApiClient(app).login("jefe", "Consola-Ficticia-2026").status_code == 200
    weak = runner.invoke(args=["users", "create-admin", "--username", "otro"], env={"ADMIN_PASSWORD": "corta"})
    assert weak.exit_code != 0


def test_make_user_helper_must_change(app):
    make_user("temporal", "consulta", must_change=True)
    api = ApiClient(app)
    api.login("temporal")
    assert api.get("/api/products").json["error"].startswith("Debes cambiar")
