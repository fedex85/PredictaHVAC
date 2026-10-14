from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import core.models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_checklist_mediciones'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='ordentrabajo',
            name='con_evidencias',
            field=models.BooleanField(default=False, verbose_name='Exige fotografías y firma'),
        ),
        migrations.CreateModel(
            name='FotoOT',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('imagen', models.ImageField(upload_to=core.models.ruta_foto)),
                ('subida_en', models.DateTimeField(auto_now_add=True)),
                ('orden', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fotos', to='core.ordentrabajo')),
                ('subida_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['subida_en', 'id'],
            },
        ),
        migrations.CreateModel(
            name='FirmaOT',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('imagen', models.ImageField(upload_to=core.models.ruta_firma)),
                ('firmante', models.CharField(max_length=120)),
                ('firmada_en', models.DateTimeField(auto_now_add=True)),
                ('huella', models.CharField(max_length=64)),
                ('orden', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='firma', to='core.ordentrabajo')),
                ('recogida_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
