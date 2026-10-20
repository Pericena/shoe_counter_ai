# Fase 0 — Auditoría de `shoe_counter_ai`

| | |
|---|---|
| Fecha | 2026-10-20 |
| Alcance | Lectura completa del repositorio y del entorno local. **No se modificó ni borró ningún archivo existente.** |
| Commit base | `ab67904 Initial commit` (solo contiene `README.md`; el resto del proyecto está sin versionar) |

---

## 1. Estado actual del proyecto

### 1.1 Hallazgo principal

El repositorio se llama `shoe_counter_ai`, pero **lo que contiene es otro proyecto: "Patitas IA", un clasificador de fotos de perros y gatos**. No existe todavía ninguna funcionalidad de zapatos, inventario, ventas, base de datos, backend ni análisis de datos.

| Pieza | Qué es realmente |
|---|---|
| `index.html` (609 líneas, ~38 KB) | Página estática "Patitas IA". Carga TensorFlow.js 4.22.0 y COCO-SSD 2.2.3 desde CDN, filtra que haya perro/gato y luego clasifica con el modelo propio. Historial en `localStorage`. |
| `modelo/model.json` + `group1-shard{1,2}of2.bin` | Modelo **TensorFlow.js (layers-model)** `patitas_classifier`: CNN Keras, entrada 100×100×1 en gris, salida sigmoide perro/gato. ~5,3 MB. |
| `cuaderno/Clasificador_de_perros_y_gatos.html` | Cuaderno exportado a HTML del entrenamiento perros/gatos. |
| `entrenamiento/shoe-brand-classification-nike-adidas-converse.ipynb` | Notebook **de terceros (Kaggle)** de **clasificación de marca** (Adidas/Converse/Nike) con InceptionV3. 642 imágenes de entrenamiento, 69 de validación, 10 épocas, exactitud de validación ≈ 0,80. Rutas `../input/...` de Kaggle; no se puede ejecutar localmente tal cual. **No produce pesos en el repo** y **no es un detector**. |
| `assets/` | Iconos, favicon, logo e ilustración `mascotas.svg`. |
| `docs/imagenes/` | 5 imágenes del README de Patitas IA. |
| `service-worker.js`, `manifest.webmanifest` | PWA funcional de Patitas IA (caché `patitas-shell-v4`). |
| `compose.yaml` | Un servicio `patitas-ia` que construye `docker/Dockerfile` y publica `8080:8080`. |
| `README.md` | Documentación de Patitas IA (modificado respecto al commit, sin commitear). |
| `LICENSE` | Apache 2.0. |

### 1.2 Duplicación completa `raíz/` ↔ `web/`

Se compararon los hashes MD5: **todos los archivos de `web/` son idénticos a los de la raíz** (`index.html`, `styles.css`, `service-worker.js`, `manifest.webmanifest`, `modelo/*`, `cuaderno/*`, `assets/*`). Hay ~7,9 MB duplicados. El README y el `compose.yaml` consideran `web/` como la carpeta oficial.

### 1.3 Archivos referenciados que no existen

| Referencia | Dónde | Estado |
|---|---|---|
| `docker/Dockerfile` | `compose.yaml` | **No existe** → `docker compose up --build` falla hoy. |
| `docker/nginx.conf` | README §5 | No existe. |
| `entrenamiento/Clasificador_de_perros_y_gatos.ipynb` | README §3 y §6 | No existe (en su lugar está el notebook de zapatos de Kaggle). |
| `.gitignore` | — | No existe. |

### 1.4 Entorno local comprobado (resultados reales)

| Herramienta | Resultado |
|---|---|
| Python | 3.12.10 (`python`, instalado desde Microsoft Store) y 3.12.4 (`py`) |
| Paquetes ya instalados globalmente | Flask 3.1.3, Flask-SQLAlchemy 3.1.1, Flask-Migrate 4.1.0, Flask-Login 0.6.3, Flask-WTF 1.3.0, SQLAlchemy 2.0.51, pandas 3.0.5. **No** están: openpyxl, ultralytics, torch, pytest, psycopg, reportlab. |
| Docker | CLI 29.7.2 y Compose v5.5.0 instalados, pero **el demonio de Docker Desktop no estaba en ejecución** (`failed to connect to the docker API`). No se pudo probar ningún contenedor. |
| PostgreSQL | `psql` no está instalado en el host (se usará en contenedor). |
| GPU | NVIDIA GeForce RTX 3050 Laptop, 6 GB VRAM → apta para entrenar YOLO tamaño *nano/small* con batch moderado. |
| Node | v22.23.2 (no es necesario para el proyecto). |
| Puertos | En el momento de la auditoría no había nada escuchando en 80, 443, 3306, 5000, 5432, 8000, 8080, 8081 (XAMPP apagado). |

