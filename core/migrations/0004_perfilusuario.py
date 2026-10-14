from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def crear_perfiles_existentes(apps, schema_editor):
    """Los usuarios que ya existían conservan su acceso: superusuarios/staff -> Administrador; resto -> Gerente."""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    Perfil = apps.get_model('core', 'PerfilUsuario')
    for u in User.objects.all():
        rol = 'ADMIN' if (u.is_superuser or u.is_staff) else 'GERENTE'
        Perfil.objects.get_or_create(usuario=u, defaults={'rol': rol})


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_equipohvac_tipo'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PerfilUsuario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rol', models.CharField(choices=[('ADMIN', 'Administrador'), ('GERENTE', 'Gerente'), ('TECNICO', 'Técnico')], default='TECNICO', max_length=10)),
                ('cert_numero', models.CharField(blank=True, max_length=50, verbose_name='Nº de certificado de gases fluorados')),
                ('cert_categoria', models.CharField(blank=True, choices=[('I', 'I'), ('II', 'II'), ('III', 'III'), ('IV', 'IV')], max_length=3, verbose_name='Categoría')),
                ('cert_caducidad', models.DateField(blank=True, null=True, verbose_name='Caducidad del certificado')),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('usuario', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='perfil', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RunPython(crear_perfiles_existentes, migrations.RunPython.noop),
    ]
