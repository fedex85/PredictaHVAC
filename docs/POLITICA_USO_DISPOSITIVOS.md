# Política de uso de teléfonos y tabletas (PredictaHVAC)

Para técnicos y administradores. Cuando trabajas sin conexión, el teléfono guarda las órdenes que descargaste: datos del
cliente, fotos del equipo y firmas manuscritas. Esta política protege esos datos si el teléfono se pierde o se roba.

## Reglas para quien use la aplicación en un teléfono o tableta

1. **Bloqueo de pantalla obligatorio.** El teléfono debe pedir PIN (mínimo 6 dígitos), patrón largo, contraseña o
   huella/rostro para desbloquearse, con bloqueo automático en 5 minutos o menos. Es la protección principal: en
   Android e iPhone, con el bloqueo activado, todo el contenido del teléfono queda cifrado, incluidos los datos de la
   aplicación y las fotos.
2. **Cifrado del dispositivo activado.** En iPhone es automático al poner un código. En Android viene activado en los
   modelos actuales; si el teléfono es antiguo, compruébalo en Ajustes → Seguridad.
3. **Un teléfono, una persona.** No prestes el teléfono con tu sesión abierta. Si lo compartís, cada técnico inicia su
   propia sesión y cierra la suya al terminar.
4. **Sincroniza y cierra sesión al terminar la jornada.** La aplicación no te deja cerrar sesión mientras quede trabajo
   sin enviar: conéctate, sincroniza y después cierra. Las órdenes ya enviadas se borran del teléfono al cerrar sesión.
5. **No uses navegación privada ni borres los datos del navegador** con trabajo sin enviar: ese trabajo se perdería.
6. **Mantén el sistema y el navegador actualizados** y no instales aplicaciones de origen desconocido.
7. **Si pierdes el teléfono o te lo roban**, avisa de inmediato al administrador, aunque tuviera bloqueo de pantalla.

## Qué hace la aplicación por su cuenta

- Una orden descargada **sin trabajo pendiente se borra del teléfono a los 3 días** de la descarga (el servidor ya no deja
  empezarla pasadas 48 horas, así que deja de servir sin conexión). El plazo es `DIAS_RETENCION` en
  `core/static/sinconexion/sesion.js`.
- **El trabajo sin enviar nunca se borra solo**, por antiguo que sea: se conserva hasta que se sincroniza. Por eso el
  bloqueo de pantalla importa: mientras haya trabajo pendiente, esos datos siguen en el teléfono.
- Si entra otro usuario en el mismo teléfono, se borran las órdenes ya enviadas del anterior.

## Para el administrador: teléfono perdido o robado

1. Desactiva el usuario del técnico (Usuarios) para que no pueda iniciar sesión ni sincronizar, y restablece su
   contraseña y su verificación en dos pasos si la tenía.
2. Revisa la actividad reciente de ese usuario (Actividad).
3. Ten en cuenta que **dar de baja a un usuario no borra lo ya descargado en su teléfono**: la protección frente a ese
   caso es el bloqueo de pantalla y el cifrado del dispositivo. Pide al técnico que active, si puede, el borrado remoto
   del propio teléfono (Buscar mi iPhone / Encontrar mi dispositivo).
4. Si el teléfono tenía trabajo sin enviar, ese trabajo no se podrá recuperar: asigna de nuevo la orden y, si hay que
   dar aviso a clientes por la pérdida de sus datos, consúltalo con quien lleve la protección de datos (RGPD).
