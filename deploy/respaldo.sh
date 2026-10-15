#!/usr/bin/env bash
# Respaldo diario CIFRADO: base de datos (pg_dump) + carpeta media/ (fotos y firmas). Conserva 14 días en el servidor.
#
# Los archivos contienen datos personales y firmas manuscritas, así que nunca se guardan en claro: se cifran con
# `age` usando la CLAVE PÚBLICA (RESPALDO_AGE_DESTINATARIO). La clave privada NO debe estar en el servidor: guárdala
# en un gestor de contraseñas o en otro equipo; sin ella no se puede restaurar (ver deploy/restaurar.md).
# La copia fuera del servidor es obligatoria: si no hay destino configurado el script termina con error (código 2).
#
# Variables (en /srv/predicta/app/.env o en el entorno; el .env se LEE, nunca se ejecuta):
#   RESPALDO_AGE_DESTINATARIO  clave pública age (age1...)                      [obligatoria]
#   RESPALDO_RCLONE_DESTINO    destino de rclone, p. ej. almacen:predicta        [una de las dos]
#   RESPALDO_RSYNC_DESTINO     destino de rsync, p. ej. usuario@otro-host:/respaldos/predicta
#
# Cron (como usuario predicta):  30 3 * * * /srv/predicta/app/deploy/respaldo.sh >> /srv/predicta/respaldos/respaldo.log 2>&1
set -euo pipefail

APP=${APP:-/srv/predicta/app}
DESTINO=${DESTINO:-/srv/predicta/respaldos}
DIAS=${DIAS:-14}
ENV_FILE="$APP/.env"
SELLO=$(date +%Y%m%d-%H%M%S)

# Lee UNA variable del .env sin ejecutarlo: con `source`, un valor con $, comillas o acentos graves se
# interpretaría como código de shell.
leer() {
    local linea
    linea=$(grep -E "^[[:space:]]*$1=" "$ENV_FILE" | tail -n 1 || true)
    linea=${linea#*=}
    linea=${linea%$'\r'}
    if [[ $linea == \"*\" || $linea == \'*\' ]]; then linea=${linea:1:${#linea}-2}; fi
    printf '%s' "$linea"
}
error() { echo "$(date -Is) ERROR: $*" >&2; exit 1; }

[[ -r $ENV_FILE ]] || error "no se puede leer $ENV_FILE"
DB_NAME=$(leer DB_NAME); DB_USER=$(leer DB_USER); DB_PASSWORD=$(leer DB_PASSWORD)
DB_HOST=$(leer DB_HOST); DB_PORT=$(leer DB_PORT)
DESTINATARIO=${RESPALDO_AGE_DESTINATARIO:-$(leer RESPALDO_AGE_DESTINATARIO)}
RCLONE_DESTINO=${RESPALDO_RCLONE_DESTINO:-$(leer RESPALDO_RCLONE_DESTINO)}
RSYNC_DESTINO=${RESPALDO_RSYNC_DESTINO:-$(leer RESPALDO_RSYNC_DESTINO)}

[[ -n $DB_NAME && -n $DB_USER ]] || error "faltan DB_NAME o DB_USER en $ENV_FILE"
[[ -n $DESTINATARIO ]] || error "define RESPALDO_AGE_DESTINATARIO (clave pública age1...): los respaldos no se guardan sin cifrar"
command -v age > /dev/null || error "falta el programa 'age' (sudo apt install age)"

umask 077
mkdir -p "$DESTINO"
TMP=$(mktemp -d "$DESTINO/.tmp.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

# Base de datos: el volcado en claro solo existe en una carpeta temporal privada hasta cifrarlo.
PGPASSWORD="$DB_PASSWORD" pg_dump -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -U "$DB_USER" -Fc "$DB_NAME" > "$TMP/bd.dump"
pg_restore --list "$TMP/bd.dump" > /dev/null          # comprobación mínima: el volcado debe poder listarse
age -r "$DESTINATARIO" -o "$DESTINO/bd-$SELLO.dump.age" "$TMP/bd.dump"
rm -f "$TMP/bd.dump"

# Fotos y firmas: se cifran al vuelo, sin dejar el tar en claro.
tar -czf - -C "$APP" media | age -r "$DESTINATARIO" -o "$DESTINO/media-$SELLO.tar.gz.age"

[[ -s $DESTINO/bd-$SELLO.dump.age && -s $DESTINO/media-$SELLO.tar.gz.age ]] || error "algún archivo cifrado quedó vacío"

# Rotación local (también limpia respaldos antiguos sin cifrar, si los hubiera).
find "$DESTINO" -type f \( -name 'bd-*.dump.age' -o -name 'media-*.tar.gz.age' -o -name 'bd-*.dump' -o -name 'media-*.tar.gz' \) \
    -mtime +"$DIAS" -delete

# Copia fuera del servidor (obligatoria). Solo viajan los archivos cifrados.
if [[ -n $RCLONE_DESTINO ]]; then
    rclone copy "$DESTINO" "$RCLONE_DESTINO" --include '*.age' --max-age "${DIAS}d"
elif [[ -n $RSYNC_DESTINO ]]; then
    rsync -a --include='*.age' --exclude='*' "$DESTINO"/ "$RSYNC_DESTINO"/
else
    echo "$(date -Is) respaldo $SELLO cifrado en el servidor, pero SIN copia externa: define RESPALDO_RCLONE_DESTINO o RESPALDO_RSYNC_DESTINO" >&2
    exit 2
fi
echo "$(date -Is) respaldo $SELLO correcto (cifrado y copiado fuera del servidor)"
