# Shoe Counter AI

Sistema de gestión para **una tienda de calzado**:

- inventario por modelo, talla y color con libro de movimientos;
- conteo de zapatos en fotos con un detector de visión por computadora y revisión humana;
- importación y BI de datos de comercio exterior de calzado;
- reportes, exportaciones;
- tienda online conectada al stock real.

| | |
|---|---|
| **Alumno** | Luishiño Pericena |
| **Stack** | Python 3.12 · Flask 3.1 · SQLAlchemy 2 / Alembic · PostgreSQL 16 · HTML/CSS/JS sin frameworks ni CDN · ONNX Runtime · Ultralytics YOLO (solo entrenamiento) · Docker Compose |
| **Estado** | Ver [docs/BITACORA.md](docs/BITACORA.md): qué está probado y qué falta |

## Funcionalidades

| Módulo | Qué incluye |
|---|---|
| **Acceso** | Login y logout con sesión segura, contraseñas con hash scrypt, bloqueo tras intentos fallidos, CSRF, cambio obligatorio de contraseña temporal, recuperación por correo (si se configura SMTP) y 4 roles con permisos verificados en el servidor |
| **Panel** | Indicadores reales, alertas de stock, actividad reciente, gráfico de entradas y salidas, estado del modelo de IA y estados vacíos con instrucciones |
| **Catálogo** | Marcas, categorías, proveedores, productos (modelo comercial), variantes por talla y color con SKU, código de barras, costo y precio, fotos, y publicación en la tienda |
| **Inventario** | Entradas, ventas, devoluciones, ajustes justificados y conteos físicos, siempre como movimientos inmutables con usuario. Búsqueda por código de barras, stock bajo/agotado, valor a costo, verificación stock ↔ libro mayor y bloqueo de concurrencia |
| **Conteo inteligente** | **Cámara en vivo** con cajas y conteo en tiempo real, o subida de foto → detección de zapatos individuales con confianza → revisión (rechazar falsos positivos, dibujar omitidos) → desglose en pares y sueltos → confirmación → conciliación opcional con el stock. Sin modelo funciona en modo manual |
| **Lector de etiquetas** | Cámara o foto → código de barras/QR + OCR sin conexión → marca, talla, color, precio y SKU propuestos → buscar la variante o crear el producto prellenado |
| **Importar** | Excel y CSV (tipo detectado automáticamente) del catálogo y del comercio exterior: detección de columnas, vista previa, validación, duplicados, filas rechazadas, confirmación e historial |
| **Reportes / BI** | Entradas y salidas por período, rotación, ajustes, precisión de los conteos con IA, y comercio exterior (importaciones vs. exportaciones, socios, valor por par, síntesis ejecutiva). Exportación CSV, Excel y PDF |
| **Tienda online** | Catálogo público, filtros, carrito, pedidos con reserva de stock en una transacción, estados del pedido y consulta por código. Cobro manual: no hay pasarela configurada |
| **Administración** | Usuarios, auditoría de operaciones y configuración |

## Inicio rápido en Windows (Docker Desktop)

```bash
copy .env.example .env
```

Edita `.env`: una `SECRET_KEY` aleatoria y `POSTGRES_PASSWORD` (solo letras y números). Después:

```bash
docker compose up --build -d
docker compose exec app flask --app run users create-admin --username admin --full-name "Tu nombre"
```

| Dirección | Para qué |
|---|---|
| http://localhost:8088 | Aplicación de gestión (inicia sesión con el usuario creado) |
| http://localhost:8088/tienda.html | Tienda pública |

Sin Docker, con un entorno virtual y SQLite o tu propio PostgreSQL: ver [docs/09-despliegue-operacion.md](docs/09-despliegue-operacion.md) §3.

> No uses `docker compose down -v`: borra la base de datos. Copias de seguridad y restauración: [docs/09](docs/09-despliegue-operacion.md) §4.

## Uso básico

1. **Productos**:
   1. Crea una **marca** (y categorías y proveedores si quieres) en sus pestañas.
   2. Pulsa **Nuevo producto**.
   3. En el producto, añade una **Nueva variante** por cada talla y color, con SKU, costo, precio y stock mínimo. Opcionalmente sube fotos y marca «Publicar en la tienda online».
2. **Existencias** → **Movimiento**:
   - registra la **entrada por compra** (el stock empieza en 0);
   - las ventas, devoluciones, ajustes (con motivo) y conteos físicos se registran igual;
   - el buscador de código acepta un lector de códigos de barras.
