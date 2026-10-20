"""Cámara en vivo (detección sin guardar) y lector de etiquetas (códigos + OCR). Datos FICTICIOS."""
import io

import numpy as np
import zxingcpp
from PIL import Image, ImageDraw, ImageFont

from app.ai.models import AICount
from app.extensions import db
from app.files.models import StoredFile
from tests.test_ai import FakeDetector, jpeg_bytes


def frame(api, data=None):
    return api.post("/api/ai/detect", data={"frame": (data or jpeg_bytes(), "frame.jpg")},
                    content_type="multipart/form-data")


def test_live_detect_without_model(manager):
    body = frame(manager).json
    assert body["model_installed"] is False and body["detections"] == []


def test_live_detect_does_not_persist(manager, monkeypatch):
    monkeypatch.setattr("app.ai.routes.get_detector", lambda: FakeDetector())
    body = frame(manager).json
    assert body["count"] == 3 and body["model_version"] == "detector-de-prueba"
    assert db.session.query(AICount).count() == 0
    assert db.session.query(StoredFile).count() == 0


def test_live_detect_validation_and_permissions(manager, viewer):
    assert frame(manager, io.BytesIO(b"no es imagen")).status_code == 415
    assert manager.post("/api/ai/detect", data={}, content_type="multipart/form-data").status_code == 422
    assert frame(viewer).status_code == 403


def label_image(barcode_text):
    code = zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(barcode_text, zxingcpp.BarcodeFormat.EAN13), scale=4)
    code = Image.fromarray(np.asarray(code)).convert("RGB")
    canvas = Image.new("RGB", (1000, 520), "white")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 44)
    except OSError:
        font = ImageFont.load_default(size=44)
    draw.text((30, 20), "MarcaFicticia", fill="black", font=font)
    draw.text((30, 80), "TALLA: 40", fill="black", font=font)
    draw.text((420, 80), "Color: NEGRO", fill="black", font=font)
    draw.text((30, 140), "PRECIO 180.00", fill="black", font=font)
    canvas.paste(code, (30, 200))
    buffer = io.BytesIO()
    canvas.save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def test_label_reader_barcode_and_text(manager, variant):
    ean = zxingcpp.create_barcode("779000000001", zxingcpp.BarcodeFormat.EAN13).text  # con dígito de control
    manager.patch(f"/api/variants/{variant['id']}", json={"barcode": ean})
    response = manager.post("/api/ocr/analyze", data={"image": (label_image("779000000001"), "etiqueta.png")},
                            content_type="multipart/form-data")
    assert response.status_code == 200, response.json
    body = response.json
    assert any(b["text"] == ean for b in body["barcodes"]), body["barcodes"]
    assert [m["sku"] for m in body["matches"]] == ["TEST-001-40-NEG"]
    assert "MarcaFicticia" in body["fields"]["brands"]
    assert "40" in body["fields"]["sizes"]
    assert "Negro" in body["fields"]["colors"]
    assert "180.00" in body["fields"]["prices"]
    # Solo lectura: no cambia el stock y la imagen queda privada.
    assert manager.get(f"/api/variants/{variant['id']}").json["stock_quantity"] == 0
    assert db.session.get(StoredFile, body["file_id"]).purpose == "etiqueta"


def test_label_reader_rejects_non_images(manager):
    response = manager.post("/api/ocr/analyze", data={"image": (io.BytesIO(b"texto"), "x.jpg")},
                            content_type="multipart/form-data")
    assert response.status_code == 415
