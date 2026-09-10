from django.core.management.base import BaseCommand

from ehs.services import genera_notifiche_scadenza


class Command(BaseCommand):
    help = (
        'Genera le notifiche di scadenza formazione EHS (§8bis) per i partecipanti '
        'la cui scadenza_formazione è a 30 giorni o meno. Pensato per un cron '
        'giornaliero (es. Render Cron Job) — nessuno schedulatore è ancora configurato.'
    )

    def handle(self, *args, **options):
        creati = genera_notifiche_scadenza()
        self.stdout.write(self.style.SUCCESS(f'{creati} notifiche di scadenza create.'))
