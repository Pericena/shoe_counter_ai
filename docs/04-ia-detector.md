# Detector de zapatos y conteo inteligente

## 1. Resumen honesto

| Pregunta | Respuesta |
|---|---|
| ¿Hay un modelo entrenado? | Sí: **`shoe-det-v001`** (YOLO11s ajustado, 1 clase «zapato»), entrenado en este equipo el 2026-10-20 |
| ¿Funciona? | Sí, como asistente: el modelo desplegado (ONNX) detecta zapatos individuales con precisión 0,77–0,85 y recall 0,62–0,75 según el conjunto (§4.1). Integrado y probado en la app y en Docker |
| ¿Sirve ya para contar sin revisión? | **No.** El conteo exacto se da en 40–57 % de las fotos y **falla en filas de zapatos expuestos**, que es el escenario de la tienda (§5). Por eso la app **exige revisión y confirmación humana** antes de tocar el stock |
| ¿Qué falta para un detector fiable en la tienda? | Fotos **reales** de la tienda, anotadas (la propia app las genera: §6), para reentrenar y, sobre todo, para medir el rendimiento en ese escenario |

## 2. Datos

| Conjunto | Uso | Detalle |
|---|---|---|
| **Open Images V7**, clases Footwear, Boot, High heels y Sandal (particiones validation y test, cajas verificadas) | Entrenamiento, validación y prueba | Se descartan las cajas *IsGroupOf* (una caja que agrupa varios zapatos, lo que haría imposible contar), los dibujos (*IsDepiction*), las imágenes con patines, con rotación EXIF o con más de 30 zapatos. Cajas duplicadas entre clase padre e hija (IoU > 0,7) se unifican. 7.877 candidatas → 3.000 descargadas con semilla 42, reducidas a 1.280 px como máximo. Anotaciones CC BY 4.0; imágenes CC BY 2.0 con autor y URL en `datasets/openimages/attribution.csv` |
| **Kaggle `nishthakukreti/shoedataset`** | **Solo prueba externa** | 150 imágenes, 137 etiquetadas en YOLO (clase `shoe`, 300 cajas, una por zapato individual: mismo objetivo de detección). **Licencia «Unknown»** y marcas de agua de bancos de imágenes (alamy, shutterstock) → no se usa para entrenar los pesos entregados. Informe: `entrenamiento/informes/kaggle_shoedataset/informe.md` |

El dataset de Kaggle **sí** trae cajas (escenario A del encargo), pero su licencia y su tamaño, 137 imágenes de catálogo con 2 zapatos puestos, no permiten basar en él el detector.

**Particiones sin filtraciones** (`preparar_dataset.py`, semilla 42):

| Partición | Imágenes | Cajas |
|---|---|---|
| train (Open Images) | 2.400 | 10.216 |
| val (Open Images) | 300 | 1.298 |
| test (Open Images) | 300 | 1.355 |
| test_externo (Kaggle) | 137 | 300 |

Cómo se evitó la contaminación entre conjuntos:

- Los duplicados exactos (SHA-256) se eliminan: 0 entre fuentes. El duplicado exacto que hay dentro de Kaggle tenía una de las dos copias sin etiqueta.
- Los casi duplicados (hash perceptual, distancia ≤ 6) forman grupos que van enteros a una sola partición: 7 grupos.
- Se buscaron casi duplicados entre Open Images y el test externo: 0.
- Una comprobación final verifica que ningún hash aparezca en dos particiones.

## 3. Entrenamiento

| Parámetro | Valor |
|---|---|
| Base | `yolo11s.pt` (COCO, Ultralytics 8.4.183) · PyTorch 2.14.1 + CUDA 12.6 · RTX 3050 6 GB |
| Configuración | `configs/detector_zapatos.yaml`: 60 épocas, `patience` 15, 640 px, batch 16, semilla 42, determinista, `cos_lr`, `close_mosaic` 10, `single_cls` |
| Memoria | ~4 GB de VRAM. Con `workers ≥ 1` y Docker Desktop abierto, Windows se quedó sin RAM (7,6 GB) y el primer intento cayó en la época 2. Se relanzó con `workers: 0` |
| Duración | ~4 h 30 min (2–4 min por época) |
| Mejor checkpoint | **Época 59** según la *fitness* de Ultralytics (0,9·mAP50-95 + 0,1·mAP50): mAP50 0,663 / mAP50-95 0,362 en val. `best.pt` = ese checkpoint, no el de la última época |

Evolución en validación (mAP50): época 1: 0,216 · 10: 0,502 · 20: 0,574 · 35: 0,628 · 47: 0,660 · 59: 0,663 · 60: 0,660.

## 4. Evaluación (imágenes no usadas para entrenar)

