# Bitácora de shoe_counter_ai

Registro cronológico de todo lo que se hace en el proyecto. Cada entrada indica fecha, fase, archivos tocados, pruebas reales y pendientes. El detalle de cada fase está en su propio documento dentro de `docs/`.

| Documento | Contenido |
|---|---|
| [00-auditoria-fase0.md](00-auditoria-fase0.md) | Auditoría inicial, problemas, arquitectura y plan |
| [01-fase1-base.md](01-fase1-base.md) | Fase 1 (parte 1): backend, BD, API de inventario, Docker, ejecución |
| [02-arquitectura-datos-comerciales.md](02-arquitectura-datos-comerciales.md) | Importación Excel/CSV, diccionario de datos y política de duplicados |
| [03-autenticacion-seguridad.md](03-autenticacion-seguridad.md) | Login, roles, permisos, auditoría y seguridad |
| [04-ia-detector.md](04-ia-detector.md) | Datasets, entrenamiento, métricas, exportación y conteo inteligente |
| [06-bi-reportes.md](06-bi-reportes.md) | Fórmulas de indicadores, BI y exportaciones |
| [07-tienda-online.md](07-tienda-online.md) | Tienda, pedidos y pagos pendientes |
| [08-pruebas.md](08-pruebas.md) | Pruebas automatizadas y verificaciones manuales |
| [09-despliegue-operacion.md](09-despliegue-operacion.md) | Instalación, copias de seguridad y producción |

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

---

## 2026-10-20 — Fase 1 (parte 1): base funcional e inventario mínimo

**Respaldo y Git**
- Commit `415ecfd` ("Respaldo: estado original de Patitas IA + auditoría Fase 0") y tag anotado `respaldo-pre-fase1` en `main`.
- **No se hizo push**, por indicación del usuario.
- El ZIP de respaldo que se generó en `backups/` se borró porque el usuario indicó que no hacía falta. El commit y el tag son el respaldo.

**Eliminado (autorizado por el usuario: "puedes borrar lo de gatos y perros")**
- `web/` original completo: era una copia idéntica de la raíz.
- `index.html`, `styles.css`, `service-worker.js` y `manifest.webmanifest` de Patitas IA.
- `cuaderno/` (cuaderno perro/gato).
- `modelo/model.json` y `modelo/group1-shard{1,2}of2.bin`: clasificador perro/gato en TensorFlow.js. **No era un modelo de zapatos.**
- `docs/imagenes/` (imágenes del README de Patitas).
- `assets/mascotas.svg` y `assets/icon-pwa.svg` (dibujos de mascotas).
- Movidos a `web/assets/`: `LogotipoV2-Simple.png` (robot) y los favicons, que son genéricos.

**Creado**
- `backend/`: `app/` (config, extensions, common, products, inventory), `migrations/` (revisión `fd19e9dd1c4c`), `tests/` (28 pruebas), `requirements*.txt`, `run.py`, `docker-entrypoint.sh`, `pytest.ini`.
- `web/index.html`, `web/css/app.css`, `web/js/app.js`: panel de inventario conectado a la API real.
- `Dockerfile`, `.env.example`, `.gitignore`, `.gitattributes`.
- `modelo/README.md` y `modelo/{pesos,exportados,resultados}/.gitkeep`.
- `entrenamiento/README.md`.
- `docs/01-fase1-base.md` y `docs/02-arquitectura-datos-comerciales.md`.
- `.claude/launch.json`: configuración para arrancar el servidor local desde Claude Code.
- No versionados (ignorados por Git): `.venv/`, `.env` (con claves aleatorias de desarrollo) y `storage/` con `dev.sqlite3` vacía.

**Modificado**
- `compose.yaml`: antes había un único servicio Nginx en el puerto 8080 que dependía de `docker/Dockerfile`, inexistente. Ahora tiene los servicios `db` (postgres:16-alpine, volumen `pgdata`, healthcheck) y `app` (Flask/gunicorn, `127.0.0.1:8088`, `./storage` montado), con red interna y PostgreSQL sin puerto publicado.
- `.dockerignore`: adaptado al nuevo layout.
- `README.md`: reescrito para Shoe Counter AI.

**Pruebas ejecutadas (resultados reales)**

