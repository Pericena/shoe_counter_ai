"""Descarga un subconjunto de Open Images V7 con cajas de calzado y lo convierte a formato YOLO.

Fuente oficial: https://storage.googleapis.com/openimages/web/download_v7.html
Licencias: anotaciones CC BY 4.0; imágenes listadas por Google como CC BY 2.0 (se guarda autor y
URL original de cada imagen en attribution.csv para cumplir la atribución).

Se usan las particiones validation y test porque sus cajas fueron verificadas exhaustivamente.
Filtros para que el conteo sea fiable:
  - clases de calzado: Footwear y sus subclases (Boot, High heels, Sandal); se eliminan cajas
    duplicadas del mismo objeto (padre e hija) con IoU > 0.7
  - se descartan imágenes con cajas "IsGroupOf" (una caja para varios zapatos), "IsDepiction"
    (dibujos) o con patines (Roller skates)
  - se descartan imágenes con rotación EXIF registrada y con más de 30 zapatos

Uso:
  python -I scripts/descargar_openimages.py --out datasets/openimages --max-images 3000
"""
import argparse
import concurrent.futures as futures
import csv
import io
import random
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd
from PIL import Image

META = {
    "validation-annotations-bbox.csv": "https://storage.googleapis.com/openimages/v5/validation-annotations-bbox.csv",
    "test-annotations-bbox.csv": "https://storage.googleapis.com/openimages/v5/test-annotations-bbox.csv",
    "class-descriptions-boxable.csv": "https://storage.googleapis.com/openimages/v5/class-descriptions-boxable.csv",
    "validation-images-with-rotation.csv":
        "https://storage.googleapis.com/openimages/2018_04/validation/validation-images-with-rotation.csv",
    "test-images-with-rotation.csv": "https://storage.googleapis.com/openimages/2018_04/test/test-images-with-rotation.csv",
}
IMAGE_URL = "https://open-images-dataset.s3.amazonaws.com/{split}/{image_id}.jpg"
SHOE_CLASSES = ["Footwear", "Boot", "High heels", "Sandal"]
EXCLUDE_CLASSES = ["Roller skates"]


def download(url, target, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
            target.write_bytes(data)
            return data
        except Exception:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def load_meta(meta_dir):
    meta_dir.mkdir(parents=True, exist_ok=True)
    for name, url in META.items():
        path = meta_dir / name
        if not path.exists():
            print(f"Descargando {name}…", flush=True)
            download(url, path)
    classes = pd.read_csv(meta_dir / "class-descriptions-boxable.csv", header=None, names=["mid", "name"])
    mids = dict(zip(classes["name"], classes["mid"]))
    shoe_mids = {mids[n] for n in SHOE_CLASSES if n in mids}
    exclude_mids = {mids[n] for n in EXCLUDE_CLASSES if n in mids}
    missing = [n for n in SHOE_CLASSES if n not in mids]
    if missing:
        print(f"Aviso: clases no encontradas en Open Images: {missing}")
    return shoe_mids, exclude_mids


def candidate_images(meta_dir, shoe_mids, exclude_mids):
    rows = []
    for split in ("validation", "test"):
        boxes = pd.read_csv(meta_dir / f"{split}-annotations-bbox.csv",
                            usecols=["ImageID", "LabelName", "XMin", "XMax", "YMin", "YMax", "IsGroupOf", "IsDepiction"])
        boxes = boxes[boxes["LabelName"].isin(shoe_mids | exclude_mids)]
        info = pd.read_csv(meta_dir / f"{split}-images-with-rotation.csv",
                           usecols=["ImageID", "OriginalURL", "Author", "License", "Rotation"])
        info = info.set_index("ImageID")
        for image_id, group in boxes.groupby("ImageID"):
            if group["LabelName"].isin(exclude_mids).any():
                continue
            if (group["IsGroupOf"] == 1).any() or (group["IsDepiction"] == 1).any():
                continue
            if image_id not in info.index:
                continue
            meta = info.loc[image_id]
            if pd.notna(meta["Rotation"]) and float(meta["Rotation"]) != 0:
                continue
            kept = []
            for b in group.itertuples():
                box = (float(b.XMin), float(b.YMin), float(b.XMax), float(b.YMax))
                if box[2] - box[0] <= 0 or box[3] - box[1] <= 0:
                    continue
                if all(iou(box, k) <= 0.7 for k in kept):
                    kept.append(box)
            if not kept or len(kept) > 30:
                continue
            rows.append({"image_id": image_id, "split": split, "boxes": kept, "url": meta["OriginalURL"],
                         "author": meta["Author"], "license": meta["License"]})
    return rows


def fetch_image(item, images_dir, labels_dir, max_side):
    image_path = images_dir / f"oi_{item['image_id']}.jpg"
    label_path = labels_dir / f"oi_{item['image_id']}.txt"
    if image_path.exists() and label_path.exists():
        return "existe"
    url = IMAGE_URL.format(split=item["split"], image_id=item["image_id"])
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    image = Image.open(io.BytesIO(data))
    image.verify()
    image = Image.open(io.BytesIO(data)).convert("RGB")
    image.thumbnail((max_side, max_side))
    image.save(image_path, "JPEG", quality=92)
    lines = []
    for x1, y1, x2, y2 in item["boxes"]:
        lines.append(f"0 {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {x2 - x1:.6f} {y2 - y1:.6f}")
    label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "ok"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="datasets/openimages")
    parser.add_argument("--max-images", type=int, default=3000)
    parser.add_argument("--max-side", type=int, default=1280)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    out = Path(args.out)
    images_dir, labels_dir = out / "images", out / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    shoe_mids, exclude_mids = load_meta(out / "meta")
    candidates = candidate_images(out / "meta", shoe_mids, exclude_mids)
    print(f"Imágenes candidatas tras los filtros: {len(candidates)}", flush=True)
    random.Random(args.seed).shuffle(candidates)
    selected = candidates[:args.max_images]

    results = {"ok": 0, "existe": 0, "error": 0}
    downloaded = []
    with futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(fetch_image, item, images_dir, labels_dir, args.max_side): item for item in selected}
        for index, job in enumerate(futures.as_completed(jobs), start=1):
            item = jobs[job]
            try:
                results[job.result()] += 1
                downloaded.append(item)
            except Exception as error:  # noqa: BLE001
                results["error"] += 1
                print(f"Error con {item['image_id']}: {error}", file=sys.stderr)
            if index % 200 == 0:
                print(f"  {index}/{len(selected)} {results}", flush=True)

    with open(out / "attribution.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["archivo", "image_id", "particion_openimages", "zapatos", "autor", "licencia", "url_original"])
        for item in sorted(downloaded, key=lambda i: i["image_id"]):
            writer.writerow([f"oi_{item['image_id']}.jpg", item["image_id"], item["split"], len(item["boxes"]),
                             item["author"], item["license"], item["url"]])
    print(f"Resultado: {results}. Atribución en {out / 'attribution.csv'}")


if __name__ == "__main__":
    main()
