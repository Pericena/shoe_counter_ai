# Cámara en vivo y lector de etiquetas (OCR)

## 1. Conteo con cámara en vivo (Conteo inteligente → «Cámara en vivo»)

1. **Iniciar cámara**: el navegador pide permiso. Usa por defecto la cámara trasera del móvil; «Cambiar cámara» alterna entre trasera y frontal.
2. **Vista previa en vivo**:
   - Unas 2–3 veces por segundo se envía un fotograma reducido (960 px) a `POST /api/ai/detect`.
   - El detector devuelve las cajas, que se dibujan sobre el vídeo con su confianza, y el **número de zapatos** aparece en grande.
   - **Estos fotogramas no se guardan ni crean conteos.**
3. **Registrar foto y contar**: captura la imagen a resolución completa (hasta 1.920 px) y la envía a `POST /api/ai/counts`. Ahí queda **guardada** y abre la revisión (aceptar o rechazar cajas, añadir las omitidas, pares y sueltos, confirmar y, si se quiere, conciliar con el stock). El stock nunca cambia sin esa confirmación.

| Rendimiento medido | Valor |
|---|---|
| Detección por fotograma, servidor local en CPU | ~140–200 ms |
| Detección dentro de Docker | ~300 ms |

**Requisitos de la cámara**: el navegador solo la permite en **contexto seguro**, es decir, `http://localhost` / `http://127.0.0.1` o **HTTPS**. Para usarla desde un móvil en la tienda hay que publicar la app con HTTPS (ver [09](09-despliegue-operacion.md) §5). Sin modelo instalado, la vista en vivo no detecta, pero se puede registrar la foto y contar a mano.

## 2. Lector de etiquetas (menú «Lector de etiquetas»)

Lee una foto (tomada con la cámara o subida) de una **etiqueta, caja, lengüeta o código de barras** con `POST /api/ocr/analyze`:

| Paso | Tecnología | Resultado |
|---|---|---|
| Códigos de barras y QR | `zxing-cpp` 3.1.1 (Apache-2.0) | EAN-13/8, UPC, Code 128, QR… |
| Texto (OCR) | `rapidocr-onnxruntime` 1.4.4 (Apache-2.0), modelos PP-OCRv4 **incluidos en el paquete** (16 MB), ejecutados con ONNX Runtime | Líneas de texto con confianza ≥ 0,5. **Funciona sin Internet** |
| Campos propuestos | Reglas en `backend/app/ocr/services.py` | **Marca**: solo si aparece escrita y coincide con una marca registrada. **Talla**: tras «talla/EUR/US/UK/size»; corrige confusiones O→0 solo si no es ambiguo. **Color**: lista en español e inglés. **Precio**: tras «precio/PVP/Bs/$». **SKU / código**: coincidencias con SKU, códigos de barras o códigos de producto registrados |
| Búsqueda | Base de datos | Variante exacta por código/SKU; si no la hay, variantes de la misma marca y talla |

Después, la persona decide:

- **Variante encontrada** → «Registrar movimiento» (entrada, venta, ajuste…) con el formulario normal.
- **No encontrada** → «Crear producto con estos datos»: abre el formulario de producto **prellenado** y, tras guardarlo, propone la variante con la talla, el color, el precio y el código de barras leídos. O bien «Añadir variante» a un producto existente de la misma marca.

**Trazabilidad**: cada imagen leída se guarda como archivo privado (`storage/etiquetas/`, propósito `etiqueta`, migración `e865ca134acc`), y la lectura queda en la auditoría (`etiqueta_leida`) con los códigos, marcas, tallas y coincidencias.

### Limitaciones (honestas)

- **No reconoce logotipos ni modelos de zapato a partir de la imagen del calzado.** La marca solo se obtiene del texto impreso. Reconocer marcas por logotipo requeriría entrenar un modelo con fotos etiquetadas por marca, que no existen en este proyecto.
- El OCR une palabras sin espacios con frecuencia (p. ej. «TALLA4ONEGRO»). En esos casos ambiguos **no propone talla**: mejor vacío que una talla equivocada.
- La primera lectura tarda unos 4 s (carga del modelo); las siguientes, ~1–2 s en CPU.

## 3. Producto reconocido → ficha completa y comparación con el inventario

Cuando la foto, la cámara o el lector reconocen un producto **ya registrado**, se muestra su **ficha** (`GET /api/products/<id>/overview`, componente `web/js/productcard.js`):

- **Identidad**: foto, marca, modelo, código, categoría, tipo de calzado, proveedor, estado, publicación y descripción.
- **Totales**: pares en stock, variantes bajas o agotadas, vendidos en 30 días, reservados por pedidos abiertos, valor a costo y a precio de venta, rango de precios.
- **Matriz talla × color** con el stock de cada combinación (verde, ámbar o rojo); la **variante reconocida va recuadrada**.
- En el detalle del producto, además, los últimos movimientos y los conteos conciliados.

**Cómo se identifica el producto en un conteo**:

| Origen | Método | Cómo |
|---|---|---|
| Foto subida o «Registrar foto» | `codigo` / `etiqueta` | Al crear el conteo, el servidor lee en la **misma foto** el código de barras/QR y el texto. Si coincide exactamente con **una** variante registrada, queda identificada (`ai_counts.identified_variant_id`) |
| Cámara en vivo → «Identificar producto» | `seleccion_en_vivo` | Lee el código o la etiqueta del fotograma, muestra la ficha y una franja sobre el vídeo («marca modelo · SKU · talla · color — sistema: N pares · en la foto: X zapatos»). Al registrar, la foto queda asociada a esa variante |
| Revisión del conteo | `manual` | «Identificar / Cambiar el producto»: buscar y asignar la variante (`PUT /api/ai/counts/<id>/identify`) |

En la revisión aparece **«Foto frente a inventario»**: stock en sistema, zapatos en la foto (o pares y sueltos confirmados) y la diferencia orientativa. La conciliación con el stock **preselecciona** la variante identificada; sigue siendo necesario indicar los pares contados y el alcance, y confirmarlo. Identificar un producto nunca modifica el stock.

**Límite**: sin código de barras ni etiqueta visible no se puede saber qué modelo es solo por la forma del zapato. En ese caso se identifica a mano.

## 4. Pruebas

`backend/tests/test_ocr_live.py` y `test_identification.py` (ficha consolidada, ventas y último movimiento en Existencias, lector con ficha, conteo identificado por código en la foto, selección en vivo, corrección manual, conciliación con la variante identificada):

- Detección en vivo sin modelo y con el detector de prueba, comprobando que **no guarda nada**.
- Validación del fotograma y permisos.
- Lector con un **código EAN-13 real generado** y texto renderizado: lee el código, encuentra la variante y extrae marca, talla, color y precio, sin modificar el stock.
- Rechazo de archivos que no son imagen.

Verificado también contra el servidor real (HTTP) y dentro del contenedor Docker con PostgreSQL. La cámara física del dispositivo **no** se probó automáticamente: requiere conceder el permiso en el navegador.
