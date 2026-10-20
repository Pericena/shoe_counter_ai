# Tienda online

Página pública: `http://localhost:8088/tienda.html` (no requiere sesión).

## 1. Qué hace

- **Catálogo**:
  - Muestra solo productos con «Publicar en la tienda online» activado y estado activo, y de ellos solo las variantes activas **con precio**.
  - Fotos, marca, modelo, categoría y descripción.
  - Disponibilidad por talla y color. No se expone la cantidad exacta, solo «últimas unidades» cuando quedan 3 o menos.
  - Filtros por texto, talla, color, categoría y «solo disponibles».
- **Carrito**: se guarda en el navegador (`localStorage`). Precios y stock se validan siempre en el servidor, nunca con lo que envíe el navegador.
- **Pedido**: nombre, correo, teléfono, dirección y notas. **No se piden datos de tarjeta ni se cobra en línea.**
- **Consulta del estado**: con el código del pedido (`PED-XXXXXXXX`) y el correo usado.

## 2. Stock y concurrencia

Al crear el pedido, en **una sola transacción**:

1. Las variantes se bloquean (`SELECT … FOR UPDATE`) en orden de id, para evitar interbloqueos entre pedidos simultáneos.
2. Se comprueba el stock y se registra un movimiento `salida_pedido` por línea (reserva).
3. Si cualquier línea falla, se revierte todo: no quedan pedidos ni reservas a medias.

Esto está probado en PostgreSQL con 6 compradores simultáneos y una sola unidad: un pedido se acepta y los otros 5 reciben 409.

## 3. Estados

```
creado ──► pago_confirmado ──► preparado ──► enviado ──► entregado ──► devuelto
   │              │                 │
   └──────────────┴─────────────────┴──► cancelado
```

| Transición | Efecto |
|---|---|
| → pago_confirmado | Exige registrar la **referencia del pago** recibido (transferencia, recibo…) |
| → cancelado | Exige motivo. Repone el stock con `cancelacion_pedido` |
| entregado → devuelto | Exige motivo. Repone el stock con `devolucion_cliente` |

Cada cambio queda en `order_status_history` (usuario, fecha y nota) y en la auditoría. Gestión interna en **Pedidos online** (`orders.view` / `orders.manage`).

## 4. Protección

- Límite de 10 pedidos por IP y hora (`ORDERS_PER_IP_PER_HOUR`) y de 30 consultas de estado cada 15 minutos.
- CSRF obligatorio también en la tienda pública.
- Máximo 20 líneas por pedido y 10 pares por línea.
- La respuesta pública del pedido no incluye datos personales.

## 5. Pagos: qué falta configurar

No hay pasarela de pago integrada a propósito. Para cobrar en línea hace falta:

1. **Elegir un proveedor** compatible con el país y las condiciones del negocio. Para Bolivia hay que evaluar opciones locales con QR o transferencia, o pasarelas internacionales que operen allí.
2. **Obtener las credenciales** del proveedor y guardarlas como variables de entorno.
3. **Implementar** la creación del cobro y el *webhook* de confirmación, que haría la transición `creado → pago_confirmado` con la referencia del proveedor.
4. **Nunca guardar** números de tarjeta en esta base de datos.

Hasta entonces el pago se coordina con la tienda, y el personal lo confirma manualmente registrando su referencia.