> **Conflicto de puertos:** XAMPP usa por defecto Apache **80/443**, MySQL **3306** y Tomcat **8080**. El `compose.yaml` actual publica **8080**, que choca con Tomcat de XAMPP si se inicia.

---

## 2. Funcionalidades existentes que deben conservarse

Funcionan en código (revisado línea a línea en `index.html`), aunque pertenecen a Patitas IA:

1. **Carga de imagen con validación** de tipo MIME (JPG/PNG/WEBP/GIF) y tamaño (12 MB) — `showSelectedPhoto()`.
2. **Cámara frontal/trasera** con `getUserMedia` y espejo — `startCamera()`, `stopCamera()`.
3. **Preprocesado en canvas** — `prepareInput()`.
4. **Inferencia en navegador** con TF.js y liberación correcta de tensores (`tf.tidy`, `dispose`).
5. **Estado de carga y errores** explícitos (no inventa resultados si el modelo no carga).
6. **Historial local** saneado al leer (`renderHistory()` filtra entradas inválidas) y sin `innerHTML` con datos del usuario.
7. **PWA**: instalación, service worker con caché del *shell* y de recursos externos.
8. **Accesibilidad**: `aria-live`, `focus-visible`, `prefers-reduced-motion`.
9. **Lectura en voz alta** del resultado (SpeechSynthesis).

**Qué se reutilizará para shoe_counter_ai:** el patrón de carga/cámara/validación/estado/PWA y el estilo visual. El clasificador perro/gato **no sirve** para contar zapatos; se conservará intacto como proyecto anterior (ver §5, decisión D1) y no se borrará.

---

## 3. Funcionalidades incompletas o ausentes

Todo lo pedido para shoe_counter_ai está **ausente**:

| Módulo | Estado |
|---|---|
| Backend Flask / API | Ausente |
| PostgreSQL, esquema, migraciones | Ausente |
| Autenticación, roles, CSRF | Ausente |
| Productos, variantes, proveedores | Ausente |
| Movimientos de inventario, conteos físicos, alertas | Ausente |
| Conteo de zapatos / pares con IA | Ausente — **no hay detector, ni dataset, ni pesos de zapatos** |
| OCR / códigos de barras | Ausente |
| Importación Excel/CSV comercial | Ausente — **el archivo comercial no está en el repositorio** |
| BI, gráficos, KPI, síntesis Manaco | Ausente |
| Exportación XLSX/CSV/PDF | Ausente |
| Tienda online, carrito, pedidos | Ausente |
| Pruebas automatizadas | Ausentes (no hay `tests/`, ni pytest) |
| Docker funcional | Roto (falta `docker/Dockerfile`) |

**Elementos que podrían confundirse con funcionalidad real:**

- El notebook de zapatos muestra métricas (≈80 %) de **otro autor, en Kaggle, para otra tarea** (clasificación de marca). No hay pesos de ese modelo en el proyecto. No debe presentarse como "modelo de zapatos entrenado".
- Los "retos" para mascotas (`challenges`) son texto fijo; correcto para Patitas, irrelevante para la tienda.

---

## 4. Problemas técnicos y de seguridad detectados

| # | Severidad | Problema | Recomendación |
|---|---|---|---|
| P1 | Alta | `compose.yaml` apunta a `docker/Dockerfile` inexistente. | Nuevo `Dockerfile` + `compose.yaml` (Fase 1). |
| P2 | Alta | El nombre/propósito del repo no coincide con el contenido; README describe otro proyecto. | Mover Patitas IA a una carpeta de legado y reescribir el README para shoe_counter_ai (conservando el texto anterior). |
| P3 | Media | Código y pesos duplicados en raíz y `web/` (7,9 MB). Riesgo de editar uno y no el otro. | Mantener una sola copia (D1). No borrar hasta confirmar. |
| P4 | Media | No hay `.gitignore`; solo `README.md` está versionado. Riesgo de subir `.env`, fotos, bases de datos o pesos grandes. | Crear `.gitignore` y hacer un commit "snapshot" del estado actual antes de cambiar nada (punto de retorno). |
| P5 | Media | Tailwind se usa con el *Play CDN* (`cdn.tailwindcss.com`), que su propio autor no recomienda para producción. Scripts CDN (TF.js, COCO-SSD, Boxicons) **sin `integrity` (SRI)**. | Para el nuevo frontend: CSS propio o Tailwind compilado una vez; fijar versiones y añadir SRI o servir los archivos localmente. |
| P6 | Media | Sin cabeceras de seguridad (CSP, X-Frame-Options…): el `nginx.conf` que las ponía no existe. | Flask/servidor añadirá cabeceras. |
| P7 | Media | Conflicto de puerto 8080 con Tomcat de XAMPP. | Usar **8088** para la app y no publicar PostgreSQL (o solo `127.0.0.1:5433`). |
| P8 | Baja | README cita `entrenamiento/Clasificador_de_perros_y_gatos.ipynb`, que no existe. | Corregir en la documentación de legado. |
| P9 | Baja | Notebook de Kaggle de terceros sin atribución explícita de autor/licencia en el repo. | Documentar origen; los notebooks públicos de Kaggle suelen ser Apache 2.0, **hay que verificarlo en la página original**. |
| P10 | Baja | Python de Microsoft Store: rutas en `WindowsApps` pueden dar problemas con algunos paquetes nativos (torch/CUDA). | Usar `py -3.12 -m venv .venv` dentro del proyecto. |
| P11 | Info | `manifest.webmanifest` usa `"purpose": "any maskable"` en un SVG (válido, pero el recorte puede verse mal). | Revisar al rehacer el manifest. |

