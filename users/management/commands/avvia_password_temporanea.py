from datetime import timedelta

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from stores.models import Store
from users.accesso import LIVELLI_SENZA_ACCESSO, revoca_sessioni
from users.models import GIORNI_PASSWORD_TEMPORANEA

User = get_user_model()


class Command(BaseCommand):
    help = ('Lancio: assegna la password comune temporanea ai profili abilitati che non hanno ancora '
            'scelto la propria e cancella le password in chiaro. Senza --applica esegue solo una prova.')

    def add_arguments(self, parser):
        parser.add_argument('--applica', action='store_true')

    def handle(self, *args, **options):
        comune = settings.KOLLEGAS_PASSWORD_COMUNE
        if not comune:
            raise CommandError('Imposta la variabile d\'ambiente KOLLEGAS_PASSWORD_COMUNE prima del lancio.')
        # password_cambiata_il vuoto: rilanciare il comando non tocca chi è già passato di qui.
        profili = (User.objects.filter(is_active=True, sola_lettura=False, password_cambiata_il__isnull=True)
                   .exclude(livello_accesso__in=LIVELLI_SENZA_ACCESSO))
        conteggi = {}
        with transaction.atomic():
            for user in profili:
                conteggi[user.livello_accesso] = conteggi.get(user.livello_accesso, 0) + 1
                if user.livello_accesso == 'admin':
                    # L'Admin tiene la password attuale e non scade: è lui a sbloccare gli altri.
                    user.deve_cambiare_password = True
                    user.save(update_fields=['deve_cambiare_password'])
                else:
                    user.imposta_password_temporanea(comune)
                    user.save()
                    revoca_sessioni(user)
            chiaro_utenti = User.objects.exclude(raw_password='').update(raw_password='')
            chiaro_negozi = Store.objects.exclude(portale_password='').update(portale_password='')
            if not options['applica']:
                transaction.set_rollback(True)

        for livello, numero in sorted(conteggi.items()):
            self.stdout.write(f'  {livello}: {numero}')
        scadenza = timezone.localtime(timezone.now() + timedelta(days=GIORNI_PASSWORD_TEMPORANEA))
        self.stdout.write(f'Scadenza password comune: {scadenza:%d/%m/%Y %H:%M}')
        self.stdout.write(f'Password in chiaro da cancellare: {chiaro_utenti} utenti, {chiaro_negozi} negozi')
        esito = 'AVVIATO' if options['applica'] else 'PROVA, nessuna modifica salvata'
        self.stdout.write(self.style.SUCCESS(f'{sum(conteggi.values())} profili — {esito}.'))
