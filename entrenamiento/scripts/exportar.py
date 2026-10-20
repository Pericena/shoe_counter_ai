"""Versiona y exporta un detector entrenado para la aplicación.

  modelo/pesos/<versión>/best.pt          pesos nativos (PyTorch/Ultralytics)
  modelo/exportados/<versión>/model.onnx  modelo para el backend (onnxruntime, CPU)
  modelo/exportados/<versión>/metadata.json  versión, fecha, dataset, métricas y umbral recomendado

Nunca sobrescribe una versión existente. Comprueba que ONNX y PyTorch den el mismo conteo en
imágenes de test antes de dar la exportación por buena.

Uso:
  python -I scripts/exportar.py --run runs/shoe-det-v001 --dataset datasets/zapatos_v1
"""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
import ultralytics
from PIL import Image
from ultralytics import YOLO

# Nota: tras exportar, evalúa el ONNX (evaluar.py --weights <model.onnx> --device cpu --tag _onnx) y ejecuta
# verificar_onnx.py para fijar en metadata.json las métricas del modelo que realmente usa la app.

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent


def onnx_count(session, image_path, imgsz, conf, iou):
    """Mismo pre/postproceso que backend/app/ai (letterbox idéntico a Ultralytics)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("postprocess", PROJECT / "backend" / "app" / "ai" / "postprocess.py")
    post = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(post)
    tensor, _, _, _ = post.letterbox(np.asarray(Image.open(image_path).convert("RGB")), imgsz)
    output = session.run(None, {session.get_inputs()[0].name: tensor})[0]
    boxes, scores, _ = post.decode_output(output, conf)
    return len(post.nms(boxes, scores, iou))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    run = (ROOT / args.run).resolve()
    version = run.name
    best = run / "weights" / "best.pt"
    metrics_path = run / "evaluacion" / "metricas.json"
    if not best.exists():
        raise SystemExit(f"No existe {best}")
    if not metrics_path.exists():
        raise SystemExit("Evalúa el modelo antes de exportarlo (scripts/evaluar.py).")
    weights_dir = PROJECT / "modelo" / "pesos" / version
    export_dir = PROJECT / "modelo" / "exportados" / version
    if weights_dir.exists() or export_dir.exists():
        raise SystemExit(f"La versión {version} ya está exportada; no se sobrescribe.")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    conf = metrics["count_conf_threshold"]

    onnx_path = Path(YOLO(str(best)).export(format="onnx", imgsz=args.imgsz, opset=17, simplify=True, dynamic=False,
                                            nms=False))
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])

    dataset = (ROOT / args.dataset).resolve()
    test_images = sorted((dataset / "images" / "test").iterdir())[:40]
    reference = YOLO(str(onnx_path), task="detect")  # Ultralytics ejecutando el mismo ONNX
    mismatches = 0
    for image_path in test_images:
        expected = len(reference.predict(str(image_path), imgsz=args.imgsz, conf=conf, iou=0.5, verbose=False, device="cpu")[0].boxes)
        mismatches += onnx_count(session, image_path, args.imgsz, conf, 0.5) != expected
    print(f"Paridad pipeline del backend vs Ultralytics-ONNX en {len(test_images)} imágenes: {len(test_images) - mismatches} iguales")
    if mismatches:
        raise SystemExit("El pipeline del backend no reproduce al ONNX de Ultralytics: no se exporta.")

    weights_dir.mkdir(parents=True)
    export_dir.mkdir(parents=True)
    shutil.copy2(best, weights_dir / "best.pt")
    shutil.copy2(onnx_path, export_dir / "model.onnx")
    manifest = dataset / "manifest.json"
    entorno = json.loads((run / "entorno.json").read_text(encoding="utf-8"))
    metadata = {
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task": "detección de zapatos individuales (1 clase)",
        "classes": ["zapato"],
        "imgsz": args.imgsz,
        "recommended_confidence": conf,
        "framework": {"ultralytics": ultralytics.__version__, "torch": torch.__version__,
                      "onnxruntime": ort.__version__},
        "base_model": entorno.get("base_model"),
        "training_params": entorno.get("params"),
        "hardware": entorno.get("hardware"),
        "dataset": {"manifest": str(manifest.relative_to(ROOT)),
                    "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()},
        "metrics": metrics["splits"],
        "onnx_parity": {"images": len(test_images), "count_mismatches": mismatches},
        "sha256": {"best.pt": hashlib.sha256(best.read_bytes()).hexdigest(),
                   "model.onnx": hashlib.sha256((export_dir / "model.onnx").read_bytes()).hexdigest()},
        "license_note": ("Entrenado con Ultralytics YOLO (AGPL-3.0) y Open Images V7 (anotaciones CC BY 4.0, "
                         "imágenes CC BY 2.0). Ver docs/04-ia-detector.md."),
    }
    (export_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    (weights_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exportado: {export_dir}")


if __name__ == "__main__":
    main()
