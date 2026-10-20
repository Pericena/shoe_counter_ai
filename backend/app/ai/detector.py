"""Inferencia del detector de zapatos exportado a ONNX (formato de salida YOLOv8/YOLO11).

Cada versión vive en AI_MODELS_DIR/<versión>/ con:
  - model.onnx      pesos exportados (sin NMS integrado)
  - metadata.json   versión, clases, imgsz, dataset y métricas de evaluación

Si no hay modelo, `get_detector()` devuelve None y la API informa "modelo no instalado":
nunca se inventan detecciones.
"""
import json
import threading
import time
from pathlib import Path

import numpy as np
from flask import current_app

from .postprocess import decode_output, nms

_lock = threading.Lock()
_cache = {}


class ModelUnavailable(Exception):
    pass


def available_versions(models_dir):
    models_dir = Path(models_dir)
    if not models_dir.is_dir():
        return []
    versions = []
    for folder in sorted(models_dir.iterdir()):
        meta_path = folder / "metadata.json"
        if folder.is_dir() and (folder / "model.onnx").is_file() and meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            meta.setdefault("version", folder.name)
            versions.append((folder, meta))
    versions.sort(key=lambda item: (item[1].get("created_at", ""), item[0].name))
    return versions


def model_status():
    cfg = current_app.config
    versions = available_versions(cfg["AI_MODELS_DIR"])
    wanted = cfg.get("AI_MODEL_VERSION")
    chosen = None
    if wanted:
        chosen = next((v for v in versions if v[0].name == wanted), None)
    elif versions:
        chosen = versions[-1]
    status = {
        "installed": chosen is not None,
        "versions": [m.get("version") for _, m in versions],
        "requested_version": wanted,
        "confidence_threshold": cfg["AI_CONFIDENCE"],
        "iou_threshold": cfg["AI_IOU"],
        "runtime": "onnxruntime (CPU)",
    }
    if chosen:
        folder, meta = chosen
        status.update({"version": meta.get("version"), "metadata": meta, "path": folder.name})
    elif wanted:
        status["message"] = f"La versión '{wanted}' indicada en AI_MODEL_VERSION no está instalada."
    else:
        status["message"] = ("No hay ningún modelo instalado. Entrena y exporta uno con los scripts de "
                             "entrenamiento/ (ver docs/04-ia-detector.md).")
    return status, chosen


class Detector:
    def __init__(self, folder, meta):
        import onnxruntime as ort

        self.folder = Path(folder)
        self.meta = meta
        self.version = meta.get("version", self.folder.name)
        self.imgsz = int(meta.get("imgsz", 640))
        self.classes = meta.get("classes", ["zapato"])
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(self.folder / "model.onnx"), options,
                                            providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def _letterbox(self, image):
        """Redimensiona manteniendo proporción y rellena con gris 114 (igual que en entrenamiento)."""
        from PIL import Image

        width, height = image.size
        scale = min(self.imgsz / width, self.imgsz / height)
        new_w, new_h = max(1, round(width * scale)), max(1, round(height * scale))
        resized = image.resize((new_w, new_h), Image.BILINEAR)
        canvas = Image.new("RGB", (self.imgsz, self.imgsz), (114, 114, 114))
        pad_x, pad_y = (self.imgsz - new_w) // 2, (self.imgsz - new_h) // 2
        canvas.paste(resized, (pad_x, pad_y))
        array = np.asarray(canvas, dtype=np.float32) / 255.0
        return array.transpose(2, 0, 1)[None], scale, pad_x, pad_y

    def predict(self, image, conf, iou):
        image = image.convert("RGB")
        width, height = image.size
        tensor, scale, pad_x, pad_y = self._letterbox(image)
        started = time.perf_counter()
        output = self.session.run(None, {self.input_name: tensor})[0]
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        boxes, scores, labels = decode_output(output, conf)
        keep = nms(boxes, scores, iou)
        detections = []
        for i in keep:
            x1, y1, x2, y2 = boxes[i]
            x1 = (x1 - pad_x) / scale / width
            x2 = (x2 - pad_x) / scale / width
            y1 = (y1 - pad_y) / scale / height
            y2 = (y2 - pad_y) / scale / height
            x1, y1, x2, y2 = (float(np.clip(v, 0, 1)) for v in (x1, y1, x2, y2))
            if x2 - x1 <= 1e-4 or y2 - y1 <= 1e-4:
                continue
            label_index = int(labels[i])
            label = self.classes[label_index] if label_index < len(self.classes) else str(label_index)
            detections.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                               "confidence": round(float(scores[i]), 4), "label": label})
        detections.sort(key=lambda d: -d["confidence"])
        return detections, elapsed_ms


def get_detector():
    """Devuelve el detector activo (cacheado) o None si no hay modelo instalado."""
    status, chosen = model_status()
    if not chosen:
        return None
    folder, meta = chosen
    model_file = folder / "model.onnx"
    key = (str(model_file), model_file.stat().st_mtime)
    with _lock:
        if key not in _cache:
            _cache.clear()
            try:
                _cache[key] = Detector(folder, meta)
            except Exception as error:  # noqa: BLE001
                raise ModelUnavailable(f"No se pudo cargar el modelo {folder.name}: {error}") from error
        return _cache[key]