`scripts/evaluar.py`. El **umbral de conteo** se elige minimizando el error de conteo **solo en validación** y después se aplica sin cambios a los conjuntos de prueba.

### 4.1 Modelo desplegado: ONNX (`model.onnx`, el que ejecuta la app). Métricas oficiales

Evaluado en CPU con `--weights …/model.onnx --tag _onnx`. Umbral elegido en validación: **0,20**, guardado como `recommended_confidence` en `metadata.json` y usado por la app.

| Conjunto | Imágenes / zapatos | Precisión | Recall | mAP50 | mAP50-95 | MAE de conteo | Conteo exacto | Error relativo | TP / FP / FN (IoU 0,5) |
|---|---|---|---|---|---|---|---|---|---|
| val (Open Images) | 300 / 1.298 | 0,770 | 0,586 | 0,666 | 0,365 | 1,19 | 40,0 % | 27,5 % | 841 / 412 / 457 |
| **test** (Open Images) | 300 / 1.355 | **0,767** | **0,619** | **0,687** | **0,379** | **1,23** | **40,0 %** | **27,2 %** | 905 / 373 / 450 |
| **test externo** (Kaggle) | 137 / 300 | **0,853** | **0,747** | **0,823** | **0,556** | **0,56** | **56,9 %** | **25,7 %** | 246 / 69 / 54 |

- Tiempo de inferencia del ONNX en la CPU de este equipo: ~165–180 ms por imagen (solo el modelo). En la app, ~0,3–0,75 s por foto incluyendo la lectura. En el contenedor Docker se midieron 308 ms.

### 4.2 Pesos nativos (`best.pt`, letterbox rectangular, GPU), como referencia

Umbral elegido en validación: 0,25.

| Conjunto | Precisión | Recall | mAP50 | mAP50-95 | MAE | Exactos |
|---|---|---|---|---|---|---|
| val | 0,752 | 0,599 | 0,664 | 0,361 | 1,20 | 43,0 % |
| test | 0,766 | 0,624 | 0,686 | 0,381 | 1,30 | 40,3 % |
| test externo | 0,814 | 0,790 | 0,834 | 0,555 | 0,55 | 59,9 % |

- MAE de conteo = media de |zapatos predichos − zapatos reales| por imagen.
- Error relativo = Σ errores / Σ zapatos reales.
- Matrices de confusión, curvas PR y galerías: `entrenamiento/runs/shoe-det-v001/evaluacion/` y `evaluacion_onnx/` (`ultralytics_*`, `peores_*.jpg`).

### 4.3 Paridad entre el backend y Ultralytics (defecto encontrado y corregido)

La primera exportación mostró que el pipeline del backend solo coincidía en **26 de 40** conteos con PyTorch. Diagnóstico sobre 40 imágenes de test:

| Comparación | Conteos iguales |
|---|---|
| ONNX de Ultralytics vs. backend con PIL (versión inicial) | 32/40 → **defecto**: PIL suaviza al reducir y rellenaba con otra geometría |
| ONNX de Ultralytics vs. backend con letterbox OpenCV idéntico | **40/40** |
| PyTorch (letterbox rectangular) vs. ONNX (entrada fija 640) | 33/40 → diferencia inherente a exportar con tamaño fijo |

Corrección: `backend/app/ai/postprocess.py::letterbox` replica exactamente `LetterBox(auto=False)` de Ultralytics, con `opencv-python-headless` en el backend. `scripts/verificar_onnx.py` lo comprueba y dio **60/60 en test y 60/60 en test externo**. Como el ONNX difiere del `.pt` en ~10–15 % de los conteos, **las métricas oficiales son las del ONNX (§4.1)**, que es lo que ejecuta la app.

### 4.4 Independencia del conjunto externo

- Kaggle procede de otra fuente: fotos de catálogo de banco de imágenes frente a Open Images de Flickr.
- Se buscaron casi duplicados contra Open Images con hash perceptual: 0.
- Se revisó visualmente una muestra: **una caja por zapato individual**, el mismo objetivo de detección.
- Contiene ruido de anotación (por ejemplo, un zapato con 2 cajas) y un dominio más fácil (zapatos grandes y centrados). Por eso sus métricas son más altas y **no** representan una foto de estantería.

## 5. Análisis de errores (galerías `peores_*.jpg`)

- **Falsos negativos en escenas con mucha gente** (Open Images): gradas, equipos, manifestaciones, con zapatos de pocos píxeles. Es el origen principal del recall bajo en test.
- **Falsos positivos**: patas de perro, objetos oscuros en el suelo y zapatos dibujados.
- **Errores de localización** (Kaggle): el modelo incluye parte de la pierna o el pantalón en la caja. Con IoU < 0,5 cuenta como falso positivo **y** falso negativo aunque el conteo sea correcto. Por eso las métricas de detección subestiman la calidad del conteo en esas fotos.
- **Fallo crítico para la tienda**: en una foto de **10 zapatos alineados en exposición** detectó solo 4. Las fotos de exposición o estantería casi no aparecen en Open Images.
- Hay **ruido de anotación** en Kaggle: por ejemplo, un único zapato con 2 cajas.

