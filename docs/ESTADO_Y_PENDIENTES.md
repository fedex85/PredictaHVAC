# Estado del proyecto y pendientes

**Versión actual: piloto.** El flujo completo funciona y está probado con pruebas automáticas y en uso real básico (móvil y PC). Antes de una versión 1.0 para varios clientes faltan los puntos de este documento.

Última actualización: octubre de 2026.

## Qué está hecho

**Flujo de órdenes de trabajo (según la especificación de flujo v1.0)**
- Estados: Pendiente → Asignada → En ejecución → Pendiente de aprobación → Finalizada / Cancelada, con historial de eventos.
- Llegada al sitio, verificación del equipo (código/QR), checklist, evidencias fotográficas y firma del técnico y del cliente.
- Subsanación, aprobación (manual o automática, configurable) y notas administrativas.
- OT de continuación con antecedente, OT de emergencia y próxima acción obligatoria al cerrar (derivar OT, programar o sin acción).
- Jerarquía Cliente → Instalación → Equipo como entidades separadas.
- Avisos a la gerencia dentro de la aplicación y por correo; envío del informe PDF al cliente con reintentos.

**Plataforma**
- Roles Administrador / Gerente / Técnico; PWA con trabajo sin conexión y sincronización.
- Informes PDF con sello de integridad de las firmas.
- Asistente con IA (Groq) con límites de uso.

**Seguridad y operación**
- MFA (TOTP), CSP con nonce, ruta de administración configurable y bitácora del panel.
- Caducidad de datos locales en el dispositivo y política de uso de dispositivos (`docs/POLITICA_USO_DISPOSITIVOS.md`).
- Respaldos cifrados con `age` (`deploy/respaldo.sh`, `deploy/restaurar.md`) y servicio endurecido (`deploy/gunicorn.service`).
- Pruebas automáticas (Python y JavaScript) y CI en GitHub Actions.

## Pendiente para una versión 1.0

### Prioridad alta
- [ ] **Piloto con técnicos reales** (1–2 técnicos, una o dos semanas): mala cobertura, fotos pesadas, dos dispositivos a la vez. Es donde suelen aparecer los fallos de sincronización.
- [ ] **Instalador de un solo paso** y script de actualización por cliente (hoy el despliegue es manual, ver `DEPLOY.md`).
- [ ] **Configuración por cliente**: SMTP (`EMAIL_*`), cron de `enviar_informes`, dominio y HTTPS.
- [ ] **Manual de usuario** para técnico y gerente.

### Prioridad media
- [ ] Escáner QR dentro de la app para verificar el equipo (hoy el código se escribe o se pega).
- [ ] Generador de etiquetas QR imprimibles para los equipos.
- [ ] Selectores en cascada Cliente → Instalación → Equipo al crear una OT (incómodo con muchos equipos).
- [ ] Panel o aviso cuando fallen los envíos de correo (hoy el estado se consulta en `EnvioInforme`).
- [ ] Auditoría de seguridad externa antes de manejar datos de clientes ajenos.

### Ideas a futuro
- Informes y métricas de mantenimiento por cliente/equipo.
- Mantenimiento programado recurrente generado automáticamente.
- Notificaciones push a los técnicos.

## Estado de verificación

| Área | Estado |
|---|---|
| Lógica de OT, permisos, sincronización | Pruebas automáticas (727 Python / 94 JS en la última ejecución) |
| Uso en móvil y PC | Comprobado manualmente por el autor, sin incidencias |
| Trabajo sin conexión con mala red real | Pendiente de piloto |
| Envío de correo en producción | Pendiente de configurar SMTP del cliente |
| Despliegue en servidor limpio | Pendiente de probar con el instalador |
| Seguridad | Revisión interna realizada; auditoría externa pendiente |

## Modelo de despliegue

Cada cliente usa su propia infraestructura (servidor, base de datos, correo y dominio). El código es el mismo para todos; lo que cambia es el archivo `.env`. Plantilla en `deploy/env.production.example`.
