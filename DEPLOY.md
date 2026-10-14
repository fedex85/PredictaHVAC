# Despliegue en un VPS Linux (Ubuntu/Debian)

Stack: Nginx (HTTPS) → Gunicorn → Django, con PostgreSQL. Archivos de apoyo en `deploy/`.

## 0. Antes de empezar: necesitas un dominio

El modo sin conexión (Service Worker) **solo funciona por HTTPS**, y Let's Encrypt no emite certificados para una IP.
Opciones: comprar un dominio (unos pocos €/año) o usar un subdominio gratuito (DuckDNS, afraid.org).
Apunta un registro **A** del dominio a la IP del VPS y espera a que propague. Abre los puertos 80 y 443 (`sudo ufw allow 'Nginx Full'`).

## 1. Paquetes y usuario

```bash
sudo apt update && sudo apt install -y python3-venv python3-dev libpq-dev nginx postgresql certbot python3-certbot-nginx
sudo adduser --system --group --home /srv/predicta predicta
sudo usermod -aG predicta www-data   # opcional, según permisos de tu Nginx
```

## 2. Base de datos

```bash
sudo -u postgres psql -c "CREATE USER predicta WITH PASSWORD 'CAMBIA_ESTA_CLAVE';"
sudo -u postgres psql -c "CREATE DATABASE predicta OWNER predicta;"
```

## 3. Código y entorno

```bash
sudo -u predicta git clone TU_REPOSITORIO /srv/predicta/app      # o copia la carpeta con rsync/scp
sudo -u predicta python3 -m venv /srv/predicta/venv
sudo -u predicta /srv/predicta/venv/bin/pip install -r /srv/predicta/app/requirements.txt
sudo -u predicta cp /srv/predicta/app/deploy/env.production.example /srv/predicta/app/.env
sudo -u predicta chmod 600 /srv/predicta/app/.env
sudo -u predicta nano /srv/predicta/app/.env     # DJANGO_SECRET_KEY, dominio, clave de BD, GROQ_API_KEY
```

Con `DJANGO_DEBUG=0` la app **se niega a arrancar** si la clave secreta falta o es la de desarrollo.

## 4. Migraciones, estáticos y primer usuario

```bash
cd /srv/predicta/app
sudo -u predicta /srv/predicta/venv/bin/python manage.py migrate
sudo -u predicta /srv/predicta/venv/bin/python manage.py collectstatic --noinput
sudo -u predicta /srv/predicta/venv/bin/python manage.py createsuperuser
sudo -u predicta mkdir -p media
```
En producción, Administrador y Gerente deben activar la **verificación en dos pasos** (app de autenticación) la primera vez que entren: la app muestra un código QR. Si alguien pierde el teléfono, otro administrador pulsa «Restablecer verificación en dos pasos» en su ficha; si no queda ningún administrador:
`sudo -u predicta /srv/predicta/venv/bin/python manage.py reset_mfa correo@usuario`

## 5. Gunicorn (systemd)

```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/predicta.service
sudo systemctl daemon-reload && sudo systemctl enable --now predicta
sudo systemctl status predicta        # debe estar "active (running)"
```

## 6. Nginx y certificado HTTPS

