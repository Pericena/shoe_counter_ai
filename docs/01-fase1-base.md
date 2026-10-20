# Fase 1 (parte 1) — Base funcional e inventario mínimo

> **Documento histórico.** Describe el estado del 2026-10-20 por la mañana. Después se añadieron autenticación (todas las rutas exigen sesión y CSRF), marcas y categorías como tablas, el usuario responsable en cada movimiento, fotos, conteo inteligente, importaciones, BI y tienda. La referencia actual está en el [README](../README.md) y en los documentos 02–09. El modelo de datos y las reglas de stock descritas aquí siguen vigentes.

| | |
|---|---|
| Fecha | 2026-10-20 |
| Estado | Implementado y probado con SQLite. **Docker y PostgreSQL sin probar:** Docker Desktop estaba apagado. |
| Punto de retorno | Tag `respaldo-pre-fase1` (commit `415ecfd`) |

## 1. Qué se construyó

```
shoe_counter_ai/
├── backend/
│   ├── app/
│   │   ├── __init__.py        create_app(): config, BD, blueprints, /api/health, web estática, errores JSON, cabeceras de seguridad
│   │   ├── config.py          Configuración por entorno (development/testing/production) desde variables de entorno
│   │   ├── extensions.py      SQLAlchemy + Flask-Migrate con nombres de restricciones estables
│   │   ├── common.py          ApiError, validación de entrada, fechas UTC
│   │   ├── products/          Proveedores, productos (modelo comercial) y variantes (talla + color)
│   │   └── inventory/         Movimientos (libro mayor), servicio de stock, consulta de existencias, conciliación
│   ├── migrations/            Alembic; revisión inicial fd19e9dd1c4c
│   ├── tests/                 28 pruebas pytest (datos FICTICIOS)
│   ├── requirements.txt / requirements-dev.txt
│   ├── docker-entrypoint.sh   Aplica migraciones y arranca gunicorn
│   └── run.py                 Entrada WSGI; en Windows arranca waitress en 127.0.0.1:8088
├── web/                       Panel de inventario (HTML + CSS + JS sin frameworks ni CDN)
├── Dockerfile, compose.yaml, .env.example, .gitignore, .gitattributes, .dockerignore
└── storage/                   (creada al arrancar, ignorada por Git) fotos/, procesadas/, importaciones/, exportaciones/
```

## 2. Modelo de datos

| Tabla | Propósito | Restricciones clave |
|---|---|---|
| `suppliers` | Proveedores | `name` único |
| `products` | Modelo comercial (marca + modelo) | `code` único; `status` ∈ {activo, inactivo, descontinuado}; FK proveedor `SET NULL` |
| `product_variants` | Talla + color de un producto. **Unidad de stock: par.** | `sku` único; `barcode` único (opcional); `(product_id, size, color)` único; `stock_quantity ≥ 0`; costo/precio ≥ 0 |
| `inventory_movements` | Libro mayor; nunca se edita ni borra | `quantity ≠ 0` (con signo); `balance_after ≥ 0`; tipo ∈ lista cerrada; FK `RESTRICT` |

**Fuente única de verdad del stock:**

- `stock_quantity` **no se puede escribir por la API**: crear o editar una variante con ese campo devuelve 422.
- Solo `inventory/services.register_movement()` lo cambia. Bloquea la fila con `SELECT … FOR UPDATE` y escribe el movimiento y el nuevo saldo en la **misma transacción**. Así dos ventas simultáneas no pueden consumir la misma última unidad en PostgreSQL.
- `GET /api/inventory/reconciliation` recalcula el saldo sumando los movimientos y lo compara con el guardado.

**Tipos de movimiento:**

| Tipo | Cantidad enviada | Efecto |
|---|---|---|
| `entrada_compra` | `quantity` > 0 | + |
| `salida_venta` | `quantity` > 0 | − (rechaza con 409 si no hay stock) |
| `devolucion_cliente` | `quantity` > 0 | + |
| `devolucion_proveedor` | `quantity` > 0 | − |
| `ajuste` | `quantity` ≠ 0, con signo; `reason` obligatorio | ± |
| `conteo_fisico` | `counted_quantity` ≥ 0 | Registra la diferencia contra el sistema; si coincide, no crea movimiento |

