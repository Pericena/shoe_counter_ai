"""Une fuentes etiquetadas en formato YOLO y crea particiones train/val/test sin filtraciones.

Prevención de filtración:
  - duplicados exactos (SHA-256) se eliminan
  - casi duplicados (hash perceptual con distancia <= umbral) forman un GRUPO que va entero a una
    sola partición; el reparto se hace por grupos con una semilla fija
  - las fuentes marcadas con --external-test no se usan para entrenar: forman 'test_externo'

Uso:
  python -I scripts/preparar_dataset.py \
      --source openimages=datasets/openimages/images:datasets/openimages/labels \
      --external-test kaggle=<carpeta imágenes>:<carpeta etiquetas> \
      --out datasets/zapatos_v1 --seed 42
"""
import argparse
import hashlib
import json
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path

import imagehash
from PIL import Image

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
CLASS_NAMES = ["zapato"]


def label_for(image_path, labels_dir):
    for name in (image_path.stem + ".txt", image_path.stem + ".xml.txt"):
        candidate = labels_dir / name
        if candidate.exists():
            return candidate
    return None


def valid_lines(path):
    lines = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            cx, cy, w, h = map(float, parts[1:])
        except ValueError:
            continue
        if 0 <= cx <= 1 and 0 <= cy <= 1 and 0 < w <= 1 and 0 < h <= 1:
            lines.append(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")  # una sola clase: zapato
    return lines


def collect(name, images_dir, labels_dir):
    items = []
    for image_path in sorted(images_dir.iterdir()):
        if image_path.suffix.lower() not in IMAGE_EXT:
            continue
        label = label_for(image_path, labels_dir)
        if label is None:
            continue
        lines = valid_lines(label)
        if not lines:
            continue
        try:
            with Image.open(image_path) as image:
                image.verify()
            with Image.open(image_path) as image:
                phash = int(str(imagehash.phash(image.convert("RGB"))), 16)
        except Exception:  # noqa: BLE001
            continue
        items.append({"source": name, "image": image_path, "lines": lines, "phash": phash,
                      "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest()})
    return items


def group_items(items, threshold):
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    hashes = [it["phash"] for it in items]
    for i in range(len(items)):
        hi = hashes[i]
        for j in range(i + 1, len(items)):
            if (hi ^ hashes[j]).bit_count() <= threshold:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(items[i])
    return list(groups.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", action="append", default=[], help="nombre=imagenes[:etiquetas]")
    parser.add_argument("--external-test", action="append", default=[], help="nombre=imagenes[:etiquetas]")
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ratios", type=float, nargs=3, default=[0.8, 0.1, 0.1])
    parser.add_argument("--phash-threshold", type=int, default=6)
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} ya existe: crea una versión nueva (p. ej. zapatos_v2) para no sobrescribir.")

    def split_arg(text):
        name, _, rest = text.partition("=")
        # admite "C:/a/b:C:/c/d" o "a/b:c/d"
        pieces = rest.split(":")
        merged, current = [], ""
        for piece in pieces:
            if len(piece) == 1 and piece.isalpha() and not current:
                current = piece + ":"
                continue
            merged.append(current + piece)
            current = ""
        images = Path(merged[0])
        labels = Path(merged[1]) if len(merged) > 1 else images
        return name, images, labels

    train_items, external_items = [], []
    for text in args.source:
        train_items += collect(*split_arg(text))
    for text in args.external_test:
        external_items += collect(*split_arg(text))

    # Duplicados exactos (dentro y entre fuentes): se conserva la primera aparición.
    seen, removed = set(), []
    unique = []
    for item in external_items + train_items:
        if item["sha256"] in seen:
            removed.append(str(item["image"]))
            continue
        seen.add(item["sha256"])
        unique.append(item)
    external_items = [i for i in unique if i in external_items]
    train_items = [i for i in unique if i not in external_items]

    # Casi duplicados entre la parte entrenable y el test externo: se quitan de la parte entrenable.
    ext_hashes = [i["phash"] for i in external_items]
    leak = [i for i in train_items if any((i["phash"] ^ h).bit_count() <= args.phash_threshold for h in ext_hashes)]
    train_items = [i for i in train_items if i not in leak]

    groups = group_items(train_items, args.phash_threshold)
    random.Random(args.seed).shuffle(groups)
    total = sum(len(g) for g in groups)
    targets = [args.ratios[0] * total, (args.ratios[0] + args.ratios[1]) * total]
    splits = {"train": [], "val": [], "test": []}
    running = 0
    for group in groups:
        name = "train" if running < targets[0] else ("val" if running < targets[1] else "test")
        splits[name].extend(group)
        running += len(group)
    ext_groups = group_items(external_items, args.phash_threshold) if external_items else []
    if external_items:
        splits["test_externo"] = external_items

    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "seed": args.seed, "ratios": args.ratios,
                "phash_threshold": args.phash_threshold, "classes": CLASS_NAMES,
                "sources": args.source, "external_test": args.external_test,
                "exact_duplicates_removed": removed, "near_duplicates_removed_vs_external": [str(i["image"]) for i in leak],
                "near_duplicate_groups": sum(1 for g in groups if len(g) > 1) + sum(1 for g in ext_groups if len(g) > 1),
                "splits": {}}
    for split, items in splits.items():
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
        files = []
        for item in items:
            stem = f"{item['source']}_{item['image'].stem}"[:150]
            target = out / "images" / split / f"{stem}{item['image'].suffix.lower()}"
            shutil.copy2(item["image"], target)
            (out / "labels" / split / f"{stem}.txt").write_text("\n".join(item["lines"]) + "\n", encoding="utf-8")
            files.append({"file": target.name, "source": item["source"], "boxes": len(item["lines"]),
                          "sha256": item["sha256"]})
        manifest["splits"][split] = {"images": len(files), "boxes": sum(f["boxes"] for f in files), "files": files}

    names_yaml = "\n".join(f"  {i}: {n}" for i, n in enumerate(CLASS_NAMES))
    root = out.resolve().as_posix()
    (out / "data.yaml").write_text(
        f"path: {root}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n{names_yaml}\n", encoding="utf-8")
    if "test_externo" in splits:
        (out / "data_externo.yaml").write_text(
            f"path: {root}\ntrain: images/train\nval: images/test_externo\ntest: images/test_externo\n"
            f"names:\n{names_yaml}\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # Verificación final: ningún archivo (por hash) en dos particiones.
    owners = {}
    for split, data in manifest["splits"].items():
        for f in data["files"]:
            if f["sha256"] in owners and owners[f["sha256"]] != split:
                raise SystemExit(f"Filtración detectada: {f['file']} en {owners[f['sha256']]} y {split}")
            owners[f["sha256"]] = split
    summary = {s: {k: v for k, v in d.items() if k != "files"} for s, d in manifest["splits"].items()}
    print(json.dumps({"splits": summary, "exact_duplicates_removed": len(removed),
                      "near_duplicates_removed_vs_external": len(leak),
                      "near_duplicate_groups": manifest["near_duplicate_groups"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
