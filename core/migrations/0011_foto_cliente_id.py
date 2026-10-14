from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_descarga_sin_conexion'),
    ]

    operations = [
        migrations.AddField(
            model_name='fotoot',
            name='cliente_id',
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