```bash
sudo cp deploy/nginx-proxy.conf /etc/nginx/snippets/predicta-proxy.conf
# RUTA_ADMIN = el valor de DJANGO_ADMIN_URL de tu .env; TU_IP_O_VPN = tu IP fija o rango (p. ej. 203.0.113.7 o 10.8.0.0/24)
sudo sed -e 's/TU_DOMINIO/tu.dominio.com/g' -e 's#RUTA_ADMIN#la-ruta-aleatoria#' -e 's#TU_IP_O_VPN#203.0.113.7#' \
    deploy/nginx.conf | sudo tee /etc/nginx/sites-available/predicta
```
El panel de Django (`/RUTA_ADMIN/`) solo responde desde la IP/VPN que indiques; para el resto de visitantes Nginx devuelve 403 y la ruta `/admin/` no existe. Las altas, cambios y bajas hechas en el panel quedan en la bitácora de actividad.
Las subidas de fotos admiten 25 MB; el resto de rutas, 1 MB. Django envía una **Content-Security-Policy** con nonce: si tras una actualización alguna pantalla dejara de funcionar, pon `DJANGO_CSP_MODO=report-only` en el `.env` para diagnosticarlo en la consola del navegador (no lo dejes así).
El archivo de Nginx limita a 10 intentos/minuto por IP en el inicio de sesión y a 60/minuto en `/api/`, y fija `X-Real-IP` (la IP que registra la bitácora y que usa el bloqueo de Django).
Como el certificado aún no existe, primero deja solo el bloque `listen 80` y obtén el certificado:
```bash
sudo certbot --nginx -d tu.dominio.com        # crea el certificado y renueva solo (systemd timer)
```
Después comprueba que el bloque 443 de `deploy/nginx.conf` quedó activo, `sudo ln -s /etc/nginx/sites-available/predicta /etc/nginx/sites-enabled/`, `sudo nginx -t && sudo systemctl reload nginx`.

## 7. Verificación

```bash
sudo -u predicta /srv/predicta/venv/bin/python manage.py check --deploy
```
No debe quedar ningún aviso salvo, como mucho, `security.W004` (HSTS corto: normal al principio).
Luego, desde el móvil: abre `https://tu.dominio.com`, inicia sesión como técnico y prueba "Sin conexión → descargar" (el Service Worker se registra solo si hay candado HTTPS).
Cuando todo funcione unos días, sube `DJANGO_HSTS_SECONDS=31536000` en `.env` y reinicia (`sudo systemctl restart predicta`).

## 8. Respaldos

```bash
sudo -u predicta mkdir -p /srv/predicta/respaldos
sudo -u predicta /srv/predicta/app/deploy/respaldo.sh      # prueba manual: debe imprimir "respaldo ... correcto"
sudo -u predicta crontab -e
# añade:  30 3 * * * /srv/predicta/app/deploy/respaldo.sh >> /srv/predicta/respaldos/respaldo.log 2>&1
```
Guarda además una copia **fuera del servidor** (rclone, rsync o S3). Prueba la restauración siguiendo `deploy/restaurar.md`.

## 9. Actualizar la app

```bash
cd /srv/predicta/app && sudo -u predicta git pull
sudo -u predicta /srv/predicta/venv/bin/pip install -r requirements.txt
sudo -u predicta /srv/predicta/venv/bin/python manage.py migrate
sudo -u predicta /srv/predicta/venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart predicta
```

## Notas

- El CSS de Tailwind está compilado en `core/static/css/predicta.css` y va en el repositorio: el servidor **no necesita Node**.
  Si añades clases nuevas en plantillas o en los JS, regéneralo en tu PC con `npm run css` (la primera vez `npm install`) y súbelo con el resto.
  El test `core.test_css` avisa si falta una clase compilada.
- `media/` (fotos y firmas) no se publica por Nginx; Django la entrega solo con sesión iniciada.
- Si prefieres guardar `media/` en S3: `pip install django-storages boto3`, `ALMACENAMIENTO=nube` y las variables `S3_*` en `.env`.

## Preventivos automáticos (cron)

Los equipos con «Preventivo cada…» generan su orden Pendiente cuando faltan 15 días o menos (ajustable con `PREVENTIVOS_ANTICIPACION_DIAS` en `.env`).
Gestión puede generarlas a mano desde Órdenes → Preventivos, y además conviene programarlo cada día:

```bash
sudo -u predicta crontab -e
# añade (06:15 cada día):
15 6 * * * cd /srv/predicta/app && /srv/predicta/venv/bin/python manage.py generar_preventivos >> /srv/predicta/respaldos/preventivos.log 2>&1
```
Para ver qué crearía sin crear nada: `python manage.py generar_preventivos --dry-run`. El comando es idempotente: ejecutarlo dos veces no duplica órdenes.
