from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from stores.models import Store, StoreCluster
from users.models import Role

User = get_user_model()

STORES = [
    (270, 'Arese 270', 'Arese', 'MI', 'manager270@primark.it', 1, 2, 8, 22, 1),
    (275, 'Milano Via Torino 275', 'Milano', 'MI', 'manager275@primark.it', 1, 2, 9, 23, 1),
    (271, 'Firenze 271', 'Firenze', 'FI', 'manager271@primark.it', 1, 2, 7, 18, 1),
    (272, 'Brescia 272', 'Brescia', 'BS', 'manager272@primark.it', 1, 1, 5, 13, 1),
    (273, 'Verona 273', 'Verona', 'VR', 'manager273@primark.it', 1, 1, 7, 16, 1),
    (274, 'Roma Est 274', 'Roma', 'RM', 'manager274@primark.it', 1, 1, 7, 18, 1),
    (276, 'Fiordaliso 276', 'Rozzano', 'MI', 'manager276@primark.it', 1, 1, 5, 15, 1),
    (277, 'Roma Maximo 277', 'Roma', 'RM', 'manager277@primark.it', 1, 2, 7, 20, 1),
    (278, 'Bologna 278', 'Bologna', 'BO', 'manager278@primark.it', 1, 1, 6, 16, 1),
    (279, 'Torino 279', 'Torino', 'TO', 'manager279@primark.it', 1, 1, 5, 13, 1),
    (280, 'Caserta 280', 'Caserta', 'CE', 'manager280@primark.it', 1, 2, 7, 18, 1),
    (281, 'Venezia 281', 'Venezia', 'VE', 'manager281@primark.it', 1, 1, 5, 13, 1),
    (282, 'Catania 282', 'Catania', 'CT', 'manager282@primark.it', 1, 1, 6, 16, 1),
    (283, 'Chieti 283', 'Chieti', 'CH', 'manager283@primark.it', 1, 1, 4, 10, 1),
    (284, 'Bari 284', 'Bari', 'BA', 'manager284@primark.it', 1, 1, 4, 13, 1),
    (287, 'Torino ToDream 287', 'Torino', 'TO', 'manager287@primark.it', 1, 1, 4, 10, 1),
    (288, 'Livorno 288', 'Livorno', 'LI', 'manager288@primark.it', 1, 1, 3, 9, 1),
    (285, 'Salerno 285', 'Salerno', 'SA', 'manager285@primark.it', 1, 1, 4, 11, 1),
    (286, 'Cosenza 286', 'Cosenza', 'CS', 'manager286@primark.it', 1, 1, 4, 10, 1),
]

RUOLI = [
    'Store Manager', 'Assistant Manager', 'Department Manager',
    'Team Manager', 'Visual Manager', 'P&C Store Business Partner',
    'P&C Admin', 'P&C Coordinator', 'Retail Assistant',
    'Area Manager Retail', 'Head Office', 'Guest',
]


class Command(BaseCommand):
    help = 'Seed database con dati iniziali Popsquare'

    def handle(self, *args, **options):
        self.stdout.write('Creazione store...')
        for data in STORES:
            sid, nome, comune, prov, email, sm, am, dm, tm, vm = data
            store, created = Store.objects.get_or_create(
                email_store=email,
                defaults={'nome': nome, 'comune': comune, 'provincia': prov}
            )
            StoreCluster.objects.update_or_create(
                store=store,
                defaults={
                    'store_managers': sm,
                    'assistant_managers': am,
                    'department_managers': dm,
                    'team_managers': tm,
                    'visual_managers': vm,
                }
            )
            status = 'creato' if created else 'aggiornato'
            self.stdout.write(f'  Store {nome}: {status}')

        self.stdout.write('Creazione ruoli...')
        for nome in RUOLI:
            Role.objects.get_or_create(nome=nome)
            self.stdout.write(f'  Ruolo: {nome}')

        self.stdout.write('Creazione utente Admin...')
        admin, created = User.objects.get_or_create(
            email='mcalvi@primark.it',
            defaults={
                'cognome': 'Calvi',
                'nome': 'Mattia',
                'livello_accesso': 'admin',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin.set_password('Primark2026!')
            admin.save()
            self.stdout.write(self.style.SUCCESS('Admin creato: mcalvi@primark.it / Primark2026!'))
        else:
            self.stdout.write('Admin già esistente.')

        self.stdout.write(self.style.SUCCESS('Seed completato.'))
