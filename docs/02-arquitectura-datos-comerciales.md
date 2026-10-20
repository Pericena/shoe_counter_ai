# Importación de datos (comercio exterior y catálogo)

> **Estado:** implementado y probado con archivos FICTICIOS (`datos/ejemplos/`). El Excel comercial original **todavía no se ha recibido**: al importarlo, revisa el informe de validación antes de confirmar. Si sus columnas, flujos o unidades difieren de lo previsto, ajusta `backend/app/imports/parsers.py`.

## 1. Flujo en dos pasos

1. **Subir y validar** (`POST /api/imports`, pantalla «Importar Excel/CSV»):
   - Guarda el archivo en `storage/importaciones/` y su hash SHA-256.
   - Detecta y asigna las columnas por nombre normalizado (sin tildes, mayúsculas ni espacios).
   - Valida tipos, valores faltantes, duplicados, años y unidades.
   - Muestra una vista previa de 20 filas normalizadas y el informe de incidencias por fila y columna.
   - **No escribe datos.**
2. **Confirmar** (`POST /api/imports/<id>/confirm`): vuelve a leer el archivo y comprueba que no cambió. Aplica en **una transacción** y registra cuántas filas se añadieron, actualizaron, quedaron sin cambios o se rechazaron.
3. **Descartar** (`POST /api/imports/<id>/discard`) cuando el informe muestre problemas.

Formatos aceptados:

| Formato | Detalles |
|---|---|
| `.xlsx` | Primera hoja o la indicada; sin macros |
| `.csv` | UTF-8, Windows-1252 o Latin-1; separador `,`, `;` o tabulador, detectado automáticamente |

Números: `1.234,56`, `1,234.56`, `1234.5` y `12,5` se interpretan según la regla documentada en `parse_number`.

## 2. Comercio exterior — diccionario de datos

| Columna origen | Campo BD | Tipo | Unidad | Validación / tratamiento |
|---|---|---|---|---|
| `País_reportante` | `reporter` | texto ≤ 100 | — | Obligatorio |
| `Flujo_comercial` | `flow` | texto controlado | — | Normaliza Importación/Exportación/Reexportación/Reimportación (y equivalentes en inglés, M/X). Otro valor → **error** |
| `Año` | `year` | entero | año | 1900 – año actual. Si no → error |
| `Código_SA6` | `hs6_code` | texto 6 dígitos | — | Se guarda como texto (conserva ceros). Corrige `640399.0` de Excel. Fuera del capítulo 64 → **advertencia** |
| `Categoría_calzado` | `category` | texto ≤ 200 | — | Opcional |
| `Socio_comercial` | `partner` | texto ≤ 150 | — | Obligatorio. «Mundo», «World», «Total»… → `is_aggregate = true` |
| `Valor_miles_USD` | `value_thousand_usd` | decimal | miles de USD | ≥ 0 |
| `Cantidad_pares` | `quantity_pairs` | decimal | pares | ≥ 0; vacío o 0 → bandera `sin_cantidad` |
| `Valor_USD` | `value_usd` | decimal | USD | ≥ 0. Si falta pero hay miles → se deriva `miles × 1000` con la bandera `valor_usd_derivado_de_miles` |
| `Valor_USD_por_par` | `value_usd_per_pair_source` | decimal | USD/par | Se conserva tal cual y además se **recalcula** en `value_usd_per_pair` = valor / cantidad (solo si ambos > 0) |

### Coherencia de unidades

- `Valor_USD` frente a `Valor_miles_USD × 1000`: si difieren más de un 1 %, se emite una **advertencia** con la bandera `unidades_inconsistentes` y se conserva `Valor_USD` tal como viene. **No se multiplica por 1000 si `Valor_USD` ya existe.**
- `Valor_USD_por_par` del archivo frente al recalculado: si difieren más de un 1 %, advertencia y bandera `valor_por_par_inconsistente`.
- Valores negativos → **error** (fila rechazada).

### Clave e identificación de duplicados

- **Clave natural**: `(reporter, flow, year, hs6_code, partner)`, con restricción `UNIQUE` en `trade_records`.
- **Dentro del archivo**:
  - Filas con la misma clave y los **mismos** valores → se importa una y las demás se omiten con advertencia.
  - Filas con la misma clave y valores **distintos** → todas se **rechazan** para revisión manual. No se elige una al azar.
- **Frente a la base de datos**:
  - Misma clave y mismos valores → «sin cambios».
  - Valores distintos → «actualizada», y se registra el lote que la actualizó (`source_batch_id`).
- **Mismo archivo** (mismo SHA-256) ya confirmado → la validación lo bloquea.

### Separación del inventario

`trade_records` no tiene claves foráneas hacia productos ni stock. Ningún indicador de la tienda usa estos datos y la interfaz los presenta como **datos externos**.

## 3. Catálogo de la tienda

Columnas (con sus alias):

- **Obligatorias**: `codigo_producto`, `marca`, `modelo`, `sku`, `talla`, `color`.
- **Opcionales**: `categoria`, `tipo_calzado`, `descripcion`, `codigo_barras`, `costo`, `precio`, `stock_minimo`, `cantidad_entrada`.

Reglas:

- **Clave**: `sku`. Un SKU repetido en el archivo → error en todas sus filas.
- **Coherencia del producto**: un mismo `codigo_producto` con marca, modelo o categoría distintos → error.
- **Unicidad de variante**: talla + color repetidos para el mismo producto → error.
- **Producto nuevo**: se crea, y también la marca y la categoría si no existen (búsqueda sin distinguir mayúsculas). **Producto existente**: se reutiliza; sus datos generales no se sobrescriben desde el archivo.
- **Variante nueva** → añadida. **Variante existente** con cambios de código de barras, costo, precio o mínimo → actualizada.
- **SKU de otro producto**, o talla y color ya ocupados por otro SKU → se aborta toda la importación (409) sin escribir nada.
- **`cantidad_entrada > 0`** → movimiento `entrada_compra` con referencia `IMPORT-<lote>`. El stock nunca se fija directamente.

## 4. Tablas

| Tabla | Contenido |
|---|---|
| `import_batches` | Tipo, archivo, usuario, estado, hoja, totales, mapeo de columnas, vista previa y resumen |
| `import_issues` | Fila, columna, severidad (error/advertencia) y mensaje |
| `trade_records` | Datos comerciales depurados, banderas de calidad y lote de origen |
| `data_exports` | Registro de cada exportación |

Plantillas descargables: `GET /api/imports/templates/catalogo.csv` y `comercio.csv`.
