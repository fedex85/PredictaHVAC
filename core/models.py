import uuid
from datetime import date, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

class EquipoHVAC(models.Model):
    TIPO_CHOICES = [
        ('CHILLER', 'Chiller / Enfriador de Agua'),
        ('MINI_SPLIT', 'Mini Split'),
        ('SPLIT', 'Split'),
        ('VRF', 'Sistema VRF / VRV'),
        ('UMA', 'Manejadora de Aire (AHU)'),
        ('ROOFTOP', 'Unidad Paquete (Rooftop)'),
        ('OTRO', 'Otro / Industrial'),
    ]

    ESTADO_CHOICES = [
        ('OPERATIVO', 'Operativo'),
        ('MANTENIMIENTO', 'En Mantenimiento'),
        ('FUERA_SERVICIO', 'Fuera de Servicio'),
    ]

    REFRIGERANTE_CHOICES = [
        ('R-410A', 'R-410A'),
        ('R-134a', 'R-134a'),
        ('R-22', 'R-22'),
        ('R-32', 'R-32'),
        ('R-407C', 'R-407C'),
        ('Otro', 'Otro / Agua-Glicol'),
    ]

    nombre = models.CharField(max_length=100)
    codigo_identificador = models.CharField(max_length=50, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='SPLIT')
    ubicacion = models.CharField(max_length=150)
    modelo = models.CharField(max_length=100, blank=True)
    capacidad = models.CharField(max_length=50, blank=True)
    refrigerante = models.CharField(max_length=20, choices=REFRIGERANTE_CHOICES, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='OPERATIVO')
    fecha_instalacion = models.DateField(null=True, blank=True)
    PERIODICIDAD_CHOICES = [(1, 'Cada mes'), (3, 'Cada 3 meses'), (6, 'Cada 6 meses'), (12, 'Cada año')]
    periodicidad_meses = models.PositiveSmallIntegerField('Preventivo cada', null=True, blank=True,
                                                          choices=PERIODICIDAD_CHOICES)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} ({self.codigo_identificador})"


class HistorialMantenimiento(models.Model):
    TIPO_MANTENIMIENTO_CHOICES = [
        ('PREVENTIVO', 'Preventivo'),
        ('CORRECTIVO', 'Correctivo'),
    ]

    equipo = models.ForeignKey(EquipoHVAC, on_delete=models.CASCADE, related_name='mantenimientos')
    tipo_mantenimiento = models.CharField(max_length=20, choices=TIPO_MANTENIMIENTO_CHOICES, default='PREVENTIVO')
    descripcion = models.TextField()
    fecha_mantenimiento = models.DateField()
    tecnico_responsable = models.CharField(max_length=100)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tipo_mantenimiento} - {self.equipo.codigo_identificador} ({self.fecha_mantenimiento})"


