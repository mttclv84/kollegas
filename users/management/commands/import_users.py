import re
import openpyxl
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from stores.models import Store, StoreCluster
from users.models import Role

User = get_user_model()

LIVELLO_MAP = {
    'utente ho':    'ho',
    'utente area':  'area',
    'utente base':  'base',
    'utente store': 'store',
}

# Mappa nome Excel (lowercase) → nome ruolo nel DB
RUOLO_MAP = {
    'area manager retail':           'Area Manager Retail',
    'assistant manager':             'Assistant Manager',
    'department manager':            'Department Manager',
    'grow with us ra-tm':            'GWU RA-TM',
    'guest':                         'Guest',
    'head office':                   'Head Office',
    'p & c administrator':           'P&C Admin',
    'p & c coordinator':             'P&C Coordinator',
    'retail assistant':              'Retail Assistant',
    'stage p&c':                     'Stage P&C',
    'store manager':                 'Store Manager',
    'store p & c business partner':  'P&C Store Business Partner',
    'team manager':                  'Team Manager',
    'team visual manager':           'Team Visual Manager',
    'visual manager':                'Visual Manager',
    'area bp':                       'Area BP',
    '** long absence **':            None,   # ruolo reale ignoto
}

# Nuovi ruoli da creare se non esistono
NUOVI_RUOLI = [
    'GWU RA-TM',
    'Stage P&C',
    'Team Visual Manager',
    'Area BP',
]


class Command(BaseCommand):
    help = 'Importa utenti da Excel con ruolo reale dall\'Excel'

    def add_arguments(self, parser):
        parser.add_argument(
            'file', nargs='?',
            default=r'C:\Users\matti\OneDrive\Desktop\Popsquare2.0\utenti attuali.xlsx'
        )

    def handle(self, *args, **options):
        path = options['file']
        self.stdout.write(f'Apertura file: {path}')

        wb = openpyxl.load_workbook(path)
        ws = wb.active

        # Crea eventuali nuovi ruoli
        for nome in NUOVI_RUOLI:
            _, created = Role.objects.get_or_create(nome=nome)
            if created:
                self.stdout.write(self.style.WARNING(f'Ruolo creato: {nome}'))

        # Dizionario nome_ruolo → id
        ruolo_id_by_nome = {r.nome: r.id for r in Role.objects.all()}

        # Store: store_num → store_id
        store_id_by_num = {}
        for s in Store.objects.all():
            m = re.search(r'manager(\d+)@', s.email_store)
            if m:
                store_id_by_num[int(m.group(1))] = s.id

        if 291 not in store_id_by_num:
            biella, created = Store.objects.get_or_create(
                email_store='manager291@primark.it',
                defaults={'nome': 'Biella', 'comune': 'Biella', 'provincia': 'BI'}
            )
            if created:
                StoreCluster.objects.create(store=biella,
                    store_managers=1, assistant_managers=1,
                    department_managers=1, team_managers=1, visual_managers=1)
            store_id_by_num[291] = biella.id

        existing_emails = set(User.objects.values_list('email', flat=True))
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        self.stdout.write(f'Righe: {len(rows)}')

        to_create = []
        to_update = []
        long_abs_count = saltati = ruolo_non_trovati = 0
        store_non_trovati = set()

        for row in rows:
            id_excel, cognome, nome, livello_raw, store_raw, ruolo_raw = row

            if not cognome or not nome:
                saltati += 1
                continue

            ruolo_raw_str = str(ruolo_raw or '').strip()
            is_long_absence = ruolo_raw_str.lower() == '** long absence **'
            if is_long_absence:
                long_abs_count += 1

            # Risolvi ruolo
            nome_ruolo_db = RUOLO_MAP.get(ruolo_raw_str.lower())
            if nome_ruolo_db is None and not is_long_absence and ruolo_raw_str:
                ruolo_non_trovati += 1
                self.stdout.write(self.style.WARNING(f'  Ruolo non mappato: {ruolo_raw_str!r}'))
            ruolo_id = ruolo_id_by_nome.get(nome_ruolo_db) if nome_ruolo_db else None

            livello = LIVELLO_MAP.get(str(livello_raw or '').strip().lower(), 'base')

            store_raw_str = str(store_raw or '').strip()
            m = re.search(r'(\d{3,4})$', store_raw_str)
            store_num = int(m.group(1)) if m else None
            store_id = store_id_by_num.get(store_num) if store_num else None
            if store_num and not store_id:
                store_non_trovati.add(store_raw_str)

            email = f'user{id_excel}@primark.it'
            data = {
                'cognome': str(cognome).strip(),
                'nome': str(nome).strip(),
                'livello_accesso': livello,
                'store_id': store_id,
                'codice_matricola': str(id_excel) if id_excel else '',
                'ruolo_id': ruolo_id,
                'long_absence': is_long_absence,
                'is_active': True,
            }

            if email in existing_emails:
                to_update.append((email, data))
            else:
                to_create.append((email, data))

        self.stdout.write(f'Nuovi: {len(to_create)}, Da aggiornare: {len(to_update)}')

        created_count = 0
        with transaction.atomic():
            for email, data in to_create:
                user = User(email=email, **data)
                user.set_password('Primark2026!')
                user.save()
                created_count += 1

        updated_count = 0
        with transaction.atomic():
            for email, data in to_update:
                User.objects.filter(email=email).update(**data)
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nImportazione completata:\n'
            f'  Creati:            {created_count}\n'
            f'  Aggiornati:        {updated_count}\n'
            f'  Saltati:           {saltati}\n'
            f'  Long Absence:      {long_abs_count}\n'
            f'  Ruoli non mappati: {ruolo_non_trovati}\n'
        ))

        if store_non_trovati:
            self.stdout.write(self.style.WARNING(
                'Store non trovati:\n  ' + '\n  '.join(sorted(store_non_trovati))
            ))
