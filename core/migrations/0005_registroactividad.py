from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_perfilusuario'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RegistroActividad',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('usuario_nombre', models.CharField(blank=True, max_length=150)),
                ('accion', models.CharField(choices=[('LOGIN', 'Inicio de sesión'), ('LOGOUT', 'Cierre de sesión'), ('LOGIN_FALLIDO', 'Intento de acceso fallido'), ('ACCESO_DENEGADO', 'Acceso denegado por rol'), ('EQUIPO_CREADO', 'Equipo creado'), ('EQUIPO_EDITADO', 'Equipo editado'), ('MANTENIMIENTO_REGISTRADO', 'Mantenimiento registrado'), ('REPORTE_DESCARGADO', 'Reporte PDF abierto'), ('CONSULTA_IA', 'Consulta al asistente IA'), ('USUARIO_CREADO', 'Usuario creado'), ('USUARIO_EDITADO', 'Usuario modificado')], max_length=30)),
                ('detalle', models.CharField(blank=True, max_length=255)),
                ('ip', models.GenericIPAddressField(blank=True, null=True)),
                ('fecha', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('usuario', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='actividad', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-fecha', '-id']},
        ),
    ]
