"""Pruebas con SQLite en memoria por defecto.

Para probar contra PostgreSQL real: definir TEST_DATABASE_URL apuntando a una base VACÍA y
dedicada a pruebas (las pruebas borran sus tablas). Ver docs/08-pruebas.md.
Todos los datos usados en las pruebas son FICTICIOS.
"""
import pytest

from app import create_app
from app.auth.models import User
from app.auth.services import get_role, hash_password, seed_roles
from app.extensions import db

PASSWORD = "Prueba-Ficticia-123"


@pytest.fixture()
def app(tmp_path):
    app = create_app("testing", {"STORAGE_DIR": tmp_path / "storage", "AI_MODELS_DIR": tmp_path / "modelos"})
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed_roles()
        yield app
        db.session.remove()
        db.drop_all()


class ApiClient:
    """Cliente de pruebas que gestiona la sesión y el token CSRF como lo hace el navegador."""

    def __init__(self, app):
        self.client = app.test_client()
        self.csrf = None
        self.refresh_csrf()

    def refresh_csrf(self):
        self.csrf = self.client.get("/api/auth/session").json["csrf_token"]

    def login(self, username, password=PASSWORD):
        response = self.post("/api/auth/login", json={"username": username, "password": password})
        if response.status_code == 200:
            self.csrf = response.json["csrf_token"]
        return response

    def _headers(self, kwargs):
        headers = kwargs.pop("headers", {}) or {}
        headers.setdefault("X-CSRF-Token", self.csrf)
        return headers

    def get(self, *args, **kwargs):
        return self.client.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self._headers(kwargs), **kwargs)

    def put(self, *args, **kwargs):
        return self.client.put(*args, headers=self._headers(kwargs), **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self._headers(kwargs), **kwargs)

    def delete(self, *args, **kwargs):
        return self.client.delete(*args, headers=self._headers(kwargs), **kwargs)


def make_user(username, role, must_change=False):
    user = User(username=username, full_name=f"Usuario ficticio {role}", role=get_role(role),
                password_hash=hash_password(PASSWORD), must_change_password=must_change)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def users(app):
    return {role: make_user(f"{role}_prueba", role) for role in ("admin", "inventario", "operador", "consulta")}


def logged(app, username):
    api = ApiClient(app)
    response = api.login(username)
    assert response.status_code == 200, response.json
    return api


@pytest.fixture()
def admin(app, users):
    return logged(app, "admin_prueba")


@pytest.fixture()
def manager(app, users):
    return logged(app, "inventario_prueba")


@pytest.fixture()
def operator(app, users):
    return logged(app, "operador_prueba")


@pytest.fixture()
def viewer(app, users):
    return logged(app, "consulta_prueba")


@pytest.fixture()
def anonymous(app):
    return ApiClient(app)


# Compatibilidad con las pruebas de inventario existentes: `client` es un encargado de inventario.
@pytest.fixture()
def client(manager):
    return manager


@pytest.fixture()
def brand(client):
    response = client.post("/api/brands", json={"name": "MarcaFicticia"})
    assert response.status_code == 201, response.json
    return response.json


@pytest.fixture()
def product(client, brand):
    """Producto y variante FICTICIOS para pruebas."""
    category = client.post("/api/categories", json={"name": "Deportivo"}).json
    response = client.post("/api/products", json={
        "code": "TEST-001", "brand_id": brand["id"], "model_name": "Modelo Prueba",
        "category_id": category["id"], "footwear_type": "Zapatilla",
    })
    assert response.status_code == 201, response.json
    return response.json


@pytest.fixture()
def variant(client, product):
    response = client.post(f"/api/products/{product['id']}/variants", json={
        "sku": "TEST-001-40-NEG", "size": "40", "color": "Negro",
        "cost": "100.50", "price": "180", "min_stock": 2,
    })
    assert response.status_code == 201, response.json
    return response.json
