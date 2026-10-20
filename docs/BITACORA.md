# Bitácora de shoe_counter_ai

Registro cronológico de todo lo que se hace en el proyecto. Cada entrada indica fecha, fase, archivos tocados, pruebas reales y pendientes. El detalle de cada fase está en su propio documento dentro de `docs/`.

| Documento | Contenido |
|---|---|
| [00-auditoria-fase0.md](00-auditoria-fase0.md) | Auditoría inicial, problemas, arquitectura y plan |
| [01-fase1-base.md](01-fase1-base.md) | Fase 1 (parte 1): backend, BD, API de inventario, Docker, ejecución |
| [02-arquitectura-datos-comerciales.md](02-arquitectura-datos-comerciales.md) | Importación Excel/CSV, diccionario de datos y política de duplicados |
| [03-autenticacion-seguridad.md](03-autenticacion-seguridad.md) | Login, roles, permisos, auditoría y seguridad |
| [04-ia-detector.md](04-ia-detector.md) | Datasets, entrenamiento, métricas, exportación y conteo inteligente |
| [05-camara-ocr.md](05-camara-ocr.md) | Cámara en vivo y lector de etiquetas (OCR) |
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

### Entrenamiento y evaluación del detector (resultados reales)

- **Entrenamiento** `shoe-det-v001`: YOLO11s, 60 épocas completas, ~4 h 30 min en la RTX 3050, `workers: 0`. Evolución de mAP50 en val: 0,216 (época 1) → 0,502 (10) → 0,574 (20) → 0,628 (35) → 0,660 (47) → 0,663 (59).
- **Mejor checkpoint**: época 59 según la *fitness* de Ultralytics (0,9·mAP50-95 + 0,1·mAP50). `best.pt` es ese checkpoint, no el de la última época. No se repitió el entrenamiento.
- **Evaluación** del `.pt` y del **ONNX desplegado** en val, test y test externo (Kaggle), con el umbral elegido solo en val. Tablas completas en [04-ia-detector.md](04-ia-detector.md) §4. Métricas oficiales (ONNX):

  | Conjunto | P | R | mAP50 | mAP50-95 | MAE de conteo | Exactas |
  |---|---|---|---|---|---|---|
  | test | 0,767 | 0,619 | 0,687 | 0,379 | 1,23 | 40,0 % |
  | test externo | 0,853 | 0,747 | 0,823 | 0,556 | 0,56 | 56,9 % |

- **Falsos positivos y negativos** (galerías `peores_*.jpg`):
  - FN en multitudes con zapatos diminutos.
  - FP en patas de perro, objetos y dibujos.
  - Errores de localización que incluyen la pierna.
  - **Una fila de 10 zapatos expuestos con solo 4 detectados**: el escenario de tienda no está bien cubierto.
- **Independencia del test externo**: 0 casi duplicados con Open Images, otra fuente y el mismo objetivo (una caja por zapato). Tiene ruido de anotación y marcas de agua de bancos de imágenes.
- **Exportación** versionada: `modelo/pesos/shoe-det-v001/best.pt` y `modelo/exportados/shoe-det-v001/model.onnx` + `metadata.json`.

### Defecto encontrado: paridad ONNX del backend

- La comprobación de exportación dio 26/40 conteos iguales.
- El diagnóstico atribuyó la causa al preprocesado con PIL del backend: 32/40 frente al ONNX de Ultralytics, mientras que con un letterbox OpenCV idéntico daba 40/40.
- Corrección: `postprocess.letterbox` replica a Ultralytics (dependencia nueva `opencv-python-headless==5.0.0.93` en el backend), y `exportar.py` ahora aborta si no hay paridad.
- Nuevo `scripts/verificar_onnx.py`: **60/60 en test y 60/60 en test externo**. Fija en `metadata.json` las métricas del ONNX y el umbral recomendado de 0,20.
- La app usa ese umbral salvo que `AI_CONFIDENCE` lo fije.

### Integración real del detector

- **Servidor local**: 3 fotos de test subidas por HTTP → modelo `shoe-det-v001` con 2, 3 y 5 detecciones y sus confianzas, ~0,6 s por foto en CPU. La vista de revisión muestra las cajas alineadas. Un falso positivo (40 %) solapado sirvió para comprobar el rechazo.
- **Contenedor Docker**: detección con el modelo montado en solo lectura, umbral 0,20 tomado del modelo, 5 detecciones en 308 ms.

