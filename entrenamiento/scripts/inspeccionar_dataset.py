"""Inspecciona un dataset de detección (imágenes + etiquetas YOLO) y genera un informe real.

Comprueba: número y formato de imágenes, resoluciones, emparejamiento imagen↔etiqueta, formato de
cada línea, rango de coordenadas, clases, cajas por imagen, imágenes corruptas, duplicados exactos
(SHA-256) y casi duplicados (hash perceptual, distancia de Hamming <= umbral).

Uso:
  python -I scripts/inspeccionar_dataset.py --images <carpeta> [--labels <carpeta>] --out informes/kaggle
Admite etiquetas con nombre "<imagen>.txt" o "<imagen>.xml.txt" (caso del dataset de Kaggle).
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import imagehash
from PIL import Image

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def label_for(image_path, labels_dir):
    for name in (image_path.stem + ".txt", image_path.stem + ".xml.txt"):
        candidate = labels_dir / name
        if candidate.exists():
            return candidate
    return None


def parse_label(path):
    boxes, problems = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 5:
            problems.append(f"línea {number}: {len(parts)} valores (se esperan 5)")
            continue
        try:
            cls = int(parts[0])
            cx, cy, w, h = map(float, parts[1:])
        except ValueError:
            problems.append(f"línea {number}: valores no numéricos")
            continue
        if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < w <= 1 and 0 < h <= 1):
            problems.append(f"línea {number}: coordenadas fuera de [0,1]")
        if cx - w / 2 < -0.01 or cx + w / 2 > 1.01 or cy - h / 2 < -0.01 or cy + h / 2 > 1.01:
            problems.append(f"línea {number}: la caja sale de la imagen")
        boxes.append((cls, cx, cy, w, h))
    return boxes, problems


def near_duplicate_groups(hashes, threshold):
    names = list(hashes)
    parent = {n: n for n in names}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if hashes[a] - hashes[b] <= threshold:
                parent[find(a)] = find(b)
    groups = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True)
    parser.add_argument("--labels")
    parser.add_argument("--classes", help="classes.txt (opcional)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--phash-threshold", type=int, default=6)
    args = parser.parse_args()

    images_dir = Path(args.images)
    labels_dir = Path(args.labels) if args.labels else images_dir
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    classes = []
    classes_file = Path(args.classes) if args.classes else labels_dir / "classes.txt"
    if classes_file.exists():
        classes = [c.strip() for c in classes_file.read_text(encoding="utf-8").splitlines() if c.strip()]

    images = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXT)
    label_files = {p.name for p in labels_dir.glob("*.txt") if p.name != "classes.txt"}
    report = {"images_dir": str(images_dir), "classes": classes, "images": len(images),
              "formats": Counter(), "corrupt": [], "unlabeled": [], "label_problems": {},
              "empty_labels": [], "boxes_total": 0, "boxes_per_image": Counter(), "class_counts": Counter(),
              "sizes": [], "exact_duplicates": [], "near_duplicates": []}
    used_labels = set()
    sha, phash = {}, {}
    box_areas = []
    for image_path in images:
        try:
            with Image.open(image_path) as image:
                image.verify()
            with Image.open(image_path) as image:
                report["formats"][image.format] += 1
                report["sizes"].append(image.size)
                phash[image_path.name] = imagehash.phash(image.convert("RGB"))
        except Exception as error:  # noqa: BLE001
            report["corrupt"].append(f"{image_path.name}: {error}")
            continue
        sha.setdefault(hashlib.sha256(image_path.read_bytes()).hexdigest(), []).append(image_path.name)
        label = label_for(image_path, labels_dir)
        if label is None:
            report["unlabeled"].append(image_path.name)
            continue
        used_labels.add(label.name)
        boxes, problems = parse_label(label)
        if problems:
            report["label_problems"][label.name] = problems
        if not boxes:
            report["empty_labels"].append(label.name)
        report["boxes_total"] += len(boxes)
        report["boxes_per_image"][len(boxes)] += 1
        for cls, _, _, w, h in boxes:
            report["class_counts"][classes[cls] if cls < len(classes) else str(cls)] += 1
            box_areas.append(w * h)

    report["orphan_labels"] = sorted(label_files - used_labels)
    report["exact_duplicates"] = [names for names in sha.values() if len(names) > 1]
    report["near_duplicates"] = near_duplicate_groups(phash, args.phash_threshold)
    widths = sorted(s[0] for s in report["sizes"])
    heights = sorted(s[1] for s in report["sizes"])
    report["resolution"] = {
        "min": [widths[0], heights[0]] if widths else None,
        "max": [widths[-1], heights[-1]] if widths else None,
        "median": [widths[len(widths) // 2], heights[len(heights) // 2]] if widths else None,
    }
    box_areas.sort()
    report["box_area_fraction"] = {
        "min": round(box_areas[0], 4) if box_areas else None,
        "median": round(box_areas[len(box_areas) // 2], 4) if box_areas else None,
        "max": round(box_areas[-1], 4) if box_areas else None,
    }
    report["annotation_type"] = ("detección (cajas YOLO: clase cx cy w h normalizados)"
                                 if report["boxes_total"] else "sin cajas")
    report.pop("sizes")
    report["formats"] = dict(report["formats"])
    report["boxes_per_image"] = dict(sorted(report["boxes_per_image"].items()))
    report["class_counts"] = dict(report["class_counts"])
    (out / "informe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Informe del dataset: {images_dir}", "",
        f"- Imágenes: **{report['images']}** · formatos: {report['formats']}",
        f"- Clases (classes.txt): {classes or 'no hay classes.txt'}",
        f"- Tipo de anotación: {report['annotation_type']}",
        f"- Cajas totales: **{report['boxes_total']}** · por clase: {report['class_counts']}",
        f"- Distribución de cajas por imagen (n.º cajas: imágenes): {report['boxes_per_image']}",
        f"- Resolución mín/mediana/máx: {report['resolution']}",
        f"- Área de caja relativa mín/mediana/máx: {report['box_area_fraction']}",
        f"- Imágenes corruptas: {len(report['corrupt'])} {report['corrupt'][:5]}",
        f"- Imágenes sin etiqueta: {len(report['unlabeled'])} {report['unlabeled'][:10]}",
        f"- Etiquetas sin imagen: {len(report['orphan_labels'])} {report['orphan_labels'][:10]}",
        f"- Etiquetas vacías: {len(report['empty_labels'])}",
        f"- Etiquetas con problemas de formato: {len(report['label_problems'])}",
        f"- Duplicados exactos (SHA-256): {len(report['exact_duplicates'])} grupos {report['exact_duplicates'][:5]}",
        f"- Casi duplicados (pHash ≤ {args.phash_threshold}): {len(report['near_duplicates'])} grupos",
    ]
    for group in report["near_duplicates"][:15]:
        lines.append(f"  - {', '.join(group)}")
    for name, problems in list(report["label_problems"].items())[:15]:
        lines.append(f"  - {name}: {'; '.join(problems[:3])}")
    (out / "informe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
