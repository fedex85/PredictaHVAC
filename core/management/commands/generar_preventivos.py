from django.core.management.base import BaseCommand
from django.utils import timezone

from core import preventivos


class Command(BaseCommand):
    help = 'Crea las órdenes preventivas que tocan según el plan de cada equipo (pensado para ejecutarse una vez al día con cron).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Muestra qué se crearía sin crear nada.')

    def handle(self, *args, dry_run=False, **opciones):
        creadas = preventivos.generar(timezone.localdate(), simular=dry_run)
        verbo = 'Se crearían' if dry_run else 'Creadas'
        for equipo, fecha in creadas:
            self.stdout.write(f'{equipo.codigo_identificador} · {equipo.nombre}: preventivo para el {fecha:%d/%m/%Y}')
        self.stdout.write(self.style.SUCCESS(f'{verbo} {len(creadas)} orden(es) preventiva(s).'))