### Otros cambios de este bloque

- **Fotos de producto**: subida en el formulario de creación y edición (varias, con vista previa) y botón rápido «Foto» en la lista. Además de la subida que ya había en el detalle.
- **Archivo real MANACO-INTERMEDIO** (en `datos/ejemplos/`; no se modificó ni se importó):
  - El `.xlsx` es válido: 240 filas, de las que 10 claves aparecen 2 veces con valores distintos.
  - El `.csv` está **corrupto**: perdió la última letra de los campos con tildes.
  - Se añadió la política de duplicados «rechazar» / «separados» (migración `9765b6bfd4c2`, columna `occurrence`), la detección del CSV truncado y la sugerencia del tipo de importación correcto. Durante la sesión el usuario subió el archivo como «Catálogo» y obtuvo 0 filas válidas; ahora se le indica que es «Comercio exterior».
- **Robustez**: si el modelo falla durante la inferencia, el conteo pasa a modo manual con aviso, sin dar un error 500.
- **Limpieza**: carpetas `runs/` y `weights/` que Ultralytics creó en la raíz (configuración apuntada a `entrenamiento/`), `install_torch.log`, el logo de robot y los favicons de Patitas.

### Pruebas ejecutadas al cierre

| Entorno | Resultado |
|---|---|
| SQLite (`pytest`) | **107 aprobadas, 2 omitidas** (las de concurrencia, que exigen PostgreSQL). pyflakes sin avisos salvo las importaciones intencionadas de modelos |
| PostgreSQL 16 real (contenedor, base `shoe_counter_test`) | **109 aprobadas, 0 omitidas**, incluidas 2 de concurrencia (6 compradores por 1 unidad → 1 aceptado y 5 rechazados) |
| Docker | Imagen reconstruida; migraciones 1→3 aplicadas en PostgreSQL; `app` y `db` *healthy*; `/api/health` OK |
| Persistencia | Tras `docker compose down` + `up` se conservan la revisión del esquema, los roles y las bases. Volumen `shoe_counter_ai_pgdata` |
| Copia de seguridad documentada | `pg_dump -Fc` y `pg_restore` en una base temporal: esquema y 42 permisos restaurados. Base temporal y volcado borrados después |
| Verificación manual en navegador | Fotos de producto (formulario y lista), revisión de un conteo con el modelo real, BI y tienda (ver entrada anterior) |

**No probado o pendiente**:

- Rendimiento del detector con **fotos reales de la tienda**: no hay ninguna.
- Envío real de correo SMTP: no hay servidor configurado.
- Pasarela de pagos: no se integró a propósito.
- Revisión visual a pantalla completa: el panel del navegador era pequeño.