3. **Conteo inteligente**:
   1. Sube o fotografía los zapatos.
   2. Revisa las cajas: un clic rechaza una detección y arrastrar añade un zapato omitido.
   3. Indica cuántos **pares completos** y **zapatos sueltos** hay.
   4. **Confirma**. Si quieres, **concilia** con la variante contada: se registra un conteo físico con la diferencia, a tu nombre. El stock nunca cambia solo por subir una foto.
4. **Importar Excel/CSV**: elige el tipo (catálogo o comercio exterior), valida, revisa la vista previa y las incidencias, y confirma. Plantillas y ejemplos FICTICIOS en `datos/ejemplos/`.

## Puertos y variables

| Servicio | Puerto | Notas |
|---|---|---|
| App | 8088, solo `127.0.0.1` | Evita los puertos de XAMPP (80, 443, 3306, 8080) |
| PostgreSQL | No publicado | Solo en la red interna de Docker |

Variables de entorno, todas en [.env.example](.env.example):

| Variable | Uso |
|---|---|
| `SECRET_KEY` | Obligatoria |
| `POSTGRES_*` / `DATABASE_URL` | Base de datos |
| `SESSION_COOKIE_SECURE`, `SESSION_HOURS` | Sesión |
| `LOGIN_*`, `ORDERS_PER_IP_PER_HOUR` | Límites de intentos y de pedidos |
| `AI_MODEL_VERSION`, `AI_CONFIDENCE`, `AI_IOU` | Detector |
| `SMTP_*` | Recuperación de contraseña por correo |
| `TRUST_PROXY` | Proxy HTTPS |

## Pruebas

```bash
cd backend
..\.venv\Scripts\python -m pytest
```

Contra PostgreSQL real, incluidas las pruebas de concurrencia: [docs/08-pruebas.md](docs/08-pruebas.md).

## Documentación

| Documento | Contenido |
|---|---|
| [docs/BITACORA.md](docs/BITACORA.md) | Registro cronológico de cambios, pruebas, pendientes y reversión |
| [docs/00-auditoria-fase0.md](docs/00-auditoria-fase0.md) | Auditoría inicial (estado de Patitas IA) |
| [docs/01-fase1-base.md](docs/01-fase1-base.md) | Base del backend e inventario (histórico) |
| [docs/02-arquitectura-datos-comerciales.md](docs/02-arquitectura-datos-comerciales.md) | Importación, diccionario de datos y política de duplicados |
| [docs/03-autenticacion-seguridad.md](docs/03-autenticacion-seguridad.md) | Login, roles, auditoría, archivos y cabeceras |
| [docs/04-ia-detector.md](docs/04-ia-detector.md) | Dataset, entrenamiento, métricas reales, exportación y conteo |
| [docs/05-camara-ocr.md](docs/05-camara-ocr.md) | Cámara en vivo y lector de etiquetas (OCR, códigos de barras) |
| [docs/06-bi-reportes.md](docs/06-bi-reportes.md) | Fórmulas de indicadores y exportaciones |
| [docs/07-tienda-online.md](docs/07-tienda-online.md) | Catálogo, pedidos, stock transaccional y pagos pendientes |
| [docs/08-pruebas.md](docs/08-pruebas.md) | Pruebas automatizadas y verificaciones manuales |
| [docs/09-despliegue-operacion.md](docs/09-despliegue-operacion.md) | Instalación, copias de seguridad y producción |
| [entrenamiento/README.md](entrenamiento/README.md) · [modelo/README.md](modelo/README.md) | Pipeline de entrenamiento y artefactos del modelo |

## Estructura

```
backend/        API Flask (app/: auth, audit, products, inventory, files, ai, imports, exports, reports, shop),
                migraciones Alembic y pruebas pytest
web/            Frontend: index.html (gestión), login.html, tienda.html, css/, js/ (módulos ES), assets/
entrenamiento/  Pipeline del detector (scripts, configs, informes de datasets)
modelo/         pesos/ (best.pt) y exportados/ (model.onnx + metadata.json) por versión
datos/          ejemplos/ FICTICIOS; entrada/ y procesados/ para datos reales (no versionados)
storage/        Fotos e importaciones (no versionado)
docs/           Documentación y bitácora
```

Historia: el repositorio empezó como «Patitas IA» (clasificador de perros y gatos). Ese contenido se eliminó y puede consultarse en el commit `415ecfd` (tag `respaldo-pre-fase1`).

Licencia del código: Apache 2.0 ([LICENSE](LICENSE)). El detector se entrena con Ultralytics YOLO (AGPL-3.0); ver [docs/04](docs/04-ia-detector.md) §7.
