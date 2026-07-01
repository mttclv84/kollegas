from django.core.management.base import BaseCommand
from stores.models import Store
from stores.views import _sync_store_user


class Command(BaseCommand):
    help = 'Crea o aggiorna i profili User per tutti gli store attivi'

    def handle(self, *args, **options):
        stores = Store.objects.filter(is_active=True)
        count = stores.count()
        self.stdout.write(f'Store attivi trovati: {count}')

        synced = 0
        skipped = 0
        for store in stores:
            if not store.portale_password:
                self.stdout.write(f'  SKIP {store.nome} — nessuna password impostata')
                skipped += 1
                continue
            _sync_store_user(store)
            self.stdout.write(f'  OK   {store.nome} ({store.email_store})')
            synced += 1

        self.stdout.write(self.style.SUCCESS(f'Sincronizzati: {synced} | Saltati: {skipped}'))
