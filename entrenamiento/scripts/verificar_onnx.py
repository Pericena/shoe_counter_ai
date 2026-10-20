"""Verifica el modelo ONNX exportado tal como lo ejecuta el backend y actualiza su metadata.json.

1. Paridad: conteo del pipeline del BACKEND (backend/app/ai/postprocess.py: letterbox + decodificación + NMS)
   frente a Ultralytics ejecutando el mismo ONNX, en test y test_externo. Deben coincidir.
2. Informa también la concordancia PyTorch (.pt, letterbox rectangular) vs ONNX (entrada fija 640×640),
   que puede diferir: por eso las métricas válidas para la app son las del ONNX (evaluacion_onnx).
3. Fusiona en metadata.json (de modelo/exportados y modelo/pesos) las métricas de
   runs/<versión>/evaluacion_onnx/metricas.json y el umbral recomendado elegido en validación.
   No modifica pesos ni el archivo ONNX.

Uso:
  python -I scripts/verificar_onnx.py --version shoe-det-v001 --dataset datasets/zapatos_v1
"""
import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent


def load_backend_postprocess():
    spec = importlib.util.spec_from_file_location("postprocess", PROJECT / "backend" / "app" / "ai" / "postprocess.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backend_count(post, session, image_path, imgsz, conf, iou):
    rgb = np.asarray(Image.open(image_path).convert("RGB"))
    tensor, _, _, _ = post.letterbox(rgb, imgsz)
    output = session.run(None, {session.get_inputs()[0].name: tensor})[0]
    boxes, scores, _ = post.decode_output(output, conf)
    return len(post.nms(boxes, scores, iou))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--limit", type=int, default=60, help="imágenes por partición para la paridad")
    args = parser.parse_args()

    export_dir = PROJECT / "modelo" / "exportados" / args.version
    weights_dir = PROJECT / "modelo" / "pesos" / args.version
    onnx_path = export_dir / "model.onnx"
    meta = json.loads((export_dir / "metadata.json").read_text(encoding="utf-8"))
    imgsz = meta.get("imgsz", 640)
    onnx_metrics_path = ROOT / "runs" / args.version / "evaluacion_onnx" / "metricas.json"
    onnx_metrics = json.loads(onnx_metrics_path.read_text(encoding="utf-8")) if onnx_metrics_path.exists() else None
    conf = onnx_metrics["count_conf_threshold"] if onnx_metrics else meta["recommended_confidence"]

    post = load_backend_postprocess()
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    ultra_onnx = YOLO(str(onnx_path), task="detect")
    ultra_pt = YOLO(str(weights_dir / "best.pt"))
    dataset = (ROOT / args.dataset).resolve()
    parity = {}
    for split in ("test", "test_externo"):
        folder = dataset / "images" / split
        if not folder.exists():
            continue
        images = sorted(folder.iterdir())[:args.limit]
        same_backend = same_pt = 0
        for image_path in images:
            expected = len(ultra_onnx.predict(str(image_path), imgsz=imgsz, conf=conf, iou=0.5, verbose=False, device="cpu")[0].boxes)
            ours = backend_count(post, session, image_path, imgsz, conf, 0.5)
            pt = len(ultra_pt.predict(str(image_path), imgsz=imgsz, conf=conf, iou=0.5, verbose=False, device="cpu")[0].boxes)
            same_backend += ours == expected
            same_pt += pt == expected
        parity[split] = {"images": len(images), "backend_vs_ultralytics_onnx_equal": same_backend,
                         "pytorch_vs_onnx_equal": same_pt}
        print(split, parity[split])

    meta["onnx_parity"] = {"checked_at": datetime.now(timezone.utc).isoformat(), "confidence": conf, "splits": parity,
                           "note": ("backend_vs_ultralytics_onnx debe ser igual al total. pytorch_vs_onnx puede "
                                    "diferir (letterbox rectangular vs entrada fija 640): la app usa el ONNX.")}
    if onnx_metrics:
        meta["metrics_pytorch"] = meta.get("metrics_pytorch", meta.get("metrics"))
        meta["metrics"] = onnx_metrics["splits"]
        meta["metrics_source"] = "ONNX exportado (el que ejecuta la app), evaluado con scripts/evaluar.py --tag _onnx"
        meta["recommended_confidence"] = onnx_metrics["count_conf_threshold"]
    for folder in (export_dir, weights_dir):
        (folder / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = all(p["backend_vs_ultralytics_onnx_equal"] == p["images"] for p in parity.values())
    print("PARIDAD BACKEND:", "OK" if ok else "DIFERENCIAS", "| umbral recomendado:", meta["recommended_confidence"])
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
