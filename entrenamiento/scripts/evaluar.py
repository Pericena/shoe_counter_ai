"""Evalúa un detector entrenado en imágenes NO usadas para entrenar.

Métricas:
  - precision, recall, mAP50 y mAP50-95 (validador de Ultralytics) por partición
  - error de conteo por imagen: |predichos − reales| → MAE, % de imágenes exactas, error relativo
  - el umbral de confianza para contar se elige en VALIDACIÓN (no en test) para no sesgar el test
  - tiempo de inferencia medio
  - galería de peores imágenes (falsos positivos en rojo, falsos negativos en amarillo, aciertos en verde)

Uso:
  python -I scripts/evaluar.py --run runs/shoe-det-v001 --dataset datasets/zapatos_v1
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
THRESHOLDS = [round(t, 2) for t in np.arange(0.15, 0.71, 0.05)]


def ground_truth(label_path):
    boxes = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        _, cx, cy, w, h = map(float, line.split())
        boxes.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
    return boxes


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(preds, gts, threshold=0.5):
    used, tp = set(), []
    for p in sorted(preds, key=lambda b: -b[4]):
        best, best_iou = None, threshold
        for j, g in enumerate(gts):
            if j not in used and iou(p, g) >= best_iou:
                best, best_iou = j, iou(p, g)
        if best is not None:
            used.add(best)
            tp.append(p)
    fp = [p for p in preds if p not in tp]
    fn = [g for j, g in enumerate(gts) if j not in used]
    return tp, fp, fn


def predict_split(model, images_dir, labels_dir, imgsz, device):
    records = []
    elapsed = []
    for image_path in sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXT):
        label = labels_dir / f"{image_path.stem}.txt"
        if not label.exists():
            continue
        started = time.perf_counter()
        result = model.predict(str(image_path), imgsz=imgsz, conf=min(THRESHOLDS), iou=0.5, device=device,
                               verbose=False)[0]
        elapsed.append((time.perf_counter() - started) * 1000)
        preds = [(*b.tolist(), float(c)) for b, c in zip(result.boxes.xyxyn.cpu(), result.boxes.conf.cpu())]
        records.append({"image": image_path, "gt": ground_truth(label), "preds": preds})
    return records, elapsed


def count_metrics(records, conf):
    errors, exact, true_total = [], 0, 0
    for r in records:
        predicted = sum(1 for p in r["preds"] if p[4] >= conf)
        error = abs(predicted - len(r["gt"]))
        errors.append(error)
        exact += error == 0
        true_total += len(r["gt"])
    n = len(records) or 1
    return {"images": len(records), "mae": round(sum(errors) / n, 4), "exact_rate": round(exact / n, 4),
            "relative_error": round(sum(errors) / true_total, 4) if true_total else None,
            "true_shoes": true_total}


def gallery(records, conf, out_path, worst=24):
    scored = []
    for r in records:
        preds = [p for p in r["preds"] if p[4] >= conf]
        tp, fp, fn = match(preds, r["gt"])
        scored.append((len(fp) + len(fn), r, tp, fp, fn))
    scored.sort(key=lambda s: -s[0])
    tiles = []
    for _, r, tp, fp, fn in scored[:worst]:
        image = Image.open(r["image"]).convert("RGB")
        w, h = image.size
        pen = ImageDraw.Draw(image)
        lw = max(2, w // 250)
        for color, boxes in (((0, 200, 0), tp), ((230, 30, 30), fp), ((255, 210, 0), fn)):
            for b in boxes:
                pen.rectangle((b[0] * w, b[1] * h, b[2] * w, b[3] * h), outline=color, width=lw)
        pen.rectangle((0, 0, 150, 22), fill=(0, 0, 0))
        pen.text((4, 5), f"real {len(r['gt'])} pred {len(tp) + len(fp)} FP{len(fp)} FN{len(fn)}", fill=(255, 255, 255))
        image.thumbnail((320, 320))
        tile = Image.new("RGB", (320, 320), (25, 25, 25))
        tile.paste(image, ((320 - image.width) // 2, (320 - image.height) // 2))
        tiles.append(tile)
    if tiles:
        cols = 6
        mosaic = Image.new("RGB", (cols * 320, ((len(tiles) + cols - 1) // cols) * 320))
        for i, tile in enumerate(tiles):
            mosaic.paste(tile, ((i % cols) * 320, (i // cols) * 320))
        mosaic.save(out_path, quality=85)


def detection_metrics(model, data_yaml, split, imgsz, device, out, name):
    metrics = model.val(data=str(data_yaml), split=split, imgsz=imgsz, device=device, plots=True, verbose=False,
                        project=str(out), name=name, exist_ok=True)
    box = metrics.box
    return {"precision": round(float(box.mp), 4), "recall": round(float(box.mr), 4),
            "map50": round(float(box.map50), 4), "map50_95": round(float(box.map), 4),
            "speed_ms": {k: round(v, 2) for k, v in metrics.speed.items()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--weights", default="weights/best.pt")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()

    run = (ROOT / args.run).resolve()
    dataset = (ROOT / args.dataset).resolve()
    out = run / "evaluacion"
    out.mkdir(exist_ok=True)
    model = YOLO(str(run / args.weights))
    device = args.device

    val_records, _ = predict_split(model, dataset / "images" / "val", dataset / "labels" / "val", args.imgsz, device)
    sweep = {t: count_metrics(val_records, t) for t in THRESHOLDS}
    best_conf = min(THRESHOLDS, key=lambda t: (sweep[t]["mae"], -sweep[t]["exact_rate"]))
    print(f"Umbral de conteo elegido en validación: {best_conf} (MAE val {sweep[best_conf]['mae']})")

    results = {"weights": str(run / args.weights), "count_conf_threshold": best_conf,
               "val_count_sweep": {str(k): v for k, v in sweep.items()}, "splits": {}}
    splits = [("val", dataset / "data.yaml"), ("test", dataset / "data.yaml")]
    if (dataset / "data_externo.yaml").exists():
        splits.append(("test_externo", dataset / "data_externo.yaml"))
    for split, data_yaml in splits:
        val_split = "test" if split == "test_externo" else split
        det = detection_metrics(model, data_yaml, val_split, args.imgsz, device, out, f"ultralytics_{split}")
        records, elapsed = (val_records, None) if split == "val" else predict_split(
            model, dataset / "images" / split, dataset / "labels" / split, args.imgsz, device)
        counting = count_metrics(records, best_conf)
        fp = fn = tp = 0
        for r in records:
            t, f, n = match([p for p in r["preds"] if p[4] >= best_conf], r["gt"])
            tp, fp, fn = tp + len(t), fp + len(f), fn + len(n)
        results["splits"][split] = {**det, "counting": counting,
                                    "at_count_threshold": {"tp": tp, "fp": fp, "fn": fn},
                                    "predict_ms_mean": round(sum(elapsed) / len(elapsed), 2) if elapsed else None}
        gallery(records, best_conf, out / f"peores_{split}.jpg")
        print(split, json.dumps(results["splits"][split], ensure_ascii=False))
    (out / "metricas.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Métricas guardadas en {out / 'metricas.json'}")


if __name__ == "__main__":
    main()
