from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='equipohvac',
            name='modelo',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='equipohvac',
            name='capacidad',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='equipohvac',
            name='refrigerante',
            field=models.CharField(blank=True, choices=[('R-410A', 'R-410A'), ('R-134a', 'R-134a'), ('R-22', 'R-22'), ('R-32', 'R-32'), ('R-407C', 'R-407C'), ('Otro', 'Otro / Agua-Glicol')], max_length=20),
        ),
    ]