class PerfilUsuario(models.Model):
    """Rol y certificación de gases fluorados de cada usuario (Administrador, Gerente o Técnico)."""
    ADMIN = 'ADMIN'
    GERENTE = 'GERENTE'
    TECNICO = 'TECNICO'
    ROL_CHOICES = [
        (ADMIN, 'Administrador'),
        (GERENTE, 'Gerente'),
        (TECNICO, 'Técnico'),
    ]
    CATEGORIA_CHOICES = [('I', 'I'), ('II', 'II'), ('III', 'III'), ('IV', 'IV')]

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
    rol = models.CharField(max_length=10, choices=ROL_CHOICES, default=TECNICO)
    cert_numero = models.CharField('Nº de certificado de gases fluorados', max_length=50, blank=True)
    cert_categoria = models.CharField('Categoría', max_length=3, choices=CATEGORIA_CHOICES, blank=True)
    cert_caducidad = models.DateField('Caducidad del certificado', null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    # La contraseña inicial la conoce quien creó la cuenta: se obliga a cambiarla en el primer acceso.
    debe_cambiar_clave = models.BooleanField('Debe cambiar la contraseña', default=False)

    def __str__(self):
        return f"{self.usuario} ({self.get_rol_display()})"

    @property
    def cert_estado(self):
        """'sin' si no hay certificado, 'caducado' o 'vigente'."""
        if not self.cert_numero or not self.cert_caducidad:
            return 'sin'
        return 'caducado' if self.cert_caducidad < date.today() else 'vigente'


class RegistroActividad(models.Model):
    """Bitácora de seguridad: quién entra, sale y qué hace. Solo se añade; no se edita ni se borra."""
    LOGIN = 'LOGIN'
    LOGOUT = 'LOGOUT'
    LOGIN_FALLIDO = 'LOGIN_FALLIDO'
    ACCESO_DENEGADO = 'ACCESO_DENEGADO'
    EQUIPO_CREADO = 'EQUIPO_CREADO'
    EQUIPO_EDITADO = 'EQUIPO_EDITADO'
    MANTENIMIENTO_REGISTRADO = 'MANTENIMIENTO_REGISTRADO'
    REPORTE_DESCARGADO = 'REPORTE_DESCARGADO'
    CONSULTA_IA = 'CONSULTA_IA'
    USUARIO_CREADO = 'USUARIO_CREADO'
    USUARIO_EDITADO = 'USUARIO_EDITADO'
    ORDEN_CREADA = 'ORDEN_CREADA'
    ORDEN_ACTUALIZADA = 'ORDEN_ACTUALIZADA'
    BLOQUEO_ACCESO = 'BLOQUEO_ACCESO'
    MFA_ACTIVADO = 'MFA_ACTIVADO'
    MFA_FALLIDO = 'MFA_FALLIDO'
    MFA_RESTABLECIDO = 'MFA_RESTABLECIDO'
    CLAVE_ENLACE = 'CLAVE_ENLACE'
    CLAVE_CAMBIADA = 'CLAVE_CAMBIADA'
    ACCION_CHOICES = [
        (LOGIN, 'Inicio de sesión'),
        (LOGOUT, 'Cierre de sesión'),
        (LOGIN_FALLIDO, 'Intento de acceso fallido'),
        (ACCESO_DENEGADO, 'Acceso denegado por rol'),
        (EQUIPO_CREADO, 'Equipo creado'),
        (EQUIPO_EDITADO, 'Equipo editado'),
        (MANTENIMIENTO_REGISTRADO, 'Mantenimiento registrado'),
        (REPORTE_DESCARGADO, 'Reporte PDF abierto'),
        (CONSULTA_IA, 'Consulta al asistente IA'),
        (USUARIO_CREADO, 'Usuario creado'),
        (USUARIO_EDITADO, 'Usuario modificado'),
        (ORDEN_CREADA, 'Orden de trabajo creada'),
        (ORDEN_ACTUALIZADA, 'Orden de trabajo actualizada'),
        (BLOQUEO_ACCESO, 'Acceso bloqueado por intentos fallidos'),
        (MFA_ACTIVADO, 'Verificación en dos pasos activada'),
        (MFA_FALLIDO, 'Código de verificación incorrecto'),
        (MFA_RESTABLECIDO, 'Verificación en dos pasos restablecida'),
        (CLAVE_ENLACE, 'Enlace de contraseña generado'),
        (CLAVE_CAMBIADA, 'Contraseña cambiada'),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='actividad')
    usuario_nombre = models.CharField(max_length=150, blank=True)  # copia: se conserva aunque se borre el usuario
    accion = models.CharField(max_length=30, choices=ACCION_CHOICES)
    detalle = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d %H:%M} {self.usuario_nombre} {self.accion}"


class BloqueoAcceso(models.Model):
    """Contador de fallos por usuario+IP para frenar la fuerza bruta (ver core/bloqueo.py)."""
    clave = models.CharField(max_length=255, unique=True)  # «usuario|ip» o «mfa:id|ip»
    fallos = models.PositiveSmallIntegerField(default=0)
    ultimo_fallo = models.DateTimeField()
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.clave} ({self.fallos})"


class DispositivoTOTP(models.Model):
    """Segundo factor (código de 6 dígitos de una app de autenticación) de un usuario."""
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='dispositivo_totp')
    secreto = models.CharField(max_length=64)  # base32
    confirmado = models.BooleanField(default=False)
    ultimo_paso = models.BigIntegerField(default=0)  # último intervalo de 30 s aceptado: impide reutilizar un código
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"TOTP de {self.usuario} ({'activo' if self.confirmado else 'sin confirmar'})"