## 3. API disponible

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado de la API y de la BD (503 si la BD falla) |
| GET/POST | `/api/suppliers` | Listar / crear proveedor |
| GET/POST | `/api/products` | Listar (filtros `q`, `category`, `status`, paginación) / crear producto |
| GET/PATCH | `/api/products/<id>` | Detalle con variantes / editar |
| POST | `/api/products/<id>/variants` | Crear variante (stock inicial 0) |
| GET/PATCH | `/api/variants/<id>` | Detalle / editar (sin stock) |
| GET | `/api/inventory/stock` | Existencias por modelo/talla/color. Filtros `q`, `brand`, `size`, `color`, `state=bajo/agotado`, `product_id`. Resumen: pares, valor a costo y si el valor está completo |
| POST | `/api/inventory/movements` | Registrar movimiento |
| GET | `/api/inventory/movements` | Historial (`variant_id`, `movement_type`, paginación) |
| GET | `/api/inventory/reconciliation` | Auditoría saldo vs. movimientos |

El valor de inventario se calcula como `costo × pares`. Si una variante con stock no tiene costo, el resumen marca `inventory_value_complete: false` en lugar de inventar un valor.

## 4. Cómo ejecutar

### A. Sin Docker (probado)

```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
copy .env.example .env
```

Edita `.env` (`SECRET_KEY`). Por defecto usa SQLite en `storage/dev.sqlite3`. Después:

```bash
cd backend
..\.venv\Scripts\flask --app run db upgrade
..\.venv\Scripts\python run.py
```

Abre http://localhost:8088.

### B. Con Docker Desktop (pendiente de probar)

1. Inicia Docker Desktop.
2. En `.env`, define `SECRET_KEY` y `POSTGRES_PASSWORD`. Usa solo letras y números en la contraseña: forma parte de la URL de conexión.
3. Desde la raíz del proyecto:

```bash
docker compose up --build -d
docker compose ps
docker compose logs app
```

- El contenedor `app` aplica las migraciones al arrancar.
- La app queda en http://localhost:8088, publicada solo en `127.0.0.1`.
- PostgreSQL **no publica puerto**.
- Para detener: `docker compose down`. **Nunca `down -v`**: borra el volumen `pgdata` con la base de datos.

### Pruebas

```bash
cd backend
..\.venv\Scripts\python -m pytest
```

Para correr las mismas pruebas contra PostgreSQL, define `TEST_DATABASE_URL` con una base **vacía y dedicada a pruebas**: las pruebas borran sus tablas.

## 5. Reutilización del frontend de Patitas IA

| Componente original | Decisión |
|---|---|
| Paleta (crema `#f7f5ef`, verde `#46765a`, tinta `#26352b`), anillo de foco, `prefers-reduced-motion` | **Reutilizado** en `web/css/app.css` |
| Logo del robot y favicons | **Reutilizados** en `web/assets/` |
| Carga de imagen con validación MIME/tamaño, cámara frontal/trasera, preprocesado en canvas | **A reutilizar en la Fase 6** (subida de fotos para el detector). Código recuperable desde el tag `respaldo-pre-fase1` (`index.html`, funciones `showSelectedPhoto`, `startCamera`, `prepareInput`) |
| Service worker y manifest PWA | A rehacer en la Fase 8; la caché del service worker no debe servir datos de inventario antiguos |
| Tailwind por CDN, TF.js, COCO-SSD, clasificador perro/gato, "retos" de mascotas | **Eliminados**: no aplican y el CDN sin SRI era un riesgo |

## 6. Seguridad aplicada en esta parte

- Secretos solo por variables de entorno. La app **no arranca** si faltan `SECRET_KEY` o `DATABASE_URL` (probado).
- ORM con consultas parametrizadas; validación de tipos, longitudes y rangos en el servidor.
- Cabeceras CSP (`default-src 'self'`), `X-Frame-Options: DENY`, `nosniff` y `Referrer-Policy`.
- Archivos estáticos con `send_from_directory`: el intento de salir de la carpeta web con `../` devuelve 404 (probado).
- Contenedor con usuario no root; app publicada solo en `127.0.0.1`; PostgreSQL sin puerto expuesto.
- Límite de subida configurable (`MAX_UPLOAD_MB`, 15 MB por defecto).
- **Sin autenticación todavía.** Cualquiera con acceso a `localhost:8088` puede escribir. Por eso el puerto solo se publica en local. La autenticación y los roles van en la Fase 2, antes de exponer la app en red.

## 7. Pendientes

- Probar Docker y PostgreSQL con Docker Desktop encendido, incluida la concurrencia real de `FOR UPDATE`.
- Fase 2: usuarios, roles, CSRF, auditoría de acciones, fotos de producto, tabla de conteos físicos con sesión de conteo, alertas.
- Fase 3: datos comerciales (ver [02-arquitectura-datos-comerciales.md](02-arquitectura-datos-comerciales.md)).
