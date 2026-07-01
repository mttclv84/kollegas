import re
import openpyxl
from datetime import datetime, date, time, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from events.models import Host, AttivitaCatalogo, Evento
from participants.models import Iscrizione
from stores.models import Store

User = get_user_model()

STATO_MAP = {
    'partecipato': 'partecipato',
    'iscritto':    'iscritto',
    'assente':     'assente',
}

TIPO_TIPOLOGIA = {
    'corso di formazione':    'formazione',
    'attività interna store': 'sviluppo',
    'attivita interna store': 'sviluppo',
}


def calc_orari(ore_val):
    """Restituisce (ora_inizio, ora_fine) per un evento con N ore nette."""
    ore = float(ore_val or 8)
    ora_inizio = time(9, 0)
    minuti_lordi = int(ore * 60) + 60   # +60 per pausa pranzo
    fine_dt = datetime(2000, 1, 1, 9, 0) + timedelta(minutes=minuti_lordi)
    return ora_inizio, fine_dt.time()


def parse_location(loc_str, store_by_num):
    loc = str(loc_str or '').strip()
    if loc.upper() == 'ONLINE':
        return None, 'Online', 'online'
    m = re.search(r'(\d{3,4})$', loc)
    if m:
        num = int(m.group(1))
        sid = store_by_num.get(num)
        if sid:
            return sid, '', 'presenza'
    return None, loc, 'presenza'


class Command(BaseCommand):
    help = 'Importa storico partecipazioni da report.xlsx'

    def add_arguments(self, parser):
        parser.add_argument('file', nargs='?',
            default=r'C:\Users\matti\OneDrive\Desktop\Popsquare2.0\report.xlsx')

    def handle(self, *args, **options):
        wb = openpyxl.load_workbook(options['file'])
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        self.stdout.write(f'Righe da importare: {len(rows)}')

        # --- Indici di supporto ---
        store_by_num = {}
        for s in Store.objects.all():
            m = re.search(r'manager(\d+)@', s.email_store)
            if m:
                store_by_num[int(m.group(1))] = s.id

        # User lookup: "Cognome Nome" (case-insensitive) → user_id
        user_by_name = {}
        for u in User.objects.values('id', 'cognome', 'nome'):
            key = f"{u['cognome']} {u['nome']}".lower().strip()
            user_by_name[key] = u['id']

        # AttivitaCatalogo lookup: nome → id
        att_by_nome = {a.nome: a.id for a in AttivitaCatalogo.objects.all()}

        # Host placeholder per dati storici
        host_storico, _ = Host.objects.get_or_create(
            descrizione='Dato Storico',
            defaults={'posizione': 'interno', 'is_active': True}
        )

        # --- Raggruppa righe per evento unico ---
        # Chiave: (data, attivita_nome, location_repr, ore)
        eventi_map = {}   # key → dict con dati evento
        righe_per_key = {}  # key → [(collab_str, sesso, store_str, stato_str)]

        for row in rows:
            data_val, att_nome, ore, tipo, store_str, collab, sesso, location, stato = row
            if not data_val or not att_nome:
                continue

            att_nome = str(att_nome).strip()
            loc_sid, loc_est, modalita = parse_location(location, store_by_num)
            loc_repr = loc_sid or loc_est or ''

            # Normalizza data
            if isinstance(data_val, str):
                try:
                    data_obj = datetime.strptime(data_val, '%Y-%m-%d').date()
                except ValueError:
                    continue
            elif hasattr(data_val, 'date'):
                data_obj = data_val.date() if hasattr(data_val, 'date') and callable(data_val.date) else data_val
            else:
                data_obj = data_val

            key = (data_obj, att_nome, loc_repr, ore)

            if key not in eventi_map:
                tipologia = TIPO_TIPOLOGIA.get(str(tipo or '').strip().lower(), 'formazione')
                eventi_map[key] = {
                    'data': data_obj,
                    'att_nome': att_nome,
                    'ore': ore,
                    'tipologia': tipologia,
                    'location_store_id': loc_sid,
                    'location_esterna': loc_est,
                    'modalita': modalita,
                }
                righe_per_key[key] = []

            # Normalizza spazi multipli nei nomi
            collab_clean = ' '.join(str(collab or '').split())
            righe_per_key[key].append((
                collab_clean,
                str(sesso or '').strip(),
                str(store_str or '').strip(),
                str(stato or '').strip(),
            ))

        self.stdout.write(f'Eventi unici trovati: {len(eventi_map)}')

        # --- Crea eventi e iscrizioni ---
        eventi_creati = eventi_presenti = iscrizioni_create = 0
        utenti_non_trovati = set()

        with transaction.atomic():
            for key, ev_data in eventi_map.items():
                att_nome = ev_data['att_nome']

                # Crea attività se non esiste
                if att_nome not in att_by_nome:
                    att = AttivitaCatalogo.objects.create(
                        nome=att_nome,
                        tipologia=ev_data['tipologia'],
                        is_active=True,
                    )
                    att_by_nome[att_nome] = att.id
                    self.stdout.write(self.style.WARNING(f'  Attività creata on-the-fly: {att_nome}'))

                att_id = att_by_nome[att_nome]
                ora_inizio, ora_fine = calc_orari(ev_data['ore'])

                evento, created = Evento.objects.get_or_create(
                    data=ev_data['data'],
                    attivita_id=att_id,
                    location_store_id=ev_data['location_store_id'],
                    location_esterna=ev_data['location_esterna'],
                    defaults={
                        'ora_inizio': ora_inizio,
                        'ora_fine': ora_fine,
                        'host': host_storico,
                        'modalita_partecipazione': ev_data['modalita'],
                        'nota': 'Importato da storico',
                    }
                )
                if created:
                    eventi_creati += 1
                else:
                    eventi_presenti += 1

                # Crea iscrizioni
                for collab_str, sesso, store_str, stato_str in righe_per_key[key]:
                    uid = user_by_name.get(collab_str.lower())
                    if not uid:
                        utenti_non_trovati.add(collab_str)
                        continue

                    stato = STATO_MAP.get(stato_str.lower(), 'partecipato')
                    Iscrizione.objects.get_or_create(
                        evento=evento,
                        user_id=uid,
                        defaults={'stato': stato}
                    )
                    iscrizioni_create += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nImportazione report completata:\n'
            f'  Eventi creati:      {eventi_creati}\n'
            f'  Eventi già presenti:{eventi_presenti}\n'
            f'  Iscrizioni create:  {iscrizioni_create}\n'
            f'  Utenti non trovati: {len(utenti_non_trovati)}\n'
        ))

        if utenti_non_trovati:
            self.stdout.write(self.style.WARNING(
                f'Utenti non abbinati ({len(utenti_non_trovati)} nomi unici):\n  ' +
                '\n  '.join(sorted(utenti_non_trovati)[:30]) +
                ('\n  ...' if len(utenti_non_trovati) > 30 else '')
            ))