class OrdenTrabajo(models.Model):
    """Orden de trabajo: Pendiente -> Asignada -> En ejecución -> Pendiente de aprobación -> Finalizada (o Cancelada)."""
    PENDIENTE = 'PENDIENTE'
    ASIGNADA = 'ASIGNADA'
    EN_EJECUCION = 'EN_EJECUCION'
    PENDIENTE_APROBACION = 'PENDIENTE_APROBACION'
    FINALIZADA = 'FINALIZADA'
    CANCELADA = 'CANCELADA'
    ESTADO_CHOICES = [
        (PENDIENTE, 'Pendiente'),
        (ASIGNADA, 'Asignada'),
        (EN_EJECUCION, 'En ejecución'),
        (PENDIENTE_APROBACION, 'Pendiente de aprobación'),
        (FINALIZADA, 'Finalizada'),
        (CANCELADA, 'Cancelada'),
    ]
    CRITICIDAD_CHOICES = [('BAJA', 'Baja'), ('MEDIA', 'Media'), ('ALTA', 'Alta')]

    equipo = models.ForeignKey(EquipoHVAC, on_delete=models.PROTECT, related_name='ordenes')
    tipo = models.CharField(max_length=20, choices=HistorialMantenimiento.TIPO_MANTENIMIENTO_CHOICES, default='PREVENTIVO')
    descripcion = models.TextField('Tarea a realizar')
    criticidad = models.CharField(max_length=10, choices=CRITICIDAD_CHOICES, default='MEDIA')
    requiere_refrigerante = models.BooleanField('Manipula refrigerante (gases fluorados)', default=False)
    fecha_programada = models.DateField('Fecha programada', null=True, blank=True)
    estado = models.CharField(max_length=25, choices=ESTADO_CHOICES, default=PENDIENTE, db_index=True)
    tecnico = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='ordenes_asignadas')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='ordenes_creadas')
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)
    inicio = models.DateTimeField(null=True, blank=True)
    fin = models.DateTimeField(null=True, blank=True)
    observaciones = models.TextField('Observaciones técnicas', blank=True)
    materiales = models.TextField('Materiales utilizados', blank=True)
    sin_materiales = models.BooleanField('Sin materiales', default=False)
    subsanacion_motivo = models.TextField(blank=True)
    cancelada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name='+')
    cancelada_en = models.DateTimeField(null=True, blank=True)
    motivo_cancelacion = models.TextField(blank=True)
    estado_previo_cancelacion = models.CharField(max_length=25, blank=True)
    mantenimiento = models.OneToOneField(HistorialMantenimiento, null=True, blank=True, on_delete=models.SET_NULL,
                                         related_name='orden')
    con_checklist = models.BooleanField('Con checklist', default=True)
    con_evidencias = models.BooleanField('Exige fotografías y firma', default=False)
    orden_origen = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='correctivas', verbose_name='Orden de origen')
    subsanacion_bloque = models.CharField(max_length=20, blank=True)
    descargada_en = models.DateTimeField('Descargada para trabajo sin conexión', null=True, blank=True)

    BLOQUES = [('CHECKLIST', 'Checklist'), ('MEDICIONES', 'Mediciones'),
               ('OBSERVACIONES', 'Observaciones técnicas'), ('MATERIALES', 'Materiales'),
               ('FOTOS', 'Fotografías'), ('FIRMA', 'Firma del cliente')]

    class Meta:
        ordering = ['-creada_en', '-id']

    def __str__(self):
        return f"{self.codigo} · {self.equipo.codigo_identificador}"

    @property
    def codigo(self):
        return f"OT-{self.pk:04d}" if self.pk else 'OT-nueva'

    @property
    def tiene_checklist(self):
        """Con checklist y con puntos generados (las órdenes anteriores a esta función no los tienen)."""
        return self.con_checklist and self.puntos.exists()

    @property
    def pausa_activa(self):
        return self.pausas.filter(hasta__isnull=True).first()

    @property
    def tiempo_efectivo(self):
        """Tiempo trabajado (descontando pausas) o None si aún no ha empezado."""
        if not self.inicio:
            return None
        fin = self.fin or timezone.now()
        pausado = timedelta()
        for p in self.pausas.all():
            pausado += (p.hasta or fin) - p.desde
        return max(fin - self.inicio - pausado, timedelta())

    @property
    def tiempo_efectivo_texto(self):
        t = self.tiempo_efectivo
        if t is None:
            return '—'
        minutos = int(t.total_seconds() // 60)
        return f"{minutos // 60} h {minutos % 60:02d} min"


class PausaOT(models.Model):
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name='pausas')
    motivo = models.CharField(max_length=255)
    desde = models.DateTimeField()
    hasta = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['desde', 'id']


class EventoOT(models.Model):
    """Historial de cambios de una orden: quién hizo qué y cuándo."""
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name='eventos')
    usuario_nombre = models.CharField(max_length=150, blank=True)
    texto = models.CharField(max_length=255)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha', 'id']


def ruta_foto(instancia, nombre):
    return f'ordenes/{instancia.orden_id}/fotos/{uuid.uuid4().hex}.jpg'


def ruta_firma(instancia, nombre):
    return f'ordenes/{instancia.orden_id}/firma/{uuid.uuid4().hex}.png'


