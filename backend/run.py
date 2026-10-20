"""Punto de entrada: `flask --app run ...`, gunicorn (`run:app`) o `python run.py` en Windows."""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    from waitress import serve

    serve(app, host="127.0.0.1", port=8088)
