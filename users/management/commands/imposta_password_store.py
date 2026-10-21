from django.core.management.base import BaseCommand
from django.db import transaction

from stores.models import Store
from stores.views import _sync_store_user


class Command(BaseCommand):
    help = ('Imposta la stessa password per tutti i negozi attivi: password del portale '
            '(Store) e account di accesso del negozio. Senza --applica esegue solo una prova.')

    def add_arguments(self, parser):
        parser.add_argument('--password', required=True)
        parser.add_argument('--applica', action='store_true')

    def handle(self, *args, **options):
        password = options['password']
        negozi = Store.objects.filter(is_active=True).order_by('codice_store')
        with transaction.atomic():
            for store in negozi:
                store.portale_password = password
                store.save(update_fields=['portale_password'])
                _sync_store_user(store, password=password)
                self.stdout.write(f'  {store.codice_store:>4}  {store.nome}  ({store.email_store})')
            if not options['applica']:
                transaction.set_rollback(True)
        esito = 'aggiornati' if options['applica'] else 'da aggiornare (PROVA, nessuna modifica salvata)'
        self.stdout.write(self.style.SUCCESS(f'{negozi.count()} negozi {esito}.'))
