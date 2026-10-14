# Restaurar un respaldo

Prueba esto al menos una vez en un servidor de ensayo: un respaldo que nunca se restauró no es un respaldo.

```bash
sudo systemctl stop predicta
cd /srv/predicta/respaldos            # elige los archivos con el mismo sello: bd-SELLO.dump y media-SELLO.tar.gz

# Base de datos (borra y recrea los objetos)
PGPASSWORD=... pg_restore -h localhost -U predicta -d predicta --clean --if-exists bd-SELLO.dump

# Fotos y firmas
tar -xzf media-SELLO.tar.gz -C /srv/predicta/app    # recrea /srv/predicta/app/media

sudo systemctl start predicta
```

Comprueba después: inicia sesión, abre una orden con fotos y descarga un PDF.
