# Instalación, operación, copias de seguridad y despliegue

## 1. Requisitos (Windows)

| Componente | Versión probada | Para qué |
|---|---|---|
| Docker Desktop | 29.7.2, Compose v5.5.0 | Ejecutar la app + PostgreSQL 16 (recomendado) |
| Python | 3.12 (`py -3.12`) | Ejecutar sin Docker, pruebas y comandos de administración |
| GPU NVIDIA (opcional) | RTX 3050 6 GB, driver 581.83, CUDA 12.6 | Solo para **entrenar** el detector. La app infiere en CPU |

Puertos: la app usa **8088**, publicado solo en `127.0.0.1`. PostgreSQL no se publica. Se evitan así los puertos de XAMPP: 80/443 (Apache), 3306 (MySQL) y 8080 (Tomcat).

## 2. Puesta en marcha con Docker (recomendado)

```bash
copy .env.example .env
```

Edita `.env`: pon `SECRET_KEY` aleatoria, `POSTGRES_PASSWORD` solo con letras y números y `SESSION_COOKIE_SECURE=false` en local. Después:

```bash
docker compose up --build -d
docker compose ps
docker compose exec app flask --app run users create-admin --username admin --full-name "Tu nombre"
```

- Abre http://localhost:8088 e inicia sesión.
- Las migraciones se aplican solas al arrancar el contenedor (`docker-entrypoint.sh` ejecuta `flask db upgrade`).
- `app` espera a que `db` esté *healthy*.

**Persistencia**

| Dato | Dónde |
|---|---|
| Base de datos | Volumen Docker `shoe_counter_ai_pgdata` |
| Fotos e importaciones | `.\storage` del equipo |
| Modelos ONNX | `.\modelo\exportados`, montado en solo lectura |

| Acción | Comando |
|---|---|
| Detener (conserva todo) | `docker compose stop` o `docker compose down` |
| Reiniciar | `docker compose up -d` |
| Actualizar tras cambios de código | `docker compose up --build -d` (migra sola) |
| Ver registros | `docker compose logs -f app` |
| **NUNCA** en uso normal | `docker compose down -v`: borra el volumen de la base de datos |

## 3. Sin Docker (entorno virtual)

```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
copy .env.example .env
```

Pon `SECRET_KEY` en `.env`. `DATABASE_URL` puede ser SQLite (`sqlite:///storage/dev.sqlite3`) o un PostgreSQL propio. Después:

```bash
cd backend
..\.venv\Scripts\flask --app run db upgrade
..\.venv\Scripts\flask --app run users create-admin --username admin
..\.venv\Scripts\python run.py
```

`run.py` usa waitress en `127.0.0.1:8088`. SQLite sirve para desarrollo; **no** aplica bloqueos de fila, así que para uso real usa PostgreSQL.

## 4. Copias de seguridad y recuperación

Los respaldos de **datos de la tienda** son responsabilidad operativa: no se generan automáticamente.

**Base de datos (Docker)**, formato comprimido de `pg_dump`:

```bash
docker compose exec -T db sh -c "pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc" > backups\shoe_counter_AAAAMMDD.dump
```

**Fotos e importaciones**: copia la carpeta `storage\`. Por ejemplo, con PowerShell:

```powershell
Compress-Archive -Path storage -DestinationPath backups\storage_AAAAMMDD.zip
```

**Restaurar** sobre una base vacía:

```bash
docker compose up -d db
docker compose exec -T db sh -c "pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists" < backups\shoe_counter_AAAAMMDD.dump
docker compose up -d
```

**Comprobar** después de restaurar: en la app, **Existencias → Verificar con movimientos** debe indicar que el stock coincide con el libro mayor.

Recomendación:

- Respaldo diario de la base de datos y semanal de `storage\`, en un disco distinto del equipo.
- Prueba de restauración mensual.
- `backups\` está en `.gitignore`.

## 5. Despliegue en un servidor (producción)

Hoy el sistema está configurado para **uso local**. Para exponerlo en red o en Internet:

1. **HTTPS obligatorio** con un proxy inverso (Caddy, nginx o Traefik) delante del contenedor `app`, que sigue escuchando solo en la red interna o en localhost.
2. En `.env`: `SESSION_COOKIE_SECURE=true`, `TRUST_PROXY=true` y `PUBLIC_BASE_URL=https://tu-dominio`.
3. **Secretos** fuera del repositorio: `SECRET_KEY` y `POSTGRES_PASSWORD` largos y aleatorios, en variables de entorno o en el gestor de secretos del servidor. Rotar `SECRET_KEY` cierra todas las sesiones.
4. **SMTP real** (`SMTP_*`) si se quiere recuperación de contraseña por correo.
5. **Copias de seguridad** programadas (punto 4) y monitorización de `/api/health`.
6. **Licencia del detector**: Ultralytics YOLO es AGPL-3.0 (ver [04-ia-detector.md](04-ia-detector.md) §7). Revísala antes de ofrecer el servicio a terceros.
7. **Pasarela de pago** si se activa el cobro en línea (ver [07-tienda-online.md](07-tienda-online.md) §5).

## 6. Activar o cambiar el modelo de IA

1. Entrena y exporta según [04-ia-detector.md](04-ia-detector.md). Se crea `modelo\exportados\<versión>\model.onnx` + `metadata.json`.
2. La app usa la versión más reciente. Para fijar una concreta: `AI_MODEL_VERSION=<versión>` en `.env`.
3. Con Docker la carpeta está montada: basta con `docker compose restart app`.
4. Comprueba en **Configuración → Detector de zapatos** que aparece la versión con sus métricas.
