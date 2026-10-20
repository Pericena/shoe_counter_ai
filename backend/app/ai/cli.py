"""`flask --app run ai export-dataset --out <carpeta>`: convierte los conteos revisados por personas
(confirmados o aplicados) en un dataset YOLO para evaluar o reentrenar el detector con fotos REALES
de la tienda. Solo se exportan cajas aceptadas (del modelo o añadidas a mano)."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import click
from flask import current_app
from flask.cli import AppGroup
from sqlalchemy import select

from ..extensions import db
from .models import AICount

ai_cli = AppGroup("ai", help="Herramientas del detector de zapatos.")


@ai_cli.command("export-dataset")
@click.option("--out", required=True, type=click.Path(file_okay=False), help="Carpeta de destino (debe no existir).")
def export_dataset(out):
    target = Path(out)
    if target.exists():
        raise click.ClickException(f"{target} ya existe; elige una carpeta nueva para no sobrescribir.")
    counts = db.session.execute(
        select(AICount).where(AICount.status.in_(("confirmado", "aplicado"))).order_by(AICount.id)).scalars().all()
    if not counts:
        raise click.ClickException("No hay conteos confirmados para exportar.")
    (target / "images").mkdir(parents=True)
    (target / "labels").mkdir()
    storage = current_app.config["STORAGE_DIR"].resolve()
    files = []
    for count in counts:
        source = (storage / count.file.relative_path).resolve()
        if storage not in source.parents or not source.is_file():
            click.echo(f"Aviso: falta la imagen del conteo #{count.id}; se omite.")
            continue
        stem = f"tienda_conteo_{count.id:06d}"
        shutil.copy2(source, target / "images" / f"{stem}.jpg")
        lines = [f"0 {(d.x1 + d.x2) / 2:.6f} {(d.y1 + d.y2) / 2:.6f} {d.x2 - d.x1:.6f} {d.y2 - d.y1:.6f}"
                 for d in count.detections if d.accepted]
        (target / "labels" / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        files.append({"file": f"{stem}.jpg", "count_id": count.id, "shoes": len(lines),
                      "model_version": count.model_version, "manual_boxes": sum(1 for d in count.detections
                                                                               if d.accepted and d.source == "manual")})
    (target / "classes.txt").write_text("zapato\n", encoding="utf-8")
    (target / "manifest.json").write_text(json.dumps({
        "exported_at": datetime.now(timezone.utc).isoformat(), "source": "conteos confirmados de la aplicación",
        "images": len(files), "boxes": sum(f["shoes"] for f in files), "files": files,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"Exportadas {len(files)} imágenes con {sum(f['shoes'] for f in files)} cajas en {target}")
