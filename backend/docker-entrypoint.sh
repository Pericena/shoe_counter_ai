#!/bin/sh
# Aplica migraciones pendientes antes de arrancar. Nunca borra datos.
set -e
flask --app run db upgrade
exec "$@"
