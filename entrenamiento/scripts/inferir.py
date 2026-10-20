"""Ejecuta el detector sobre imágenes, dibuja las cajas y cuenta zapatos.

Uso:
  python -I scripts/inferir.py --weights ../modelo/pesos/shoe-det-v001/best.pt --source fotos/ --out salida/ --conf 0.35
"""
import argparse
import csv
from pathlib import Path

from PIL import Image, ImageDraw
from ultralytics import YOLO

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()
    source, out = Path(args.source), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    images = [source] if source.is_file() else sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_EXT)
    model = YOLO(args.weights)
    rows = []
    for image_path in images:
        result = model.predict(str(image_path), conf=args.conf, imgsz=args.imgsz, device=args.device, verbose=False)[0]
        image = Image.open(image_path).convert("RGB")
        pen = ImageDraw.Draw(image)
        lw = max(2, image.width // 250)
        for i, (box, conf) in enumerate(zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist()), start=1):
            pen.rectangle(box, outline=(0, 200, 0), width=lw)
            pen.text((box[0] + 3, box[1] + 3), f"{i}: {conf:.2f}", fill=(0, 200, 0))
        image.save(out / f"{image_path.stem}_detecciones.jpg", quality=90)
        rows.append({"imagen": image_path.name, "zapatos_detectados": len(result.boxes),
                     "tiempo_ms": round(sum(result.speed.values()), 1)})
        print(f"{image_path.name}: {len(result.boxes)} zapatos")
    with open(out / "conteos.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["imagen", "zapatos_detectados", "tiempo_ms"])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
