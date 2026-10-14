from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_registroactividad'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='registroactividad',
            name='accion',
            field=models.CharField(choices=[('LOGIN', 'Inicio de sesión'), ('LOGOUT', 'Cierre de sesión'), ('LOGIN_FALLIDO', 'Intento de acceso fallido'), ('ACCESO_DENEGADO', 'Acceso denegado por rol'), ('EQUIPO_CREADO', 'Equipo creado'), ('EQUIPO_EDITADO', 'Equipo editado'), ('MANTENIMIENTO_REGISTRADO', 'Mantenimiento registrado'), ('REPORTE_DESCARGADO', 'Reporte PDF abierto'), ('CONSULTA_IA', 'Consulta al asistente IA'), ('USUARIO_CREADO', 'Usuario creado'), ('USUARIO_EDITADO', 'Usuario modificado'), ('ORDEN_CREADA', 'Orden de trabajo creada'), ('ORDEN_ACTUALIZADA', 'Orden de trabajo actualizada')], max_length=30),
        ),
        migrations.CreateModel(
            name='OrdenTrabajo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('PREVENTIVO', 'Preventivo'), ('CORRECTIVO', 'Correctivo')], default='PREVENTIVO', max_length=20)),
                ('descripcion', models.TextField(verbose_name='Tarea a realizar')),
                ('criticidad', models.CharField(choices=[('BAJA', 'Baja'), ('MEDIA', 'Media'), ('ALTA', 'Alta')], default='MEDIA', max_length=10)),
                ('requiere_refrigerante', models.BooleanField(default=False, verbose_name='Manipula refrigerante (gases fluorados)')),
                ('fecha_programada', models.DateField(blank=True, null=True, verbose_name='Fecha programada')),
                ('estado', models.CharField(choices=[('PENDIENTE', 'Pendiente'), ('ASIGNADA', 'Asignada'), ('EN_EJECUCION', 'En ejecución'), ('PENDIENTE_APROBACION', 'Pendiente de aprobación'), ('FINALIZADA', 'Finalizada'), ('CANCELADA', 'Cancelada')], db_index=True, default='PENDIENTE', max_length=25)),
                ('creada_en', models.DateTimeField(auto_now_add=True)),
                ('actualizada_en', models.DateTimeField(auto_now=True)),
                ('inicio', models.DateTimeField(blank=True, null=True)),
                ('fin', models.DateTimeField(blank=True, null=True)),
                ('observaciones', models.TextField(blank=True, verbose_name='Observaciones técnicas')),
                ('materiales', models.TextField(blank=True, verbose_name='Materiales utilizados')),
                ('sin_materiales', models.BooleanField(default=False, verbose_name='Sin materiales')),
                ('subsanacion_motivo', models.TextField(blank=True)),
                ('cancelada_en', models.DateTimeField(blank=True, null=True)),
                ('motivo_cancelacion', models.TextField(blank=True)),
                ('estado_previo_cancelacion', models.CharField(blank=True, max_length=25)),
                ('cancelada_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ordenes_creadas', to=settings.AUTH_USER_MODEL)),
                ('equipo', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ordenes', to='core.equipohvac')),
                ('mantenimiento', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='orden', to='core.historialmantenimiento')),
                ('tecnico', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ordenes_asignadas', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-creada_en', '-id']},
        ),
        migrations.CreateModel(
            name='PausaOT',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('motivo', models.CharField(max_length=255)),
                ('desde', models.DateTimeField()),
                ('hasta', models.DateTimeField(blank=True, null=True)),
                ('orden', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pausas', to='core.ordentrabajo')),
            ],
            options={'ordering': ['desde', 'id']},
        ),
        migrations.CreateModel(
            name='EventoOT',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('usuario_nombre', models.CharField(blank=True, max_length=150)),
                ('texto', models.CharField(max_length=255)),
                ('fecha', models.DateTimeField(auto_now_add=True)),
                ('orden', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='eventos', to='core.ordentrabajo')),
            ],
            options={'ordering': ['fecha', 'id']},
        ),
    ]
