from django.core.management.base import BaseCommand

from core import correo_informe


class Command(BaseCommand):
    help = ('Reintenta el envío de los informes que fallaron o quedaron sin enviar (hasta 3 intentos por orden). '
            'Pensado para ejecutarse cada 5-10 minutos con cron.')

    def handle(self, *args, **opciones):
        pendientes = correo_informe.reintentos_pendientes()
        resultados = [correo_informe.intentar(pk) for pk in pendientes]
        self.stdout.write(self.style.SUCCESS(
            f'{len(pendientes)} envío(s) revisado(s): {resultados.count("ENVIADO")} enviado(s), '
            f'{resultados.count("FALLIDO")} fallido(s) definitivos.'))
