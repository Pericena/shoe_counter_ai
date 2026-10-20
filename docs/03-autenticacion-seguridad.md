# Autenticación, roles y seguridad

## 1. Sesión e inicio de sesión

| Elemento | Implementación |
|---|---|
| Contraseñas | Hash **scrypt** con sal aleatoria (Werkzeug 3). Nunca se guardan ni registran en claro. |
| Política | Mínimo 10 caracteres, letras y números, no repetitiva y sin contener el nombre de usuario. |
| Sesión | Cookie firmada `shoe_session`, `HttpOnly`, `SameSite=Lax`; `Secure` con `SESSION_COOKIE_SECURE=true` (obligatorio con HTTPS). Caduca a las 8 h (`SESSION_HOURS`). |
| Invalidación | Cada usuario tiene `session_version`. Cambiar la contraseña, el rol o desactivar al usuario la incrementa, y las sesiones abiertas dejan de valer de inmediato. |
| Fijación de sesión | Al iniciar sesión se borra la sesión anterior y se genera un token CSRF nuevo. |
| Intentos repetidos | 5 fallos por usuario o 20 por IP en 15 minutos bloquean 15 minutos (configurable). El mensaje es idéntico exista o no el usuario, y se gasta el mismo tiempo de cálculo. |
| CSRF | Toda petición `POST/PUT/PATCH/DELETE` a `/api/*` exige la cabecera `X-CSRF-Token` igual al token de la sesión, también el login y los pedidos públicos. |
| Contraseña temporal | Los usuarios creados por un administrador deben cambiarla al entrar: hasta entonces solo pueden usar `/api/auth/*`. |

### Recuperación de contraseña

- **Con SMTP configurado** (`SMTP_HOST`, `SMTP_FROM`, …): se envía un enlace de un solo uso que caduca en 30 minutos. En la base de datos solo se guarda el hash SHA-256 del token. La respuesta es la misma exista o no el correo.
- **Sin SMTP** (estado actual): la pantalla lo indica y la recuperación la hace un administrador, desde **Usuarios → Editar → contraseña temporal** o por consola:

  ```bash
  flask --app run users reset-password --username <usuario>
  ```

## 2. Primer administrador

No existen credenciales por defecto. El primer administrador se crea por consola, y la contraseña se pide dos veces sin mostrarla:

```bash
cd backend
..\.venv\Scripts\flask --app run users create-admin --username admin --full-name "Nombre Apellido"
```

Con Docker:

```bash
docker compose exec app flask --app run users create-admin --username admin
```

Para automatizaciones existe la variable `ADMIN_PASSWORD`. Evítala en uso interactivo, porque queda en el historial de la consola.

## 3. Roles y permisos (verificados en el servidor)

Las tablas son `roles`, `permissions` y `role_permissions`. La migración `178fd8c60df3` siembra:

| Permiso | Consulta | Operador | Encargado de inventario | Administrador |
|---|:-:|:-:|:-:|:-:|
| dashboard.view, products.view, inventory.view, reports.view, orders.view | ✓ | ✓ | ✓ | ✓ |
| inventory.sell (ventas y devoluciones de clientes) | | ✓ | ✓ | ✓ |
| counts.create (subir fotos, revisar conteos) | | ✓ | ✓ | ✓ |
| orders.manage (estados de pedidos) | | ✓ | ✓ | ✓ |
| products.manage, inventory.move (entradas, ajustes, conteos físicos) | | | ✓ | ✓ |
| counts.confirm (confirmar y conciliar conteos) | | | ✓ | ✓ |
| imports.manage, exports.run | | | ✓ | ✓ |
| users.manage, audit.view, settings.view | | | | ✓ |

- **Por defecto se deniega**: toda ruta bajo `/api/` exige sesión salvo una lista blanca explícita (`/api/health`, `/api/auth/session|login|logout|password-reset/*`, `/api/shop/*`, `/api/public/*`).
- Cada endpoint declara además los permisos que necesita con `@require(...)`.
- El tipo de movimiento también se comprueba: un operador puede registrar ventas, pero una entrada devuelve 403 aunque llame a la API directamente.
- Debe quedar siempre al menos un administrador activo.

