# PredictaHVAC

Gestor de mantenimiento HVAC: órdenes de trabajo, clientes, instalaciones y equipos, informes PDF con firmas y trabajo sin conexión para técnicos de campo. Django + PostgreSQL, PWA.

**Estado:** versión piloto. Qué está hecho y qué falta para la 1.0: [docs/ESTADO_Y_PENDIENTES.md](docs/ESTADO_Y_PENDIENTES.md).

## Documentación
- Despliegue: [DEPLOY.md](DEPLOY.md)
- Política de uso de dispositivos: [docs/POLITICA_USO_DISPOSITIVOS.md](docs/POLITICA_USO_DISPOSITIVOS.md)
- Restauración de respaldos: [deploy/restaurar.md](deploy/restaurar.md)

## Desarrollo
```
python -m venv venv && venv\Scripts\activate    # en Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                              # y rellenar
python manage.py migrate
python manage.py runserver
```
Pruebas: `python manage.py test` y `node --test "jstests/*.test.mjs"`.
