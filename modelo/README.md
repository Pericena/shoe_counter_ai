# modelo/

Artefactos versionados del **detector de zapatos**. Detalle completo, métricas y limitaciones: [../docs/04-ia-detector.md](../docs/04-ia-detector.md).

| Carpeta | Contenido | ¿En Git? |
|---|---|---|
| `pesos/<versión>/best.pt` | Pesos nativos (Ultralytics/PyTorch) + `metadata.json` | No (`.gitignore`): copiar a mano o regenerar con `entrenamiento/` |
| `exportados/<versión>/model.onnx` | Modelo que ejecuta la app (ONNX Runtime, CPU, entrada fija 640×640) | No |
| `exportados/<versión>/metadata.json` | Versión, fecha, parámetros, hardware, SHA-256 del dataset y de los pesos, métricas **del ONNX**, umbral recomendado y paridad backend ↔ Ultralytics | No |
| `resultados/` | Reservado para informes adicionales | No |

## Versión actual: `shoe-det-v001`

- YOLO11s ajustado con 2.400 imágenes de Open Images (clase única «zapato»), entrenado el 2026-10-20.
- La app usa automáticamente la versión más reciente, o la fijada en `AI_MODEL_VERSION`.
- El umbral de confianza es el `recommended_confidence` de `metadata.json`, salvo que se fije `AI_CONFIDENCE`.

**Reglas**:

- Cada entrenamiento crea una carpeta de versión nueva; `exportar.py` se niega a sobrescribir.
- No se elimina una versión mientras haya conteos registrados con ella: `ai_counts.model_version` la referencia para la trazabilidad.

## Formato `.bin`

No se generó ningún `.bin`: solo tiene sentido para un runtime concreto (OpenVINO `model.xml + model.bin`, NCNN `.param + .bin` o TensorFlow.js `model.json + *.bin`). Renombrar `best.pt` a `.bin` no convierte el modelo.

## Modelo anterior (eliminado)

El clasificador perro/gato de Patitas IA (TensorFlow.js) se eliminó el 2026-10-20 y se puede consultar en el tag `respaldo-pre-fase1`. No tenía relación con zapatos.