| Prueba | Resultado |
|---|---|
| `pytest` (SQLite en memoria): app, productos, variantes, movimientos, conteo físico, conciliación, migraciones upgrade/downgrade | **28 passed** |
| `flask db upgrade` sobre SQLite local | OK; crea las 4 tablas |
| Panel en el navegador (http://localhost:8088, waitress): crear producto → variante → entrada de 5 pares → venta de 9 | La venta se rechazó con "Stock insuficiente"; stock 5; valor a costo 500,00; historial correcto |
| Conciliación tras la prueba manual | `ok: true`, sin diferencias |
| Intento de salir de la carpeta web con `../` desde el navegador | 404 |
| Cabecera CSP presente y consola sin errores (salvo el 409 esperado) | OK |
| `docker compose config` | Sintaxis válida; puerto `127.0.0.1:8088`; volumen `pgdata` |

Los datos de la prueba manual (marcados como `PRUEBA`) se borraron. La base de desarrollo quedó con 0 registros.

**No se pudo ejecutar**
- `docker compose up` y PostgreSQL real: Docker Desktop no estaba en ejecución (`failed to connect to the docker API`). **No se afirma que la configuración Docker funcione** hasta probarla.
- La concurrencia real de `SELECT … FOR UPDATE`: SQLite ignora ese bloqueo. Se probará con PostgreSQL.

**Error encontrado y corregido durante la prueba**
- Las fechas se mostraban con 4 h de desfase: SQLite devuelve fechas sin zona horaria. Se añadió `common.iso()`, que marca esas fechas como UTC, y una prueba que lo verifica.

**Pendientes**
1. Encender Docker Desktop y probar `docker compose up --build -d` y luego `pytest` contra PostgreSQL.
2. Fase 1 (parte 2) / Fase 2: usuarios, roles, CSRF, auditoría, fotos de producto y sesiones de conteo físico.
3. Fase 3: esperar el Excel original de datos comerciales.
4. Fase 5: dataset de detección.

**Cómo volver atrás**
- Ver el estado original sin perder nada: `git stash -u` y luego `git checkout respaldo-pre-fase1`.
- Recuperar solo el modelo perro/gato: `git checkout respaldo-pre-fase1 -- modelo/`.
- Descartar todos los cambios de la Fase 1 (destructivo): `git reset --hard respaldo-pre-fase1` y luego `git clean -fd`. Esto también borra `.env` y `storage/` si se añade `-x`.

---

## 2026-10-20 (tarde) — Sistema completo: autenticación, inventario, IA, importación, BI, tienda

Reglas de esta etapa (del usuario): sin `git push`, sin commits, tags, ZIP ni respaldos nuevos; avanzar sin pedir aprobación por fase; eliminar lo de Patitas IA que no aporte.

### Implementado (resumen; detalle en docs/02–09)

| Área | Estado |
|---|---|
| Autenticación | Login y logout, scrypt, sesión `HttpOnly`/`SameSite`, CSRF en toda escritura, bloqueo por intentos, contraseña temporal obligatoria, recuperación por token (necesita SMTP), invalidación de sesiones, CLI `users create-admin`/`reset-password`/`list` |
| Roles y permisos | 4 roles × 16 permisos en BD, sembrados por migración; denegación por defecto en `/api/*` |
| Auditoría | `audit_logs` para todas las operaciones relevantes; pantalla solo para administradores |
| Catálogo | Marcas y categorías normalizadas (migradas desde texto), proveedores, fotos de producto re-codificadas sin EXIF, publicación en tienda |
| Inventario | Movimientos con usuario, permisos por tipo, paginación y filtros, búsqueda por código de barras, bloqueo `FOR UPDATE` con `populate_existing` |
| Conteo inteligente | Detección ONNX (CPU), revisión con cajas, desglose en pares y sueltos, confirmación, conciliación con `conteo_fisico`, modo manual sin modelo o si el modelo falla, imagen anotada, CLI `ai export-dataset` para reentrenar con fotos de la tienda |
| Importación | Catálogo y comercio exterior; vista previa, validación, duplicados, rechazos, confirmación, historial, plantillas |
| BI / reportes | Series, rotación, ajustes, precisión de la IA, BI de comercio exterior (3 visualizaciones + KPI + síntesis trazable), CSV/XLSX con metadatos, PDF |
| Tienda | Catálogo público, carrito, pedidos transaccionales, estados, cancelación y devolución con reposición de stock, consulta pública |
| Frontend | Nuevo diseño con barra lateral y 12 secciones, módulos ES sin CDN (CSP estricta), gráficos SVG propios, modo oscuro, adaptable a móvil |
| Docker | Compose: `app` + `db` (PostgreSQL 16) con healthchecks, volumen `pgdata`, `storage` y `modelo/exportados` montados, puerto `127.0.0.1:8088` |

### Archivos

- **Creados**:
  - `backend/app/{auth,audit,files,ai,imports,exports,reports,shop}/…`
  - migración `178fd8c60df3` (con migración de datos de marcas y categorías y siembra de roles)
  - `tests/test_{auth,ai,imports_exports,shop_reports,concurrency_pg}.py`
  - `web/{login.html,tienda.html,css/shop.css,js/*.js,js/views/*.js,assets/logo.svg,manifest.webmanifest}`
  - `entrenamiento/{requirements.txt,configs/,scripts/*.py,informes/}`
  - `datos/ejemplos/*_FICTICIO.csv`
  - `docs/03,04,06,07,08,09`
- **Modificados**: `backend/app/{__init__,config,common}.py`, `products/*`, `inventory/*`, `migrations/env.py` (solo se quitó una llamada obsoleta), `requirements*.txt`, `Dockerfile`, `compose.yaml`, `.env.example`, `.gitignore`, `README.md`, `docs/01,02`, `entrenamiento/README.md`, `modelo/README.md`.
- **Eliminados**: logo de robot y favicons de Patitas (`web/assets/LogotipoV2-Simple.png`, `favicon*`), sin referencias en el código; `entrenamiento/install_torch.log`; carpetas temporales `runs/` y `weights/` que Ultralytics creó en la raíz (los pesos base se movieron a `entrenamiento/weights/`); la ejecución de prueba `prueba-humo`; el primer intento de entrenamiento, que falló por memoria.
- **Se conserva** `entrenamiento/shoe-brand-classification-…ipynb`: notebook de terceros sobre clasificación de marca, solo como referencia (no es un detector).

### Defectos reales encontrados y corregidos

1. **Venta duplicada bajo concurrencia** (grave). La prueba con PostgreSQL dejó que 6 pedidos simultáneos compraran la **misma** unidad. Causa: SQLAlchemy devolvía la variante ya cargada en la sesión sin refrescarla tras `FOR UPDATE`. Corrección: `execution_options(populate_existing=True)` en todos los bloqueos. Verificado 5 de 5 veces.
2. **Error 500 con pedidos simultáneos**: carrera al crear la fila del limitador por IP (clave única). Corrección: *savepoint* + reintento + `FOR UPDATE`.
3. **Prueba de configuración no determinista** en el contenedor (las variables de entorno se leen al importar). Se reescribió la prueba.
4. **Síntesis con 1 sola limitación** cuando los datos están completos. Se añadieron limitaciones derivadas de la cobertura.
5. **Paréntesis de más** en `products.js`, detectado al recorrer la UI. Se añadió la comprobación de sintaxis con Node y la revalidación de caché de los archivos web.
6. **Fallo de inferencia → 500**. Ahora el conteo pasa a modo manual con aviso; la prueba lo cubre.

### Docker y PostgreSQL (probado de verdad)

- Docker Desktop se inició durante la sesión (servidor 29.7.2).
- `docker compose build` + `up -d`: `db` y `app` en estado *healthy*; las migraciones se aplicaron sobre PostgreSQL; `/api/health` = OK.
- Batería completa dentro del contenedor contra PostgreSQL (base `shoe_counter_test`): aprobada, incluida la concurrencia.
- **Incidente de memoria**: Docker Desktop, el entrenamiento y pytest a la vez agotaron la RAM (7,6 GB) y el entrenamiento cayó en la época 2 (`Unable to allocate 1.17 MiB`). Se detuvieron los contenedores (`docker compose stop`, sin perder datos) y se relanzó el entrenamiento con `workers: 0`.

### Verificación en la interfaz (navegador, datos «PRUEBA» en SQLite de desarrollo)

Login → 12 secciones sin errores → marca, categoría, producto y variante → entrada 6, venta 2, venta 50 rechazada → verificación con el libro → Excel y PDF → tienda: pedido creado y consultado → importación de comercio ficticio (7/1) → BI con 4 gráficos y síntesis → conteo manual de 2 zapatos = 1 par → conciliación −2.

### Datasets

- **Kaggle `nishthakukreti/shoedataset`** (descargado con KaggleHub, sin credenciales, caché `%USERPROFILE%\.cache\kagglehub\datasets\nishthakukreti\shoedataset\versions\1`):
  - 150 imágenes; 137 etiquetadas en YOLO (clase `shoe`, 300 cajas); 13 sin etiqueta; 2 etiquetas huérfanas; 1 duplicado exacto.
  - Escenario A (cajas), pero **licencia «Unknown»** e imágenes de banco de fotos → se usa **solo como test externo**, nunca para entrenar.
  - Informe en `entrenamiento/informes/kaggle_shoedataset/`.
- **Open Images V7**: calzado de las particiones validación y test, con cajas verificadas. 7.877 candidatas tras los filtros (sin cajas de grupo, sin dibujos, sin patines, sin rotación, ≤ 30 cajas) → 3.000 descargadas, con atribución en `attribution.csv`.
- **Particiones** (semilla 42, grupos de pHash ≤ 6 indivisibles): train 2.400 (10.216 cajas), val 300 (1.298), test 300 (1.355), test_externo Kaggle 137 (300). Validación OK y revisión visual de muestras.
