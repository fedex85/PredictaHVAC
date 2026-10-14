from datetime import date

from django.conf import settings
from django.db import models

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