No se encontraron credenciales, tokens ni datos personales en los archivos.

---

## 5. Arquitectura recomendada

### 5.1 Decisiones propuestas (requieren tu confirmación)

- **D1 — Patitas IA pasa a legado, sin borrarse.** Se mueve `web/` a `legacy/patitas_ia/` (o se deja en `web/` y se crea `frontend/`). Las copias duplicadas de la raíz se eliminan **solo después** del commit snapshot y con tu aprobación.
- **D2 — Frontend estático + API Flask en el mismo contenedor.** Flask sirve la API en `/api/*` y los archivos estáticos del frontend nuevo. Sin React/Vue. Un único puerto.
- **D3 — PostgreSQL 16 en contenedor**, volumen nombrado, sin puerto público (opcional `127.0.0.1:5433` para depurar).
- **D4 — Inferencia YOLO en el backend (Python)**, no en el navegador. El navegador solo sube la foto y muestra cajas. Si no hay pesos → estado "modelo no configurado".
- **D5 — Entrenamiento en entorno separado** (`entrenamiento/requirements.txt`, venv propio con PyTorch CUDA) para que la imagen Docker del backend no cargue con CUDA.
- **D6 — Stock con fuente única de verdad:** tabla `inventory_movements` (libro mayor) + saldo por variante actualizado en la misma transacción con `SELECT … FOR UPDATE`. El saldo debe poder reconstruirse sumando movimientos (prueba automática).

### 5.2 Diagrama

```
Navegador (frontend estático: HTML/CSS/JS + PWA)
        │  HTTP :8088
        ▼
Contenedor "app": Flask (gunicorn)
   ├─ /api/auth        login, roles (admin, inventario, vendedor), CSRF
   ├─ /api/products    productos, variantes, proveedores, fotos
   ├─ /api/inventory   movimientos, conteos físicos, alertas
   ├─ /api/sales       ventas, devoluciones
   ├─ /api/trade       importación/limpieza/consulta de datos comerciales
   ├─ /api/exports     XLSX / CSV / PDF
   ├─ /api/analytics   KPI y series para gráficos
   ├─ /api/ai          detección YOLO + revisión + confirmación
   └─ /api/shop        catálogo público, carrito, pedidos
        │
        ├──► Contenedor "db": PostgreSQL 16 (volumen pgdata)
        └──► Volumen/bind "storage": fotos, procesadas, importaciones, exportaciones
             Bind "modelo/pesos": pesos YOLO de solo lectura
```

### 5.3 Formato `.bin` — respuesta técnica

Los `.bin` **ya presentes** en `modelo/` son *shards* de pesos de **TensorFlow.js**: no son un formato autónomo, solo funcionan junto a `model.json`. Formatos `.bin` reales que podría necesitar el modelo de zapatos:

| Runtime destino | Archivos | ¿Ultralytics lo exporta? |
|---|---|---|
| TensorFlow.js (navegador) | `model.json` + `*.bin` | Sí (`format=tfjs`) |
| OpenVINO (CPU Intel) | `model.xml` + `model.bin` | Sí (`format=openvino`) |
| NCNN (móvil/embebido) | `model.param` + `model.bin` | Sí (`format=ncnn`) |

Plan: entrenar → `best.pt` (nativo) → exportar **ONNX** para el backend. Solo se generará un `.bin` si eliges uno de los runtimes anteriores. **Renombrar `best.pt` a `.bin` no convierte nada.** (Las opciones de exportación se verificarán con la versión instalada de Ultralytics en la Fase 5.)

### 5.4 Dataset de detección (no existe en el repo)

