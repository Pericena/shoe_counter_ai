# entrenamiento/ — detector de zapatos

Pipeline reproducible para entrenar, evaluar y exportar el detector que usa el «Conteo inteligente». Todo se ejecuta desde esta carpeta con su propio entorno virtual, separado del backend. Resultados y análisis: [../docs/04-ia-detector.md](../docs/04-ia-detector.md).

## 1. Entorno (Windows, Python 3.12)

```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu126
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

- **GPU usada**: RTX 3050 de 6 GB. El entrenamiento usó unos 4 GB de VRAM con `yolo11s`, 640 px y *batch* 16. Si aparece «CUDA out of memory», baja `batch` a 8.
- **RAM**: en este equipo de 7,6 GB hay que usar `workers: 0` y no tener Docker Desktop en marcha a la vez; si no, Windows se queda sin memoria (ver bitácora).
- **Sin GPU**: instala torch sin el índice CUDA, usa `model: yolo11n.pt` y pocas épocas. Será mucho más lento.

## 2. Datos

```bash
# a) Dataset de Kaggle (solo evaluación externa; licencia "Unknown")
.venv\Scripts\python -I -c "import kagglehub; print(kagglehub.dataset_download('nishthakukreti/shoedataset'))"
.venv\Scripts\python -I scripts\inspeccionar_dataset.py --images <ruta>\Shoes_annotation --out informes\kaggle_shoedataset

# b) Open Images V7: subconjunto de calzado con cajas verificadas (entrenamiento)
.venv\Scripts\python -I scripts\descargar_openimages.py --out datasets\openimages --max-images 3000 --seed 42

# c) Unir y particionar sin filtraciones (grupos de casi duplicados por hash perceptual)
.venv\Scripts\python -I scripts\preparar_dataset.py --source "openimages=datasets/openimages/images:datasets/openimages/labels" --external-test "kaggle=<ruta>/Shoes_annotation:<ruta>/Shoes_annotation" --out datasets\zapatos_v1 --seed 42

# d) Validar y revisar visualmente (genera datasets\zapatos_v1\verificacion\muestra_*.jpg)
.venv\Scripts\python -I scripts\validar_dataset.py --dataset datasets\zapatos_v1
```

KaggleHub reutiliza su caché (`%USERPROFILE%\.cache\kagglehub`) y no descarga dos veces. Este dataset es público y no pidió credenciales. Si algún dataset las pide, usa el mecanismo oficial: el archivo `%USERPROFILE%\.kaggle\kaggle.json` o las variables `KAGGLE_USERNAME` y `KAGGLE_KEY` en tu sesión. **Nunca** guardes el token en el código ni en Git.

## 3. Entrenar, evaluar, exportar

```bash
# Prueba rápida (1 época, 5 % de datos) para comprobar memoria y pipeline:
.venv\Scripts\python -I scripts\entrenar.py --epochs 1 --fraction 0.05 --version prueba-humo

# Entrenamiento real (parámetros en configs\detector_zapatos.yaml):
.venv\Scripts\python -I scripts\entrenar.py --config configs\detector_zapatos.yaml

# Evaluación en val/test/test_externo (elige el umbral de conteo SOLO con validación):
.venv\Scripts\python -I scripts\evaluar.py --run runs\shoe-det-v001 --dataset datasets\zapatos_v1

# Exportación versionada: modelo\pesos\<versión>\best.pt + modelo\exportados\<versión>\model.onnx
.venv\Scripts\python -I scripts\exportar.py --run runs\shoe-det-v001 --dataset datasets\zapatos_v1

# Inferencia sobre fotos propias (dibuja cajas y genera conteos.csv):
.venv\Scripts\python -I scripts\inferir.py --weights ..\modelo\pesos\shoe-det-v001\best.pt --source <carpeta> --out salida
```

Reglas del pipeline:

- `entrenar.py` **se niega a sobrescribir** una versión existente; `--resume` continúa una interrumpida.
- `exportar.py` se niega a exportar sin `evaluacion/metricas.json` y a sobrescribir una versión exportada.
- Cada versión guarda `entorno.json`: versiones, GPU, parámetros, semilla y manifiesto del dataset.

## 4. Reentrenar con fotos reales de la tienda

Las fotos revisadas en la app (cajas aceptadas y añadidas a mano) son datos etiquetados reales:

```bash
cd ..\backend
..\.venv\Scripts\flask --app run ai export-dataset --out ..\entrenamiento\datasets\tienda_AAAAMMDD
```

Después vuelve a ejecutar `preparar_dataset.py` añadiendo `--source tienda=...` (o, mejor, `--external-test` para **evaluar** en fotos de la tienda) con una carpeta de salida y una `version` nuevas.

## 5. Archivos

| Ruta | Contenido | ¿En Git? |
|---|---|---|
| `scripts/` | Pipeline completo | Sí |
| `configs/detector_zapatos.yaml` | Hiperparámetros | Sí |
| `informes/` | Informes reales de los datasets (`informe.md`/`.json`) | Sí |
| `datasets/`, `runs/`, `weights/`, `logs/`, `*.pt` | Datos descargados, ejecuciones, pesos base y registros | No (`.gitignore`) |
| `shoe-brand-classification-nike-adidas-converse.ipynb` | Notebook público de Kaggle de **otro autor** sobre **clasificación de marca**. Solo referencia: no detecta ni cuenta zapatos | Sí |
