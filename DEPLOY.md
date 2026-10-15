# Despliegue en un VPS Linux (Ubuntu/Debian)

Stack: Nginx (HTTPS) → Gunicorn → Django, con PostgreSQL. Archivos de apoyo en `deploy/`.

## 0. Antes de empezar: necesitas un dominio

El modo sin conexión (Service Worker) **solo funciona por HTTPS**, y Let's Encrypt no emite certificados para una IP.
Opciones: comprar un dominio (unos pocos €/año) o usar un subdominio gratuito (DuckDNS, afraid.org).
Apunta un registro **A** del dominio a la IP del VPS y espera a que propague. Los puertos 80 y 443 se abren en el cortafuegos del apartado 1b (no actives `ufw` antes de permitir SSH).

## 1. Paquetes y usuario

```bash
sudo apt update && sudo apt install -y python3-venv python3-dev libpq-dev nginx postgresql certbot python3-certbot-nginx \
    ufw fail2ban unattended-upgrades age
sudo adduser --system --group --home /srv/predicta predicta
sudo usermod -aG predicta www-data   # opcional, según permisos de tu Nginx
```

## 1b. Endurecer el servidor (antes de abrir los puertos 80 y 443)

Haz esto con una segunda sesión SSH abierta, por si te equivocas. El orden importa: primero SSH, luego el cortafuegos.

```bash
# Usuario con sudo para administrar (no trabajes como root) y acceso SSH solo con clave
sudo adduser admin && sudo usermod -aG sudo admin
sudo -u admin mkdir -p /home/admin/.ssh && sudo -u admin nano /home/admin/.ssh/authorized_keys   # pega tu clave pública
sudo tee /etc/ssh/sshd_config.d/99-predicta.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
sudo sshd -t && sudo systemctl reload ssh      # prueba antes, en otra terminal: ssh admin@tu-servidor

# Cortafuegos: SSH primero, después la web
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable

# Frena intentos masivos de SSH (en Debian/Ubuntu la cárcel sshd viene activa por defecto) y aplica parches solos
sudo systemctl enable --now fail2ban
sudo dpkg-reconfigure -plow unattended-upgrades
```
PostgreSQL debe escuchar solo en local: comprueba que `listen_addresses = 'localhost'` (valor por defecto) y que
`sudo ss -ltnp | grep 5432` solo muestra `127.0.0.1`. No abras el puerto 5432 en el cortafuegos.

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
systemd-analyze security predicta     # puntuación de exposición del servicio (cuanto más baja, mejor)
```
La unidad viene endurecida (sistema de archivos de solo lectura salvo `media/`, sin privilegios, tope de memoria).
Si algún día la app necesita escribir en otra carpeta, añádela a `ReadWritePaths=`; ajusta `MemoryMax=` al tamaño de tu VPS.

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

## 8. Respaldos (cifrados y fuera del servidor)

Los respaldos contienen datos personales y firmas, por eso se **cifran con `age`** y se **copian fuera del servidor**
(sin esa copia, un fallo del VPS se lleva también las copias). La clave privada no se guarda en el servidor.

```bash
# 1) En TU equipo (no en el servidor): crea el par de claves y guarda la privada en un gestor de contraseñas
age-keygen -o clave-privada-age.txt            # imprime "Public key: age1..."

# 2) En el servidor: pon la clave PÚBLICA y el destino externo en el .env (ver deploy/env.production.example)
sudo -u predicta nano /srv/predicta/app/.env
#    RESPALDO_AGE_DESTINATARIO=age1...
#    RESPALDO_RCLONE_DESTINO=almacen:predicta     (rclone config) -- o --
#    RESPALDO_RSYNC_DESTINO=usuario@otro-host:/respaldos/predicta

# 3) Prueba manual y programación diaria
sudo -u predicta mkdir -p /srv/predicta/respaldos
sudo -u predicta /srv/predicta/app/deploy/respaldo.sh      # debe imprimir "respaldo ... correcto (cifrado y copiado fuera del servidor)"
sudo -u predicta crontab -e
# añade:  30 3 * * * /srv/predicta/app/deploy/respaldo.sh >> /srv/predicta/respaldos/respaldo.log 2>&1
```
Si falta la clave pública el script no hace nada y falla; si falta el destino externo guarda el respaldo cifrado en local
y termina con error (código 2), para que se note en `respaldo.log`. **Prueba la restauración** al menos una vez siguiendo
`deploy/restaurar.md`.

## 9. Actualizar la app

```bash
cd /srv/predicta/app && sudo -u predicta git pull
sudo -u predicta /srv/predicta/venv/bin/pip install -r requirements.txt
sudo -u predicta /srv/predicta/venv/bin/python manage.py migrate
sudo -u predicta /srv/predicta/venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart predicta
```

## Notas

- Los teléfonos de los técnicos guardan órdenes descargadas: entrega a cada técnico `docs/POLITICA_USO_DISPOSITIVOS.md` (bloqueo de pantalla obligatorio).
  Las órdenes ya enviadas se borran solas a los 3 días; el trabajo sin enviar se conserva hasta sincronizar.
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

## Correo: informes al cliente y avisos a gestión

Al finalizar una orden se envía el informe PDF a los correos de la ficha del cliente (pantalla *Clientes*), y los avisos
a gerentes y administradores llegan también por correo. Define en el `.env` el servidor SMTP (sin `EMAIL_HOST` los
correos solo se escriben en la consola):

```
EMAIL_HOST=smtp.tuproveedor.com
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=PredictaHVAC <informes@TU_DOMINIO>
```

Los envíos que fallan se reintentan (hasta 3 intentos en total) con este cron; al tercer fallo se avisa a gestión, que
puede reenviar desde la orden:

```
*/10 * * * * cd /srv/predicta/app && /srv/predicta/venv/bin/python manage.py enviar_informes >> /srv/predicta/respaldos/informes.log 2>&1
```

Aprobación automática para autónomos: `APROBACION_AUTOMATICA=1` en el `.env` (por defecto desactivada).
