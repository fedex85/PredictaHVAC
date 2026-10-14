import core.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('core', '0013_etiqueta_temperatura_inyeccion')]

    operations = [
        migrations.CreateModel(
            name='FirmaTecnicoOT',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('imagen', models.ImageField(upload_to=core.models.ruta_firma)),
                ('firmante', models.CharField(max_length=120)),
                ('firmada_en', models.DateTimeField(auto_now_add=True)),
                ('huella', models.CharField(max_length=64)),
                ('orden', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='firma_tecnico', to='core.ordentrabajo')),
            ],
        ),
    ]
