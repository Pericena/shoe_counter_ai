"""Entrena el detector de zapatos con Ultralytics YOLO según configs/detector_zapatos.yaml.

- Comprueba GPU/VRAM y ajusta 'device' (auto → GPU 0 si existe, si no CPU).
- Registra entorno, parámetros y semilla en runs/<versión>/entorno.json.
- Se niega a sobrescribir una versión ya entrenada (usa --resume para continuar una interrumpida).

Uso:
  python -I scripts/entrenar.py --config configs/detector_zapatos.yaml [--epochs 1 --fraction 0.1  (prueba rápida)]
"""
import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch
import ultralytics
import yaml
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]


def hardware():
    info = {"python": sys.version.split()[0], "platform": platform.platform(), "torch": torch.__version__,
            "ultralytics": ultralytics.__version__, "cuda_available": torch.cuda.is_available()}
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        info.update({"gpu": props.name, "vram_gb": round(props.total_memory / 1024 ** 3, 2),
                     "cuda": torch.version.cuda})
    return info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/detector_zapatos.yaml")
    parser.add_argument("--epochs", type=int, help="sobrescribe epochs (p. ej. 1 para una prueba)")
    parser.add_argument("--fraction", type=float, default=1.0, help="fracción del train a usar (prueba)")
    parser.add_argument("--version", help="sobrescribe la versión")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load((ROOT / args.config).read_text(encoding="utf-8"))
    version = args.version or config["version"]
    run_dir = ROOT / "runs" / version
    hw = hardware()
    print(json.dumps(hw, indent=2))

    if args.resume:
        last = run_dir / "weights" / "last.pt"
        if not last.exists():
            raise SystemExit(f"No hay {last} para reanudar.")
        YOLO(str(last)).train(resume=True)
        return
    if run_dir.exists():
        raise SystemExit(f"La versión {version} ya existe en {run_dir}. Cambia 'version' para entrenar otra.")

    device = config.get("device", "auto")
    if device == "auto":
        device = 0 if hw["cuda_available"] else "cpu"
    batch = config["batch"]
    if device != "cpu" and hw.get("vram_gb", 0) < 4 and batch > 8:
        print(f"VRAM {hw['vram_gb']} GB: se reduce batch de {batch} a 8.")
        batch = 8
    if device == "cpu":
        print("Aviso: entrenando en CPU. Será lento; considera yolo11n.pt y pocas épocas.")

    data_yaml = (ROOT / config["dataset"]).resolve()
    if not data_yaml.exists():
        raise SystemExit(f"No existe {data_yaml}. Ejecuta antes preparar_dataset.py.")
    params = {
        "data": str(data_yaml), "epochs": args.epochs or config["epochs"], "patience": config["patience"],
        "imgsz": config["imgsz"], "batch": batch, "seed": config["seed"], "deterministic": config["deterministic"],
        "device": device, "workers": config["workers"], "cache": config["cache"], "optimizer": config["optimizer"],
        "cos_lr": config["cos_lr"], "close_mosaic": config["close_mosaic"], "fraction": args.fraction,
        "project": str(ROOT / "runs"), "name": version, "exist_ok": False, "plots": True, "verbose": True,
        "single_cls": True,
    }
    run_dir.mkdir(parents=True)
    (run_dir / "entorno.json").write_text(json.dumps({
        "version": version, "started_at": datetime.now(timezone.utc).isoformat(), "base_model": config["model"],
        "params": params, "hardware": hw,
        "dataset_manifest": str((data_yaml.parent / "manifest.json").relative_to(ROOT)),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    params["exist_ok"] = True  # la carpeta ya existe solo por entorno.json
    model = YOLO(config["model"])
    model.train(**params)
    print(f"Entrenamiento terminado. Pesos en {run_dir / 'weights'}")


if __name__ == "__main__":
    main()
