"""Conteo inteligente. El detector real se prueba aparte (scripts de entrenamiento); aquí se usa un
detector de PRUEBA inyectado solo en los tests para verificar el flujo, y el caso sin modelo."""
import io
import json

import numpy as np
import pytest
from PIL import Image

from app.ai import detector as detector_module
from app.ai.postprocess import decode_output, nms
from app.inventory.models import InventoryMovement
from app.extensions import db


def jpeg_bytes(size=(320, 240), color=(200, 180, 160)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    buffer.seek(0)
    return buffer


def upload(api, data=None, name="foto.jpg"):
    return api.post("/api/ai/counts", data={"image": (data or jpeg_bytes(), name)},
                    content_type="multipart/form-data")


class FakeDetector:
    """Solo para pruebas: devuelve tres cajas fijas."""
    version = "detector-de-prueba"

    def predict(self, image, conf, iou):
        boxes = [{"x1": 0.1, "y1": 0.1, "x2": 0.3, "y2": 0.3, "confidence": 0.9, "label": "zapato"},
                 {"x1": 0.4, "y1": 0.1, "x2": 0.6, "y2": 0.3, "confidence": 0.8, "label": "zapato"},
                 {"x1": 0.7, "y1": 0.6, "x2": 0.9, "y2": 0.9, "confidence": 0.4, "label": "zapato"}]
        return boxes, 12


@pytest.fixture()
def fake_model(monkeypatch):
    monkeypatch.setattr("app.ai.routes.get_detector", lambda: FakeDetector())


def test_status_without_model(manager):
    status = manager.get("/api/ai/status").json
    assert status["installed"] is False
    assert "No hay ningún modelo" in status["message"]


def test_count_without_model_is_manual(manager):
    response = upload(manager)
    assert response.status_code == 201
    body = response.json
    assert body["model_version"] is None
    assert body["detected_count"] is None
    assert body["detections"] == []
    assert "manual" in body["message"]


def test_rejects_non_images(manager):
    fake = io.BytesIO(b"esto no es una imagen")
    assert upload(manager, fake, "foto.jpg").status_code == 415
    assert upload(manager, jpeg_bytes(), "script.exe").status_code == 415
    assert manager.post("/api/ai/counts", data={}, content_type="multipart/form-data").status_code == 422


def test_image_is_reencoded_without_metadata(manager, app):
    buffer = io.BytesIO()
    image = Image.new("RGB", (64, 64))
    exif = Image.Exif()
    exif[0x010F] = "CamaraFicticia"
    image.save(buffer, "JPEG", exif=exif)
    buffer.seek(0)
    body = upload(manager, buffer).json
    stored = manager.get(body["image_url"])
    assert stored.status_code == 200
    assert b"CamaraFicticia" not in stored.data


def test_full_flow_with_model(manager, variant, fake_model):
    vid = variant["id"]
    manager.post("/api/inventory/movements", json={"variant_id": vid, "movement_type": "entrada_compra", "quantity": 5})
    count = upload(manager).json
    assert count["model_version"] == "detector-de-prueba"
    assert count["detected_count"] == 3
    assert count["status"] == "revision"
    # Subir la foto NO cambia el stock.
    assert manager.get(f"/api/variants/{vid}").json["stock_quantity"] == 5

    model_ids = [d["id"] for d in count["detections"]]
    review = manager.put(f"/api/ai/counts/{count['id']}/review", json={"detections": [
        {"id": model_ids[0], "source": "modelo", "accepted": True},
        {"id": model_ids[1], "source": "modelo", "accepted": True},
        {"id": model_ids[2], "source": "modelo", "accepted": False},  # falso positivo
        {"source": "manual", "x1": 0.05, "y1": 0.5, "x2": 0.2, "y2": 0.8},  # zapato omitido
        {"source": "manual", "x1": 0.25, "y1": 0.5, "x2": 0.4, "y2": 0.8},
    ]})
    assert review.status_code == 200
    assert review.json["accepted_count"] == 4
    assert review.json["rejected_count"] == 1
    assert review.json["manual_added"] == 2

    bad = manager.post(f"/api/ai/counts/{count['id']}/confirm", json={"pairs_complete": 2, "loose_shoes": 1})
    assert bad.status_code == 422  # 2*2+1 != 4
    ok = manager.post(f"/api/ai/counts/{count['id']}/confirm", json={"pairs_complete": 2, "loose_shoes": 0})
    assert ok.status_code == 200
    assert ok.json["confirmed_shoes"] == 4
    assert manager.get(f"/api/variants/{vid}").json["stock_quantity"] == 5  # confirmar tampoco cambia stock

    applied = manager.post(f"/api/ai/counts/{count['id']}/apply",
                           json={"variant_id": vid, "counted_pairs": 2, "reason": "Estante A, conteo completo"})
    assert applied.status_code == 200
    assert applied.json["count"]["status"] == "aplicado"
    assert applied.json["count"]["difference"] == -3
    movement = applied.json["movement"]
    assert movement["movement_type"] == "conteo_fisico"
    assert movement["quantity"] == -3
    assert movement["user"] == "inventario_prueba"
    assert movement["count_id"] == count["id"]
    assert "Conteo inteligente" in movement["reason"]
    assert manager.get(f"/api/variants/{vid}").json["stock_quantity"] == 2
    # No se puede aplicar dos veces.
    again = manager.post(f"/api/ai/counts/{count['id']}/apply",
                         json={"variant_id": vid, "counted_pairs": 2, "reason": "x"})
    assert again.status_code == 409
    assert manager.get("/api/inventory/reconciliation").json["ok"] is True


def test_operator_cannot_confirm_or_apply(operator, manager, fake_model):
    count = upload(operator).json
    assert operator.post(f"/api/ai/counts/{count['id']}/confirm",
                         json={"pairs_complete": 1, "loose_shoes": 1}).status_code == 403
    assert manager.post(f"/api/ai/counts/{count['id']}/confirm",
                        json={"pairs_complete": 1, "loose_shoes": 1}).status_code == 200
    assert operator.post(f"/api/ai/counts/{count['id']}/apply",
                         json={"variant_id": 1, "counted_pairs": 1, "reason": "x"}).status_code == 403


def test_viewer_cannot_upload(viewer):
    assert upload(viewer).status_code == 403


def test_discard_requires_reason(manager, fake_model):
    count = upload(manager).json
    assert manager.post(f"/api/ai/counts/{count['id']}/discard", json={}).status_code == 422
    response = manager.post(f"/api/ai/counts/{count['id']}/discard", json={"reason": "Foto borrosa"})
    assert response.json["status"] == "descartado"


def test_review_rejects_invalid_boxes(manager, fake_model):
    count = upload(manager).json
    response = manager.put(f"/api/ai/counts/{count['id']}/review",
                           json={"detections": [{"source": "manual", "x1": "a", "y1": 0, "x2": 1, "y2": 1}]})
    assert response.status_code == 422


def test_annotated_image(manager, fake_model):
    count = upload(manager).json
    response = manager.get(f"/api/ai/counts/{count['id']}/annotated.jpg")
    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"


def test_count_list_and_reports(manager, fake_model):
    count = upload(manager).json
    manager.post(f"/api/ai/counts/{count['id']}/confirm", json={"pairs_complete": 1, "loose_shoes": 1})
    listing = manager.get("/api/ai/counts").json
    assert listing["total"] == 1
    summary = manager.get("/api/reports/counts").json
    assert summary["accuracy"]["mae"] == 0
    assert summary["by_status"]["confirmado"] == 1


def test_private_count_image_requires_login(manager, anonymous, fake_model):
    count = upload(manager).json
    assert anonymous.get(count["image_url"]).status_code == 401


# ---------- Postproceso ONNX (unidad) ----------

def test_decode_raw_yolo_output_and_nms():
    # (1, 5, N): cx, cy, w, h, score para una clase.
    raw = np.array([[[100, 102, 300], [100, 101, 300], [50, 50, 40], [50, 50, 40], [0.9, 0.8, 0.2]]], dtype=np.float32)
    boxes, scores, labels = decode_output(raw, conf=0.25)
    assert len(boxes) == 2  # la de 0.2 queda fuera
    keep = nms(boxes, scores, 0.5)
    assert len(keep) == 1  # las dos primeras se solapan casi por completo


def test_decode_nms_output_format():
    raw = np.zeros((1, 300, 6), dtype=np.float32)
    raw[0, 0] = [10, 10, 50, 50, 0.9, 0]
    raw[0, 1] = [60, 60, 90, 90, 0.1, 0]
    boxes, scores, _ = decode_output(raw, conf=0.25)
    assert len(boxes) == 1


def test_model_discovery(tmp_path, app):
    version = tmp_path / "modelos" / "shoe-det-v999"
    version.mkdir(parents=True)
    (version / "model.onnx").write_bytes(b"no-es-un-modelo")
    (version / "metadata.json").write_text(json.dumps({"version": "shoe-det-v999", "created_at": "2026-01-01"}))
    app.config["AI_MODELS_DIR"] = tmp_path / "modelos"
    status, chosen = detector_module.model_status()
    assert status["installed"] is True
    assert status["version"] == "shoe-det-v999"
    # Un archivo de modelo dañado produce un error controlado, no detecciones inventadas.
    with pytest.raises(detector_module.ModelUnavailable):
        detector_module.get_detector()


def test_corrupt_model_falls_back_to_manual(manager, app, tmp_path):
    version = tmp_path / "modelos" / "roto"
    version.mkdir(parents=True)
    (version / "model.onnx").write_bytes(b"x")
    (version / "metadata.json").write_text("{}")
    app.config["AI_MODELS_DIR"] = tmp_path / "modelos"
    body = upload(manager).json
    assert body["detected_count"] is None
    assert db.session.query(InventoryMovement).count() == 0


def test_export_dataset_cli(manager, app, tmp_path, fake_model):
    count = upload(manager).json
    ids = [d["id"] for d in count["detections"]]
    manager.put(f"/api/ai/counts/{count['id']}/review", json={"detections": [
        {"id": ids[0], "source": "modelo", "accepted": True}, {"id": ids[1], "source": "modelo", "accepted": True},
        {"id": ids[2], "source": "modelo", "accepted": False}]})
    manager.post(f"/api/ai/counts/{count['id']}/confirm", json={"pairs_complete": 1, "loose_shoes": 0})
    out = tmp_path / "dataset_tienda"
    result = app.test_cli_runner().invoke(args=["ai", "export-dataset", "--out", str(out)])
    assert result.exit_code == 0, result.output
    labels = (out / "labels" / f"tienda_conteo_{count['id']:06d}.txt").read_text().splitlines()
    assert len(labels) == 2  # la caja rechazada no se exporta
    again = app.test_cli_runner().invoke(args=["ai", "export-dataset", "--out", str(out)])
    assert again.exit_code != 0  # no sobrescribe


def test_inference_failure_falls_back_to_manual(manager, monkeypatch):
    class BrokenDetector:
        version = "detector-roto"

        def predict(self, image, conf, iou):
            raise RuntimeError("fallo simulado de inferencia")

    monkeypatch.setattr("app.ai.routes.get_detector", lambda: BrokenDetector())
    body = upload(manager).json
    assert body["detected_count"] is None and body["model_version"] is None
    assert "falló" in body["message"]


def test_letterbox_matches_ultralytics_geometry():
    from app.ai.postprocess import letterbox
    rgb = np.zeros((240, 320, 3), dtype=np.uint8)
    tensor, scale, pad_x, pad_y = letterbox(rgb, 640)
    assert tensor.shape == (1, 3, 640, 640) and tensor.dtype == np.float32
    assert scale == 2.0 and pad_x == 0 and pad_y == 80
    assert abs(float(tensor[0, 0, 0, 0]) - 114 / 255) < 1e-6  # relleno gris 114 como en entrenamiento
    tensor, scale, pad_x, pad_y = letterbox(np.zeros((101, 333, 3), dtype=np.uint8), 640)
    assert tensor.shape == (1, 3, 640, 640)


def test_model_recommended_confidence_used(app, tmp_path):
    version = tmp_path / "modelos" / "shoe-det-v777"
    version.mkdir(parents=True)
    (version / "model.onnx").write_bytes(b"x")
    (version / "metadata.json").write_text(json.dumps({"version": "shoe-det-v777", "recommended_confidence": 0.25}))
    app.config["AI_MODELS_DIR"] = tmp_path / "modelos"
    app.config["AI_CONFIDENCE"] = None
    assert detector_module.model_status()[0]["confidence_threshold"] == 0.25
    app.config["AI_CONFIDENCE"] = 0.5  # fijado explícitamente: prevalece
    assert detector_module.model_status()[0]["confidence_threshold"] == 0.5