**Estado de la base de desarrollo** (`storage/dev.sqlite3`): contiene datos marcados PRUEBA de mis verificaciones y las acciones que hizo el usuario durante la sesión (conteo #9, importación #2). No se borró para no perder lo del usuario. Para empezar de cero: detén el servidor, borra `storage/dev.sqlite3`, ejecuta `flask --app run db upgrade` y crea el administrador.

**Docker**: los contenedores quedaron detenidos (`docker compose stop`) para liberar RAM. La base PostgreSQL principal solo contiene el esquema, sin usuarios: el primer administrador se crea con `users create-admin`.


---

## 2026-10-20 (noche) — CSV de Manaco, cámara en vivo y lector de etiquetas (OCR)

**Petición del usuario**: el CSV de Manaco se veía con «��» y daba «faltan columnas»; quiere activar la cámara para el conteo y el inventario, que se vaya registrando la imagen, y usar OCR (por ejemplo, para la marca).

### CSV de Manaco

- **Diagnóstico con bytes reales**: el `.csv` es UTF-8 válido, pero cada campo con tildes o ñ **perdió su último carácter** (pérdida de datos real). Además no tiene BOM, por eso Excel muestra «��». El error «faltan codigo_producto, marca…» salió porque se subió con el tipo «Catálogo».
- Se verificó que el `.csv` es exactamente el `.xlsx` truncado (240 filas, números iguales) y se generó **`MANACO-INTERMEDIO_corregido.csv`** a partir del `.xlsx`: UTF-8 con BOM, `;` y coma decimal. Valida igual que el `.xlsx`. Los originales no se tocaron.
- **Importación con «Detectar automáticamente»** (nueva opción por defecto): reconoce el tipo por las columnas, incluso con encabezados truncados.

### Cámara en vivo (Conteo inteligente)

- `POST /api/ai/detect`: detección sobre un fotograma **sin guardarlo**.
- La interfaz dibuja las cajas y el conteo sobre el vídeo (unos 140–200 ms por fotograma en local).
- «Registrar foto y contar» guarda la foto como conteo pendiente de revisión, así que el stock no cambia sin confirmación.
- `web/js/camera.js` se comparte con el lector de etiquetas.

### Lector de etiquetas (nuevo menú)

- `POST /api/ocr/analyze`: `zxing-cpp` lee los códigos de barras y QR, y `rapidocr-onnxruntime` (modelos incluidos, sin Internet) el texto.
- Propone marca (solo si está escrita y registrada), talla, color, precio y SKU, y busca la variante.
- Acciones disponibles: registrar un movimiento, o crear el producto o la variante **prellenados**.
- La imagen se guarda en privado (`storage/etiquetas/`, migración `e865ca134acc`) y la lectura queda en la auditoría.
- **Límite**: no reconoce logotipos (ver [05-camara-ocr.md](05-camara-ocr.md)).

### Defectos encontrados

- **OCR**: lee «4O» por «40» y une palabras («TALLA4ONEGRO»). Se toleran las confusiones solo cuando no hay ambigüedad; si la hay, no se propone talla.
- **Caracteres de control**: al editar con scripts se colaron caracteres invisibles (``, ``) en dos archivos. Se corrigieron y se escaneó todo el repositorio sin encontrar más.

### Dependencias nuevas

- En `requirements.txt`: `zxing-cpp==3.1.1`, `pyclipper`, `shapely`, `six`, `PyYAML`, `tqdm`.
- `rapidocr-onnxruntime==1.4.4` va en `requirements-nodeps.txt` y se instala con `--no-deps`, porque pediría el OpenCV con interfaz gráfica, que en Docker necesita libGL. El módulo `cv2` lo aporta `opencv-python-headless`.

### Pruebas

| Entorno | Resultado |
|---|---|
| SQLite | **113 aprobadas, 2 omitidas** (concurrencia, solo PostgreSQL) |
| PostgreSQL 16 en Docker (imagen reconstruida, migración 4 aplicada) | **115 aprobadas, 0 omitidas**, incluidas las de OCR y códigos de barras en Linux |
| Servidor local (HTTP real) | Vivo: 5 zapatos en 144 ms, 0 conteos guardados. Etiqueta: EAN 7790000000010, talla 40, Negro, 180.00 |
| UI | Las pantallas «Lector de etiquetas» y «Cámara en vivo» cargan sin errores |

**No probado**: la cámara física del dispositivo (requiere conceder el permiso en el navegador del usuario).


---

## 2026-10-20 (noche, 2) — Producto reconocido: ficha completa y datos relacionados

**Petición**: si el producto ya está registrado, que al detectarlo (OCR, cámara o foto) se vean su modelo, su marca y todas sus características junto con la cantidad, y que los datos del inventario estén bien relacionados.

**Hecho**:

- **Ficha consolidada** (`app/products/services.py::product_card`, `GET /api/products/<id>/overview`):
  - identidad y características;
  - totales (pares, valor a costo y a precio, vendidos en 30 días, reservados por pedidos abiertos, bajas y agotadas);
  - matriz talla × color con stock y variante reconocida;
  - últimos movimientos y conteos.
- **Lector de etiquetas**: devuelve y muestra la ficha de cada producto reconocido.
- **Conteo**:
  - identificación automática por el código o la etiqueta de la **misma foto**;
  - selección desde la cámara en vivo («Identificar producto» con una franja sobre el vídeo);
  - corrección manual.
  - Se guarda en `ai_counts.identified_variant_id` + `identification` (migración `090f29bf83c0`).
  - La revisión muestra «Foto frente a inventario» y la ficha; la conciliación preselecciona la variante identificada.
- **Existencias**: columnas «Vendidos 30 d» y «Último mov.». El detalle del producto incluye la ficha, los movimientos y los conteos.
- **Interfaz**: plurales correctos («1 par», «2 pares»).

**Pruebas**:

| Prueba | Resultado |
|---|---|
| `test_identification.py` (4 pruebas nuevas) | Aprobadas |
| SQLite | **117 aprobadas, 2 omitidas** (concurrencia) |
| PostgreSQL en Docker (migración 5 aplicada) | **119 aprobadas** |
| Servidor real | Una foto con EAN identificó `PRUEBA-UI-1-40-N` y mostró su ficha y la comparación |
| Interfaz (DOM) | Conteo, producto y Existencias sin errores |

**Aviso**: el panel del navegador integrado de Claude **bloquea la cámara**. Para usarla, abre `http://localhost:8088` en Chrome o Edge.

## 2026-10-20 — Prompt maestro (POS, compras, integraciones, BI): integración del backend

**Hecho y verificado**
- Módulos registrados en la app: ventas/devoluciones (TPV), compras y reposición, integraciones (entrada `/api/integrations/inbound/<code>/events` con `X-Integration-Key`, sin CSRF), notificaciones, registro inteligente por visión, analítica (KPI, pronóstico, anomalías, duplicados, datos incompletos) y Power BI (`/api/bi/datasets/<conjunto>.csv|json` con sesión `bi.view` o token Bearer; CLI `flask bi create-views` y `flask bi create-reader`, la contraseña se toma de `BI_READER_PASSWORD`).
- Las cajas del conteo IA se pueden asociar a una variante (`ai_detections.variant_id`) y se muestra el desglose `by_variant`. Las líneas de pedido guardan el costo (`order_items.unit_cost`).
- Migración `dcc9820fdb23`: crea la ubicación PRINCIPAL, `stock_levels` a partir del stock actual, asigna ubicación y canal al libro mayor histórico y cambia las restricciones (`movement_not_empty`, nuevos tipos, `channel_valid`, `pendiente_revision`, propósitos de archivos). También siembra los permisos y roles nuevos.
  - Se probó contra una copia de la base dev: upgrade, conciliación correcta, downgrade, upgrade otra vez, y `flask db check` sin diferencias.
  - Después se aplicó a `storage/dev.sqlite3`.
- Asistente de importación:
  - Asignación manual de columnas: `POST /api/imports/<id>/mapping`.
  - Columnas nuevas: nombre, subcategoría, segmento, material, temporada, colección, sistema de tallas, proveedor, ref. de proveedor, imagen_url, stock_inicial y ubicación. imagen_url nunca se descarga: el producto queda con la foto pendiente.
  - Vista previa por fila (crear, actualizar, omitir o revisar) contra la base de datos.
  - Validación de talla, color, código de barras y precio.
  - El stock inicial es idempotente por variante y ubicación.
  - Bloquea los duplicados de marca y modelo con otro código.
  - Informe `GET /api/imports/<id>/issues.csv`.
- Pruebas (SQLite):
  - La suite completa pasa: 117 pruebas, 2 omitidas. Se ajustaron las pruebas de la tienda al nuevo modelo de reservas.
  - Nuevas en `tests/test_escenarios.py`: 8 pruebas, todas pasan. Cubren los escenarios §16 5, 6, 7, 8, 11, 12, 13, 14, 15 (parcial), 16, 18, 19 y 20.

**Pendiente**
- Escenarios §16 sin prueba nueva: 1, 2, 3, 4, 9 y 10. Algunos los cubren en parte pruebas existentes (products, ai, identification, inventory). Para 2, 3 y 4 falta una prueba de `/api/vision/*` con imágenes sintéticas.
- Ejecutar la suite en PostgreSQL (Docker) y probar `flask bi create-views` en PostgreSQL.
- Frontend de los módulos nuevos: TPV, compras, ubicaciones, integraciones, notificaciones, registro inteligente, KPI y tokens de BI.
- Documentos 10–13 (integraciones, compras, notificaciones, Power BI) y actualización del README.
