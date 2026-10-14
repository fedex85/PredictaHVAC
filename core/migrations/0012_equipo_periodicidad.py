from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_foto_cliente_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='equipohvac',
            name='periodicidad_meses',
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name='Preventivo cada',
                choices=[(1, 'Cada mes'), (3, 'Cada 3 meses'), (6, 'Cada 6 meses'), (12, 'Cada año')]),
        ),
    ]
