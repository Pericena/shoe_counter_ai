import pytest

from app import create_app


def test_health_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "database": "ok"}


def test_security_headers(client):
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_missing_config_fails_fast():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production", {"SECRET_KEY": None, "SQLALCHEMY_DATABASE_URI": None})


def test_example_secret_rejected():
    with pytest.raises(RuntimeError, match="valor de ejemplo"):
        create_app("production", {"SECRET_KEY": "cambia-esta-clave", "SQLALCHEMY_DATABASE_URI": "sqlite://"})


def test_unknown_api_route_returns_json_404(client):
    response = client.get("/api/no-existe")
    assert response.status_code == 404
    assert "error" in response.json


def test_path_traversal_blocked(client):
    response = client.get("/../backend/app/config.py")
    assert response.status_code == 404