| Fuente | Tipo | Notas |
|---|---|---|
| **Open Images V7**, clase `Footwear` | Cajas delimitadoras | Anotaciones CC BY 4.0; imágenes con licencias de Flickr (mayoritariamente CC BY 2.0). Descargable por clase con FiftyOne o el *downloader* oficial; se convierte a formato YOLO. No distingue izquierdo/derecho ni talla. |
| Roboflow Universe ("shoe detection") | Cajas, a menudo ya en YOLO | Licencia variable por dataset: **revisar cada una**. |
| Fotos propias de la tienda | Cajas anotadas por ti (Label Studio / CVAT) | Imprescindibles para evaluar en condiciones reales (estanterías, cajas, solapamientos). |

El dataset de Kaggle del notebook actual (Nike/Adidas/Converse) **no sirve** para detección: solo tiene la etiqueta de marca por imagen.

---

## 6. Archivos que necesitan modificación

| Archivo | Cambio | Fase |
|---|---|---|
| `compose.yaml` | Reemplazar por servicios `app` + `db`, volúmenes, healthchecks, puerto 8088 (se guarda copia del original en `legacy/`). | 1 |
| `.dockerignore` | Ajustar al nuevo layout (excluir `.venv`, `storage`, `datos`, `backups`, `.env`). | 1 |
| `README.md` | Reescribir para shoe_counter_ai; el texto de Patitas se conserva en `legacy/patitas_ia/README.md`. | 1 |
| `index.html`, `styles.css`, `manifest.webmanifest`, `service-worker.js` (raíz) | Pasan a ser el frontend de shoe_counter_ai (panel), reutilizando estilo y patrones. | 1–2 |

## 7. Archivos nuevos que se crearán

```
.gitignore, .env.example, Dockerfile
backend/ (app/__init__.py, config.py, extensions.py, módulos auth, products,
          inventory, sales, trade, exports, analytics, ai, shop),
          migrations/, tests/, requirements.txt, run.py
frontend/ o web/ nuevo (css/, js/, pages/)
entrenamiento/ (README.md, requirements.txt, configs/, scripts/)
modelo/ (pesos/, exportados/, resultados/, README.md)
datos/ (entrada/, procesados/, ejemplos/ con datos FICTICIOS marcados)
storage/ (fotos/, procesadas/, importaciones/, exportaciones/) — ignorado por git
backups/ — ignorado por git
legacy/patitas_ia/
docs/ (BITACORA.md, un documento por fase, diccionario de datos, decisiones)
```

## 8. Orden de implementación

| Fase | Contenido | Dependencias externas |
|---|---|---|
| 0 | Esta auditoría | — |
| 1 | Snapshot git + `.gitignore`; legado; backend Flask, config por entorno, PostgreSQL, Alembic, Docker, healthchecks, pytest | Docker Desktop encendido |
| 2 | Productos, variantes, movimientos, conteo físico, alertas, auditoría, auth/roles | — |
| 3 | Importación/validación/exportación de datos comerciales | **Tu archivo Excel/CSV comercial** (no está en el repo) |
| 4 | BI: 3 gráficos, KPI, síntesis ejecutiva trazable | Fase 3 con datos reales |
| 5 | Dataset, validación, entrenamiento YOLO, evaluación, versionado, export ONNX | **Dataset descargado** + fotos de la tienda |
| 6 | Integración IA en backend + revisión manual + confirmación de pares | Pesos de la Fase 5 |
| 7 | Tienda online: catálogo, carrito, pedidos con bloqueo de stock | Proveedor de pago (solo si se decide) |
| 8 | Endurecimiento, backups, despliegue HTTPS | Servidor destino |

OCR (§7 del encargo) se tratará como sub‑fase de la 6 (Tesseract o lectura de código de barras con `pyzbar`), evaluando su viabilidad real con fotos de etiquetas.

## 9. Comandos para ejecutar y comprobar

**Estado actual (Patitas IA)** — sin Docker, porque el Dockerfile no existe:

```bash
python -m http.server 8081 --directory web
```

Abrir http://localhost:8081 (se evita 8080 por Tomcat de XAMPP). *No se ejecutó en esta auditoría.*

**Tras la Fase 1 (previsto):**

```bash
docker compose up --build -d
docker compose ps
docker compose exec app flask db upgrade
docker compose exec app pytest -q
```

App en http://localhost:8088. Nunca usar `docker compose down -v` (borra la base de datos).

---

## 10. Lo que necesito de ti para continuar

1. ¿Aceptas **D1** (mover Patitas IA a `legacy/` y eliminar la copia duplicada de la raíz tras un commit de respaldo)?
2. Encender **Docker Desktop** antes de la Fase 1.
3. Para la Fase 3: copiar el archivo comercial a `datos/entrada/` cuando exista la carpeta.
4. Para la Fase 5: confirmar si quieres empezar con Open Images `Footwear` y cuántas fotos propias puedes aportar.
