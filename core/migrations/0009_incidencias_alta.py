from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_fotos_firma'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='ordentrabajo',
            name='orden_origen',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='correctivas', to='core.ordentrabajo', verbose_name='Orden de origen'),
        ),
        migrations.CreateModel(
            name='DecisionIncidenciaOT',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('CORRECTIVA', 'Correctiva'), ('JUSTIFICADA', 'Justificada')], max_length=12)),
                ('justificacion', models.TextField(blank=True)),
                ('decidida_en', models.DateTimeField(auto_now_add=True)),
                ('decidida_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('orden_correctiva', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='origen_de', to='core.ordentrabajo')),
                ('punto', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='decision', to='core.puntochecklistot')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.AddConstraint(
            model_name='decisionincidenciaot',
            constraint=models.CheckConstraint(condition=models.Q(('tipo', 'CORRECTIVA'), _negated=True) | models.Q(('orden_correctiva__isnull', False), ('justificacion', '')), name='incidencia_correctiva_coherente'),
        ),
        migrations.AddConstraint(
            model_name='decisionincidenciaot',
            constraint=models.CheckConstraint(condition=models.Q(('tipo', 'JUSTIFICADA'), _negated=True) | models.Q(('orden_correctiva__isnull', True), models.Q(('justificacion', ''), _negated=True)), name='incidencia_justificada_coherente'),
        ),
    ]
