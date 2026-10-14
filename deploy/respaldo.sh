#!/usr/bin/env bash
# Respaldo diario: base de datos (pg_dump) + carpeta media/ (fotos y firmas). Conserva 14 días.
# Cron (como usuario predicta):  30 3 * * * /srv/predicta/app/deploy/respaldo.sh >> /srv/predicta/respaldos/respaldo.log 2>&1
set -euo pipefail

APP=/srv/predicta/app
DESTINO=/srv/predicta/respaldos
DIAS=14
SELLO=$(date +%Y%m%d-%H%M%S)

set -a; source "$APP/.env"; set +a
mkdir -p "$DESTINO"
umask 077

PGPASSWORD="$DB_PASSWORD" pg_dump -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -U "$DB_USER" -Fc "$DB_NAME" \
    > "$DESTINO/bd-$SELLO.dump"
tar -czf "$DESTINO/media-$SELLO.tar.gz" -C "$APP" media

# Comprobación mínima: el volcado debe poder listarse.
pg_restore --list "$DESTINO/bd-$SELLO.dump" > /dev/null
find "$DESTINO" -type f \( -name 'bd-*.dump' -o -name 'media-*.tar.gz' \) -mtime +"$DIAS" -delete
echo "$(date -Is) respaldo $SELLO correcto"
# Recomendado: copiar $DESTINO a otra máquina o almacenamiento externo (rclone, rsync, S3).