Conclusión: el modelo es útil como **asistente**, porque propone cajas que la persona acepta, rechaza o completa, pero **no** debe cerrar inventario sin revisión. La app ya lo impone.

## 6. Cómo mejorarlo (sin inventar datos)

1. **Recoger fotos reales** de estanterías, cajas y exposiciones de la tienda y contarlas en la app (revisar y confirmar). El administrador ejecuta:

   ```bash
   flask --app run ai export-dataset --out ../entrenamiento/datasets/tienda_AAAAMMDD
   ```

   Esto genera un dataset YOLO con las cajas confirmadas por personas.
2. Usar primero ese dataset como **test externo** (`--external-test tienda=…`) para medir el rendimiento real. Con suficientes fotos (orientativamente, varios cientos), añadirlo también a entrenamiento en una versión nueva (`shoe-det-v002`).
3. Si la tienda fotografía zapatos pequeños o lejanos, probar `imgsz: 960` o `yolo11m` (vigilando la VRAM de 6 GB).

## 7. Exportación, formatos y licencias

- **Nativo**: `modelo/pesos/shoe-det-v001/best.pt`.
- **Backend**: `modelo/exportados/shoe-det-v001/model.onnx` (opset 17, 640 px, sin NMS integrado) + `metadata.json`. Incluye versión, fecha, parámetros, hardware, SHA-256 del manifiesto del dataset y de los pesos, métricas del ONNX (`metrics`) y del `.pt` (`metrics_pytorch`), umbral recomendado (0,20) y resultado de la paridad.
- `exportar.py` aborta si el pipeline del backend no reproduce exactamente a Ultralytics ejecutando el mismo ONNX, y nunca sobrescribe una versión. Después: `evaluar.py --weights <model.onnx> --device cpu --tag _onnx` y `verificar_onnx.py`.
- **`.bin`**: no se generó. Un `.bin` solo tiene sentido para un runtime concreto (OpenVINO `model.xml + model.bin`, NCNN `.param + .bin` o TF.js `model.json + *.bin`), y no hay ninguno definido. Renombrar `.pt` a `.bin` no convierte nada. Si se necesita, por ejemplo para OpenVINO, se exportaría con Ultralytics `format=openvino`.
- **Licencia**: Ultralytics YOLO es **AGPL-3.0**; los pesos derivados también se consideran sujetos a ella. Para uso interno de la tienda no supone problema práctico. Si el servicio se ofrece a terceros por red, hay que publicar el código bajo AGPL o adquirir la licencia comercial de Ultralytics. El resto del proyecto es Apache 2.0. Datos: Open Images (CC BY 4.0 / CC BY 2.0, con atribución en `attribution.csv`).

## 8. Integración en la aplicación (conteo inteligente)

- **Inferencia**: `backend/app/ai/detector.py` usa ONNX Runtime en CPU, sin PyTorch en el servidor. Hace un *letterbox* idéntico al de Ultralytics, decodificación YOLO y NMS (`postprocess.py`, compartido con los scripts de exportación y verificación).
- **Umbral**: el `recommended_confidence` del modelo, salvo que se fije `AI_CONFIDENCE`.
- **Selección del modelo**: carga la versión más reciente de `AI_MODELS_DIR` o la fijada en `AI_MODEL_VERSION`.
- **Sin modelo, o con un modelo dañado o que falla** → conteo **manual**, con aviso y sin detecciones inventadas.
- **Flujo**:
  1. Foto (validada y re-codificada).
  2. Detecciones con confianza (zapatos **individuales**).
  3. Revisión: un clic rechaza un falso positivo y arrastrar añade un omitido.
  4. Desglose explícito en **pares completos** y **zapatos sueltos** (2 × pares + sueltos = zapatos marcados).
  5. Confirmación (`counts.confirm`).
  6. Conciliación opcional con **una** variante: registra un movimiento `conteo_fisico` con la diferencia, el motivo y el usuario.

  La foto y la confirmación **nunca** cambian el stock (probado).
- **Qué se guarda** (`ai_counts`, `ai_detections`): usuario, fecha, imagen, versión del modelo, umbral, tiempo de inferencia, detectados, aceptados, manuales, rechazados, zapatos confirmados, pares, sueltos, quién confirmó, variante, stock antes, pares contados, diferencia, quién aplicó, notas y estado.
