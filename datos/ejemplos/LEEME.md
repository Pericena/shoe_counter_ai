# Archivos de ejemplo FICTICIOS

Estos archivos **no contienen datos reales**. Sirven solo para probar la importación:

| Archivo | Tipo de importación | Qué prueba |
|---|---|---|
| `comercio_FICTICIO.csv` | Comercio exterior | 7 filas válidas (una de ellas es un agregado «Mundo») y 1 fila con un flujo inválido («Trueque») que debe rechazarse |
| `catalogo_FICTICIO.csv` | Catálogo de la tienda | 2 productos, 3 variantes y entradas de stock |

No los importes en la base de datos de producción. Los datos reales van en `datos/entrada/`, que Git ignora.
