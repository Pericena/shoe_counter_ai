"""Valida un dataset preparado (data.yaml) y dibuja una muestra de imágenes con sus cajas.

Comprueba en cada partición: que cada imagen tenga etiqueta y viceversa, formato de líneas,
coordenadas en [0,1] y clases conocidas. Genera mosaicos para revisión visual.

Uso:
  python -I scripts/validar_dataset.py --dataset datasets/zapatos_v1 --samples 24
"""
import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def check_split(images_dir, labels_dir, n_classes):
    images = {p.stem: p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXT}
    labels = {p.stem: p for p in labels_dir.glob("*.txt")}
    problems = []
    boxes = 0
    for stem in sorted(set(images) - set(labels)):
        problems.append(f"imagen sin etiqueta: {stem}")
    for stem in sorted(set(labels) - set(images)):
        problems.append(f"etiqueta sin imagen: {stem}")
    for stem, path in labels.items():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            parts = line.split()
            if len(parts) != 5:
                problems.append(f"{path.name}:{number} formato")
                continue
            cls, *coords = parts
            if not cls.isdigit() or int(cls) >= n_classes:
                problems.append(f"{path.name}:{number} clase {cls}")
            if any(not 0 <= float(c) <= 1 for c in coords):
                problems.append(f"{path.name}:{number} coordenadas fuera de rango")
            boxes += 1
    return images, labels, boxes, problems


def draw(image_path, label_path, size=320):
    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    pen = ImageDraw.Draw(image)
    lines = label_path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        _, cx, cy, bw, bh = map(float, line.split())
        box = ((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h)
        pen.rectangle(box, outline=(0, 220, 0), width=max(2, w // 200))
    pen.rectangle((0, 0, 70, 22), fill=(0, 0, 0))
    pen.text((5, 5), f"{len(lines)} zap.", fill=(255, 255, 255))
    image.thumbnail((size, size))
    tile = Image.new("RGB", (size, size), (30, 30, 30))
    tile.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return tile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    root = Path(args.dataset)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    n_classes = len(manifest["classes"])
    out = root / "verificacion"
    out.mkdir(exist_ok=True)
    report = {}
    ok = True
    for split in manifest["splits"]:
        images, labels, boxes, problems = check_split(root / "images" / split, root / "labels" / split, n_classes)
        report[split] = {"images": len(images), "labels": len(labels), "boxes": boxes, "problems": problems[:50]}
        ok = ok and not problems
        sample = random.Random(args.seed).sample(sorted(images), min(args.samples, len(images)))
        tiles = [draw(images[s], labels[s]) for s in sample if s in labels]
        if tiles:
            cols = 6
            rows = (len(tiles) + cols - 1) // cols
            mosaic = Image.new("RGB", (cols * 320, rows * 320), (0, 0, 0))
            for i, tile in enumerate(tiles):
                mosaic.paste(tile, ((i % cols) * 320, (i // cols) * 320))
            mosaic.save(out / f"muestra_{split}.jpg", quality=85)
    (out / "validacion.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {kk: (vv if kk != "problems" else len(vv)) for kk, vv in v.items()} for k, v in report.items()},
                     indent=2, ensure_ascii=False))
    print("VALIDACIÓN:", "OK" if ok else "CON PROBLEMAS (ver verificacion/validacion.json)")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