class PuntoChecklistOT(models.Model):
    """Punto del checklist de una orden: copia del catálogo en el momento de iniciar la intervención."""
    OK = 'OK'
    INCIDENCIA = 'INCIDENCIA'
    GRAVEDADES = [('LEVE', 'Leve'), ('MEDIA', 'Media'), ('ALTA', 'Alta')]

    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name='puntos')
    codigo = models.CharField(max_length=30)
    bloque = models.CharField(max_length=20)
    texto = models.CharField(max_length=200)
    orden_visual = models.PositiveSmallIntegerField(default=0)
    resultado = models.CharField(max_length=10, blank=True)
    gravedad = models.CharField(max_length=10, blank=True)
    nota = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['orden_visual', 'id']
        constraints = [models.UniqueConstraint(fields=['orden', 'codigo'], name='uniq_punto_orden_codigo')]

    @property
    def completo(self):
        return self.resultado == self.OK or (self.resultado == self.INCIDENCIA and bool(self.gravedad))


class MedicionOT(models.Model):
    """Medición de una orden. `valor` es nulo hasta que el técnico la registra."""
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name='mediciones')
    codigo = models.CharField(max_length=30)
    etiqueta = models.CharField(max_length=80)
    unidad = models.CharField(max_length=10)
    valor = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    obligatoria = models.BooleanField(default=True)

    class Meta:
        ordering = ['id']
        constraints = [models.UniqueConstraint(fields=['orden', 'codigo'], name='uniq_medicion_orden_codigo')]

    @property
    def rango(self):
        """Texto del rango admitido (el del catálogo vigente), p. ej. «0 a 480 V»; vacío si el código no está en el catálogo."""
        from core import checklists
        d = checklists.MEDICIONES.get(self.codigo)
        return f'{d.minimo:f} a {d.maximo:f} {self.unidad}' if d else ''


class DecisionIncidenciaOT(models.Model):
    """Decisión de gestión sobre una incidencia de gravedad Alta: orden correctiva enlazada o justificación."""
    CORRECTIVA = 'CORRECTIVA'
    JUSTIFICADA = 'JUSTIFICADA'
    TIPO_CHOICES = [(CORRECTIVA, 'Correctiva'), (JUSTIFICADA, 'Justificada')]

    punto = models.OneToOneField(PuntoChecklistOT, on_delete=models.CASCADE, related_name='decision')
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES)
    orden_correctiva = models.ForeignKey(OrdenTrabajo, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name='origen_de')
    justificacion = models.TextField(blank=True)
    decidida_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')
    decidida_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(tipo='CORRECTIVA') | (models.Q(orden_correctiva__isnull=False) & models.Q(justificacion='')),
                name='incidencia_correctiva_coherente'),
            models.CheckConstraint(
                condition=~models.Q(tipo='JUSTIFICADA') | (models.Q(orden_correctiva__isnull=True) & ~models.Q(justificacion='')),
                name='incidencia_justificada_coherente'),
        ]


class FotoOT(models.Model):
    """Fotografía de la intervención. El archivo se guarda con un nombre generado, nunca el original."""
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name='fotos')
    imagen = models.ImageField(upload_to=ruta_foto)
    subida_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    subida_en = models.DateTimeField(auto_now_add=True)
    # Identificador que asigna el teléfono: reenviar la misma foto (sin conexión) no la duplica.
    cliente_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ['subida_en', 'id']


class FirmaOT(models.Model):
    """Firma manuscrita digital del cliente, vinculada a la orden. `huella` identifica el resumen que se firmó."""
    orden = models.OneToOneField(OrdenTrabajo, on_delete=models.CASCADE, related_name='firma')
    imagen = models.ImageField(upload_to=ruta_firma)
    firmante = models.CharField(max_length=120)
    recogida_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')
    firmada_en = models.DateTimeField(auto_now_add=True)
    huella = models.CharField(max_length=64)


class FirmaTecnicoOT(models.Model):
    """Firma manuscrita digital del técnico que ejecutó la orden. Se firma sobre el mismo resumen que el cliente
    y, a diferencia de la del cliente, hay que renovarla si el resumen cambia (también en una subsanación)."""
    orden = models.OneToOneField(OrdenTrabajo, on_delete=models.CASCADE, related_name='firma_tecnico')
    imagen = models.ImageField(upload_to=ruta_firma)
    firmante = models.CharField(max_length=120)
    firmada_en = models.DateTimeField(auto_now_add=True)
    huella = models.CharField(max_length=64)


class SincronizacionOT(models.Model):
    """Paquete de trabajo sin conexión ya recibido. `paquete_id` único: reenviar el mismo paquete no repite nada."""
    paquete_id = models.UUIDField(unique=True)
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name='sincronizaciones')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+')
    creada_en = models.DateTimeField(auto_now_add=True)
    firma = models.CharField(max_length=12, blank=True)  # guardada | descartada | ninguna

    def __str__(self):
        return f"{self.orden.codigo} · {self.paquete_id}"
