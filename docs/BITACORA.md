# Bitácora de shoe_counter_ai

Registro cronológico de todo lo que se hace en el proyecto. Cada entrada indica fecha, fase, archivos tocados, pruebas reales y pendientes. El detalle de cada fase está en su propio documento dentro de `docs/`.

| Documento | Contenido |
|---|---|
| [00-auditoria-fase0.md](00-auditoria-fase0.md) | Auditoría inicial, problemas, arquitectura y plan |

---

## 2026-10-20 — Fase 0: Auditoría

**Qué se hizo**
- Lectura de todos los archivos del repositorio y comparación por hash de la raíz con `web/`.
- Inspección del notebook de `entrenamiento/`, del modelo de `modelo/` y del `compose.yaml`.
- Comprobación del entorno: Python, Docker, GPU, paquetes y puertos.

**Archivos creados**
- `docs/00-auditoria-fase0.md`
- `docs/BITACORA.md`

**Archivos modificados o borrados:** ninguno.

**Pruebas ejecutadas**
- No hay pruebas automatizadas en el proyecto.
- `docker info` falló porque Docker Desktop no estaba en ejecución.

**Hallazgos clave**
- El contenido actual es "Patitas IA" (perros/gatos), no un sistema de zapatos.
- `web/` es una copia idéntica de la raíz.
- `compose.yaml` referencia `docker/Dockerfile`, que no existe.
- El notebook de zapatos es de Kaggle, de clasificación de marca y sin pesos: no es un detector.
- Los `.bin` actuales son shards de TensorFlow.js.

**Pendientes / decisiones abiertas**
- Confirmar la decisión D1 (Patitas IA a `legacy/`).
- Encender Docker Desktop para la Fase 1.
- Conseguir el archivo comercial (Fase 3) y el dataset de detección (Fase 5).

**Cómo volver atrás:** no hay cambios que revertir; basta con borrar los dos documentos nuevos.
