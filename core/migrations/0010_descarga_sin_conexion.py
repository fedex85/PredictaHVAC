from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_incidencias_alta'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='ordentrabajo',
            name='descargada_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Descargada para trabajo sin conexión'),
        ),
        migrations.CreateModel(
            name='SincronizacionOT',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('paquete_id', models.UUIDField(unique=True)),
                ('creada_en', models.DateTimeField(auto_now_add=True)),
                ('firma', models.CharField(blank=True, max_length=12)),
                ('orden', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sincronizaciones', to='core.ordentrabajo')),
                ('usuario', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
