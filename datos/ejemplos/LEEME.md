# Archivos de ejemplo

| Archivo | Origen | Uso |
|---|---|---|
| `comercio_FICTICIO.csv` | Ficticio | Prueba de importación de comercio exterior: 7 filas válidas (una es el agregado «Mundo») y 1 con un flujo inválido |
| `catalogo_FICTICIO.csv` | Ficticio | Prueba de importación del catálogo: 2 productos, 3 variantes y entradas de stock |
| `MANACO-INTERMEDIO.xlsx` | **Archivo real del usuario** (no modificado) | Datos de comercio de calzado de España, 2020–2024, 240 filas. Válido. 10 claves aparecen dos veces con valores distintos: elige la política de duplicados al importar |
| `MANACO-INTERMEDIO.csv` | **Archivo real del usuario** (no modificado) | **Dañado**: a los campos con tildes o ñ les falta la última letra (`Españ`, `Importació`, `Países Bajo`). Además no tiene BOM, por eso Excel muestra «��». No usar |
| `MANACO-INTERMEDIO_corregido.csv` | Generado el 2026-10-20 a partir del `.xlsx` | Mismo contenido que el `.xlsx`, en CSV UTF-8 con BOM, separador `;` y coma decimal (se abre bien en Excel en español). Antes de generarlo se verificó que el `.csv` original es exactamente el `.xlsx` con ese truncado y con los mismos números |

Los datos reales nuevos van en `datos/entrada/`, que Git ignora.
