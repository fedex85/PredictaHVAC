from django.db import migrations


def renombrar(apps, schema_editor):
    MedicionOT = apps.get_model('core', 'MedicionOT')
    MedicionOT.objects.filter(codigo='TEMP_IMPULSION').update(etiqueta='Temperatura de inyección')


def restaurar(apps, schema_editor):
    MedicionOT = apps.get_model('core', 'MedicionOT')
    MedicionOT.objects.filter(codigo='TEMP_IMPULSION').update(etiqueta='Temperatura de impulsión')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_equipo_periodicidad'),
    ]

    operations = [
        migrations.RunPython(renombrar, restaurar),
    ]
