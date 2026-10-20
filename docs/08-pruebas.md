# Pruebas

Todas las pruebas usan datos **FICTICIOS** creados por la propia prueba (`MarcaFicticia`, `Cliente Ficticio`, `PaisFicticio`…). Ninguna toca datos reales.

## 1. Cómo ejecutarlas

**Rápidas** (SQLite en memoria):

```bash
cd backend
..\.venv\Scripts\python -m pytest
```

**Contra PostgreSQL real**, dentro del contenedor y con una base de pruebas **separada** (las pruebas borran sus tablas):

```bash
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" shoe_counter_test'
docker compose run --rm -T --no-deps --user root -v "%CD%/backend/tests:/srv/backend/tests:ro" app sh -c "pip install -q pytest==8.4.2 && export TEST_DATABASE_URL=postgresql+psycopg://$POSTGRES_USER:$POSTGRES_PASSWORD@db:5432/shoe_counter_test && python -m pytest -q"
```

Al terminar puede borrarse la base de pruebas con `dropdb`. Las dos pruebas de `test_concurrency_pg.py` se **omiten** en SQLite porque SQLite no aplica `SELECT … FOR UPDATE`.

## 2. Qué cubren (pruebas automatizadas)

| Archivo | Tipo | Cubre |
|---|---|---|
| `test_auth.py` | Integración API | Login y logout, contraseña incorrecta, mensaje idéntico para usuario inexistente, usuario inactivo, cookies `HttpOnly` + `SameSite`, bloqueo tras 5 fallos, rutas privadas → 401, rutas públicas, CSRF obligatorio (también en login), permisos por rol (matriz), operador vende pero no recibe, tipos de movimiento del sistema bloqueados, gestión de usuarios, contraseña temporal obligatoria, invalidación de sesiones al cambiar contraseña o rol, último administrador protegido, recuperación sin SMTP y con token de un uso, hash scrypt, auditoría y su permiso, CLI `create-admin` |
| `test_products.py` | Integración API | Productos, marcas, categorías y proveedores; campos obligatorios; código duplicado; variante única por talla+color; el stock no se edita directamente; precios negativos rechazados; búsqueda |
| `test_inventory.py` | Integración API | Entradas y ventas con historial, stock insuficiente, cantidades positivas, ajuste con motivo, devoluciones, conteo físico (con y sin diferencia), estados bajo/agotado, valor a costo (completo e incompleto), conciliación con el libro mayor, fechas con zona horaria |
| `test_ai.py` | Unidad + integración | Estado sin modelo, conteo manual sin modelo, rechazo de archivos no imagen o con extensión no permitida, re-codificación sin EXIF, flujo completo con un detector **de prueba inyectado** (revisar → confirmar → aplicar), la foto no cambia el stock, permisos operador/encargado/consulta, descarte con motivo, cajas inválidas, imagen anotada, listado y reporte de precisión, imagen privada con sesión, decodificación ONNX y NMS, descubrimiento de versiones de modelo, modelo dañado → modo manual sin inventar, CLI `export-dataset` |
| `test_imports_exports.py` | Integración API | Vista previa sin escribir datos, confirmación, exclusión de agregados, reimportación bloqueada, actualizaciones detectadas, errores de flujo, año, SA6 y negativos, advertencia de unidades, política de duplicados exactos y en conflicto, columnas faltantes, `.xlsx` y CSV con `;`, archivos disfrazados y con macros, cálculos de valor por par, variación y socios, síntesis (3 hallazgos y 2 limitaciones), importación del catálogo con entradas de stock, exportación CSV/XLSX con filtros y metadatos, 404 sin datos, inyección de fórmulas neutralizada, registro de exportaciones, permisos, PDF |
| `test_shop_reports.py` | Integración API | Catálogo solo publicado sin exponer costos ni stock, reserva de stock, total calculado en el servidor, consulta pública del pedido, ciclo de estados completo, cancelación y devolución que reponen stock, última unidad no vendible dos veces, *rollback* si una línea falla, validaciones, límite de pedidos por IP, fotos públicas solo si el producto está publicado, panel vacío y con datos, series, rotación, ajustes y permisos de reportes |
| `test_concurrency_pg.py` | Integración PostgreSQL | 6 pedidos **simultáneos** (hilos) por 1 unidad: exactamente 1 aceptado y 5 rechazados; 8 movimientos simultáneos de venta y entrada con el libro mayor consistente |
| `test_migrations.py` | Integración | `upgrade` desde cero y `downgrade` a base sobre una base de datos real en archivo |
| `test_app.py` | Integración | Salud, cabeceras de seguridad, configuración obligatoria, clave de ejemplo rechazada, 404 JSON, intento de salir de la carpeta web con `../` |

## 3. Resultados

Los resultados reales de cada ejecución, y los defectos que encontraron, están registrados en la [bitácora](BITACORA.md).

## 4. Verificaciones manuales (navegador)

Hechas a través de la interfaz real (formularios y botones), en el panel del navegador de la sesión de trabajo:

- Login, redirección a login sin sesión y navegación por las 12 secciones sin errores.
- Marca → categoría → producto → variante → entrada (6) → venta (2) → venta (50) rechazada → verificación con el libro mayor → descarga de Excel y PDF.
- Tienda: catálogo, talla y color, carrito, pedido creado y consultado.
- Importación del CSV de comercio ficticio (7 válidas y 1 rechazada) → confirmación → BI con 4 gráficos y síntesis.
- Conteo manual (sin modelo): subir foto → 2 cajas dibujadas → 1 par → confirmación → conciliación con la variante, que registró un movimiento −2 a nombre del usuario.

**Limitación de la verificación visual:** el panel del navegador era muy pequeño durante la sesión, así que el diseño se revisó sobre todo de forma funcional (texto, DOM y consola) y con pocas capturas. Conviene revisarlo visualmente en una pantalla completa.