## 4. Auditoría

La tabla `audit_logs` es inmutable desde la aplicación y se consulta en **Auditoría** (solo administradores). Registra:

- inicio y cierre de sesión e intentos fallidos;
- cambios de contraseña y recuperaciones;
- creación y modificación de usuarios, marcas, categorías, proveedores, productos y variantes, con el valor anterior y el nuevo;
- fotos de producto;
- cada movimiento de inventario;
- conteos inteligentes (creado, revisado, confirmado, aplicado, descartado);
- importaciones (validada, confirmada, descartada) y exportaciones con sus filtros;
- informes PDF;
- pedidos y cambios de estado.

Se guardan el usuario, la IP, la entidad y el detalle en formato JSON.

## 5. Archivos y rutas

- **Subida de imágenes**: se aceptan extensiones `.jpg/.jpeg/.png/.webp`, se verifica el contenido real con Pillow (límite de 50 Mpx contra «bombas» de descompresión) y la imagen **se vuelve a codificar a JPEG**. Así desaparecen los metadatos EXIF/GPS y cualquier contenido incrustado.
- **Subida de datos**: `.csv` (rechazado si contiene bytes NUL) o `.xlsx` (debe ser un paquete OOXML válido; se rechazan `.xls`, `.xlsm` y libros con macros).
- **Nombres en disco**: UUID aleatorios dentro de `STORAGE_DIR/<tipo>/<año>/<mes>/`. El nombre original solo se guarda como dato.
- **Acceso a archivos**:
  - Las fotos de conteo y los archivos de importación solo se sirven con sesión iniciada y permiso, por `/api/files/<id>`.
  - Las fotos de producto son públicas solo si el producto está **publicado y activo**.
  - Toda ruta se resuelve y se comprueba que quede dentro de `STORAGE_DIR`.
- **Archivos web**: `send_from_directory` rechaza rutas con `../` (probado).
- **Tamaño máximo** por petición: `MAX_UPLOAD_MB` (15 MB); si se supera se responde 413.

## 6. Cabeceras y navegador

- `Content-Security-Policy`: `default-src 'self'`, sin scripts ni estilos en línea ni CDN de terceros (todo el frontend se sirve localmente), `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'none'`.
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` y `Referrer-Policy: same-origin`.
- `Permissions-Policy`: cámara solo en el propio sitio, para las fotos de conteo.
- `Strict-Transport-Security` cuando `SESSION_COOKIE_SECURE=true`.
- Las respuestas de la API llevan `Cache-Control: no-store`. Los archivos web se revalidan siempre con ETag para no usar módulos antiguos tras una actualización.
- El frontend construye el DOM con `textContent` y nodos: no hay `innerHTML` con datos.
- Las exportaciones CSV/XLSX neutralizan la **inyección de fórmulas** (celdas que empiezan por `= + - @`).

## 7. Datos y concurrencia

- **ORM SQLAlchemy**: todas las consultas van parametrizadas.
- **Restricciones en la base de datos**: `CHECK` (stock ≥ 0, cantidades ≠ 0, estados válidos, cajas dentro de la imagen…), claves únicas y claves foráneas con `RESTRICT` o `SET NULL` según el caso.
- **Bloqueo de stock**: `SELECT … FOR UPDATE` con `populate_existing` en cada operación de stock. Las pruebas de concurrencia en PostgreSQL encontraron un fallo real que este cambio corrige: sin `populate_existing`, 6 pedidos simultáneos llegaron a vender 1 sola unidad.
- **Secretos**: solo por variables de entorno. La aplicación no arranca sin `SECRET_KEY` y `DATABASE_URL`, ni con la clave de ejemplo.

## 8. Pendiente para producción

Ver [09-despliegue-operacion.md](09-despliegue-operacion.md): HTTPS con proxy inverso, `SESSION_COOKIE_SECURE=true`, `TRUST_PROXY=true`, SMTP real y copias de seguridad programadas.
