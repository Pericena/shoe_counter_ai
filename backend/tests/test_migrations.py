"""Comprueba que las migraciones crean el esquema completo desde cero y se pueden revertir."""
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect

from app import create_app
from app.extensions import db

EXPECTED_TABLES = {"suppliers", "products", "product_variants", "inventory_movements"}


def test_upgrade_and_downgrade(tmp_path):
    app = create_app("testing", {
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'migr.db'}",
        "STORAGE_DIR": tmp_path / "storage",
    })
    with app.app_context():
        upgrade()
        assert EXPECTED_TABLES <= set(inspect(db.engine).get_table_names())
        downgrade(revision="base")
        assert not EXPECTED_TABLES & set(inspect(db.engine).get_table_names())
