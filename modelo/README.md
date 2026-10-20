# modelo/

Carpeta reservada para el **detector de zapatos** (Fase 5). Hoy **no hay ningún modelo de zapatos entrenado**.

| Carpeta | Contenido previsto | ¿En Git? |
|---|---|---|
| `pesos/` | Pesos nativos versionados, p. ej. `shoe-det-v001/best.pt` | No (`.gitignore`) |
| `exportados/` | Exportaciones para inferencia, p. ej. `shoe-det-v001/best.onnx` | No |
| `resultados/` | Métricas, matrices de confusión y ejemplos de evaluación | No |

Cada versión irá con una ficha (`FICHA.md`): fecha, versión de Ultralytics, dataset y su licencia, hiperparámetros y métricas (precision, recall, mAP50, mAP50-95). **Ningún peso se sobrescribe:** cada entrenamiento crea una carpeta de versión nueva.

## Modelo anterior (eliminado el 2026-10-20)

Aquí estaban `model.json` y `group1-shard{1,2}of2.bin`: el clasificador **perro/gato** de Patitas IA, en formato **TensorFlow.js layers-model**. Los `.bin` eran *shards* de pesos de TF.js (solo funcionan junto a `model.json`). **No tenía relación con zapatos.** Se eliminó a petición del usuario. Se puede recuperar así:

```bash
git checkout respaldo-pre-fase1 -- modelo/
```

## Sobre el formato `.bin`

Renombrar `best.pt` a `.bin` no convierte el modelo. Hay formatos `.bin` reales, cada uno para un runtime distinto:

| Runtime | Archivos |
|---|---|
| TensorFlow.js | `model.json` + `*.bin` |
| OpenVINO | `model.xml` + `model.bin` |
| NCNN | `model.param` + `model.bin` |

Solo se generará uno si se define el runtime que lo va a usar. Para el backend se usará ONNX.
