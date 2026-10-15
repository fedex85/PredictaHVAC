# Restaurar un respaldo

Los respaldos están **cifrados con `age`** (`bd-SELLO.dump.age` y `media-SELLO.tar.gz.age`). Para abrirlos necesitas la
**clave privada** (`age-1...`), que no está en el servidor: recupérala de tu gestor de contraseñas o del equipo donde la
guardaste y cópiala al servidor **solo durante la restauración** (bórrala después).

Prueba esto al menos una vez en un servidor de ensayo: un respaldo que nunca se restauró no es un respaldo.

```bash
sudo systemctl stop predicta
cd /srv/predicta/respaldos            # elige los archivos con el mismo sello; si ya no están, tráelos de la copia externa
CLAVE=/ruta/a/la/clave-privada-age.txt

# Base de datos (borra y recrea los objetos)
age -d -i "$CLAVE" bd-SELLO.dump.age | PGPASSWORD=... pg_restore -h localhost -U predicta -d predicta --clean --if-exists

# Fotos y firmas
age -d -i "$CLAVE" media-SELLO.tar.gz.age | tar -xz -C /srv/predicta/app    # recrea /srv/predicta/app/media

shred -u "$CLAVE"                      # si la copiaste al servidor
sudo systemctl start predicta
```

Comprueba después: inicia sesión, abre una orden con fotos y descarga un PDF (una firma alterada o ausente aparecería
señalada en el informe).

## Generar el par de claves (una sola vez, en tu equipo, no en el servidor)

```bash
age-keygen -o clave-privada-age.txt     # imprime la clave pública: "Public key: age1..."
```
Guarda `clave-privada-age.txt` fuera del servidor (gestor de contraseñas, y una segunda copia en otro sitio).
La clave pública (`age1...`) va en el `.env` del servidor como `RESPALDO_AGE_DESTINATARIO`.
**Si pierdes la clave privada, los respaldos no se pueden recuperar.**
