# Reportes, BI y exportaciones

Todos los indicadores se calculan **en el momento** a partir de la base de datos. No se guardan cifras precalculadas ni se rellenan huecos. Si no hay datos suficientes, la pantalla lo dice.

## 1. Panel principal (`/api/reports/overview`)

| Indicador | Fórmula |
|---|---|
| Productos / variantes | Conteo de filas en `products` / `product_variants` |
| Pares disponibles | Σ `stock_quantity` de todas las variantes |
| Valor del inventario | Σ `costo × pares` **solo** de variantes con costo. Si alguna variante con stock no tiene costo, se marca como «incompleto» |
| Stock bajo | Variantes con `0 < stock ≤ stock mínimo` |
| Agotados | Variantes con `stock = 0` |
| Ventas últimos 30 días | Σ \|cantidad\| de movimientos `salida_venta` + `salida_pedido` |
| Pedidos abiertos | Pedidos en `creado`, `pago_confirmado`, `preparado` o `enviado` |
| Conteos por revisar | Conteos en `revision` o `confirmado` |

## 2. Reportes de inventario (pantalla «Reportes de inventario»)

Filtros: período (desde/hasta), agrupación (día/semana/mes), categoría y marca.

| Reporte | Fórmula |
|---|---|
| Entradas y salidas por período | Entradas = Σ cantidades > 0; salidas = Σ \|cantidades < 0\|, agrupadas por fecha UTC |
| Rotación | `unidades netas / stock medio`. Unidades netas = ventas + pedidos − devoluciones de cliente. Stock medio = (stock al inicio + stock al final) / 2, reconstruido sumando el libro de movimientos hasta cada fecha. Si el stock medio es 0 no se calcula. Sin ventas en el período, se muestra «sin datos suficientes» |
| Ajustes y diferencias de conteo | Movimientos `ajuste` y `conteo_fisico` del período: Σ positivos, Σ negativos y n.º de conteos con diferencia |
| Conteos inteligentes | Error de conteo = \|detectados por el modelo − zapatos confirmados por la persona\|; MAE = media de ese error; «exactos» = % de conteos con error 0; error relativo = Σ errores / Σ zapatos confirmados. Solo usa conteos confirmados que tenían modelo |

No se calculan margen, ganancias ni predicciones: la tienda todavía no tiene ventas reales registradas, y el margen exige además un costo fiable por variante.

## 3. Comercio exterior (pantalla «Comercio exterior (BI)»)

Filtros: rango de años, flujo, categoría, socio, métrica del ranking e «Incluir agregados».

| Visualización / indicador | Fórmula y notas |
|---|---|
| 1. Importaciones vs. exportaciones (valor) | Σ `Valor_USD` por año y flujo |
| 1b. Importaciones vs. exportaciones (pares) | Σ `Cantidad_pares` por año y flujo, **en un gráfico aparte** porque valor y cantidad tienen escalas distintas (sin doble eje) |
| 2. Principales socios | Top 10 por Σ valor o Σ pares (seleccionable) |
| 3. Valor aproximado por par | Σ Valor_USD / Σ Cantidad_pares, solo con filas donde ambos son > 0 y sin agregados. Mezcla códigos SA6 distintos: es un promedio, **no un precio** |
| Variación anual | (valor año / valor año anterior − 1) × 100, por flujo y solo entre años consecutivos con datos |
| Completitud | Filas con valor y cantidad / filas totales |
| Banderas de calidad | `unidades_inconsistentes`, `valor_usd_derivado_de_miles`, `valor_por_par_inconsistente`, `sin_valor`, `sin_cantidad` (ver [02](02-arquitectura-datos-comerciales.md)) |

**Doble conteo:** por defecto se excluyen los registros agregados (socio «Mundo», «World», «Total»…). Incluirlos es una opción explícita del filtro.

### Síntesis ejecutiva (`/api/trade/synthesis`)

Se genera con los cálculos anteriores y los filtros activos:

- **Tres hallazgos**: valor por flujo, socio principal y su participación, y la variación anual más reciente (o, si no la hay, el valor por par).
- **Dos limitaciones**: completitud y banderas de calidad cuando existen; si no, el alcance de los datos (son estadísticas de país) y su cobertura temporal.
- **Una pregunta estratégica y una recomendación**, redactadas de forma condicional.
- Las visualizaciones usadas, los filtros, el número de filas y la fecha de generación.

Aviso explícito en pantalla y en el PDF: los datos externos **no demuestran por sí solos** problemas internos de ninguna empresa (caso Manaco); sirven para formular hipótesis. Los objetivos SMART a 3 años quedan para cuando exista una línea base interna: no se inventan metas.

## 4. Exportaciones

`GET /api/exports/<conjunto>?format=csv|xlsx&<filtros>` con el permiso `exports.run` más el permiso de lectura del conjunto.

| Conjunto | Contenido | Filtros |
|---|---|---|
| `productos` | Productos con n.º de variantes y pares | `category_id` |
| `existencias` | Stock por variante con valor a costo | `q, brand_id, category_id, size, color, state` |
| `movimientos` | Libro de movimientos | `variant_id, product_id, category_id, movement_type, from, to` |
| `conteos` | Conteos inteligentes | `from, to` |
| `pedidos` | Una fila por línea de pedido | `status, from, to` |
| `comercio` | Registros comerciales depurados | `year_from, year_to, flow, category, partner, reporter, hs6, include_aggregates` |
| `comercio_resumen` | Indicadores agregados por año y flujo | los mismos |
| `calidad_importaciones` | Incidencias de validación | `batch_id` |

- El Excel lleva una hoja **Metadatos** con el conjunto, la fecha (UTC), el usuario, el número de filas, los filtros y el origen.
- Si el filtro no devuelve filas se responde 404: **nunca se genera un archivo vacío**.
- Cada exportación queda en `data_exports` y en la auditoría.

### PDF

- `/api/reports/inventario.pdf`: resumen e inventario por variante.
- `/api/reports/comercio.pdf`: síntesis ejecutiva, tablas por año y flujo, socios y valor por par. Se genera con ReportLab y se rechaza si no hay datos.
