from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_ordenes_trabajo'),
    ]

    operations = [
        migrations.AddField(
            model_name='ordentrabajo',
            name='con_checklist',
            field=models.BooleanField(default=True, verbose_name='Con checklist'),
        ),
        migrations.AddField(
            model_name='ordentrabajo',
            name='subsanacion_bloque',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.CreateModel(
            name='PuntoChecklistOT',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=30)),
                ('bloque', models.CharField(max_length=20)),
                ('texto', models.CharField(max_length=200)),
                ('orden_visual', models.PositiveSmallIntegerField(default=0)),
                ('resultado', models.CharField(blank=True, max_length=10)),
                ('gravedad', models.CharField(blank=True, max_length=10)),
                ('nota', models.CharField(blank=True, max_length=255)),
                ('orden', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='puntos', to='core.ordentrabajo')),
            ],
            options={
                'ordering': ['orden_visual', 'id'],
            },
        ),
        migrations.CreateModel(
            name='MedicionOT',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=30)),
                ('etiqueta', models.CharField(max_length=80)),
                ('unidad', models.CharField(max_length=10)),
                ('valor', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('obligatoria', models.BooleanField(default=True)),
                ('orden', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mediciones', to='core.ordentrabajo')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.AddConstraint(
            model_name='puntochecklistot',
            constraint=models.UniqueConstraint(fields=('orden', 'codigo'), name='uniq_punto_orden_codigo'),
        ),
        migrations.AddConstraint(
            model_name='medicionot',
            constraint=models.UniqueConstraint(fields=('orden', 'codigo'), name='uniq_medicion_orden_codigo'),
        ),
    ]
