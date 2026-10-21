import collections
import datetime

import openpyxl
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl.utils import column_index_from_string

from ehs.models import EHSCorso, EHSFormazione, EHSMansione
from ehs.services import RUOLI_ESCLUSI_OBBLIGHI
from stores.models import Store

User = get_user_model()

FOGLIO = 'ELENCO FORMAZIONI'
PRIMA_RIGA_DATI = 4

# Colonne del file formazione negozio (formato del 280): lettera -> significato
COL_COGNOME, COL_NOME, COL_IN_FORZA, COL_JOB_TITLE = 'B', 'C', 'E', 'G'

# (codice corso, colonna data, colonna ore, aggiornamento)
COLONNE_CORSI = [
    ('PREPOSTI', 'AE', 'AF', False),
    ('PREPOSTI', 'AH', 'AI', True),
    ('DIRIGENTI', 'AT', 'AU', True),
    ('TRANSPALLET', 'AA', 'AB', False),
    ('TRANSPALLET', 'W', 'X', False),     # corso combinato Compattatore + Transpallet
    ('COMPATTATORE', 'W', 'X', False),
    ('COMPATTATORE', 'Y', 'Z', False),    # Compattatore Bramidan X25
    ('SCALE', 'AK', None, False),
]
# Dirigenti nel vecchio formato: moduli 1-2 e 3-4 (8 + 8 ore). Completo solo con entrambi.
DIRIGENTI_MODULI = (('AN', 'AO'), ('AQ', 'AR'))

# Job title del file -> mansione EHS (solo per le persone monitorate, non per i Retail Assistant)
MANSIONE_DA_JOB_TITLE = {
    'RA_STOCK': 'Stockroom', 'TM_STOCK': 'Stockroom',
    'RA_CASH': 'Cashoffice',
    'RA_VM': 'Visual',
    'EHS OP MNG': 'EHS OPS in Store Lead',
}


def norm(s):
    return ' '.join(str(s or '').split()).lower()


def data_valida(v):
    """Le celle contengono date vere, 'FORMARE', '#N/A' o lo 'zero' di Excel (1904): solo le prime contano."""
    if isinstance(v, datetime.datetime):
        v = v.date()
    if isinstance(v, datetime.date) and v.year >= 2000:
        return v
    return None


def ore_valide(v):
    try:
        ore = float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return ore if ore > 0 else None


class Command(BaseCommand):
    help = ('Importa nel registro EHS lo storico formazioni dal file Excel di un negozio. '
            'Senza --applica esegue solo una prova e non salva nulla.')

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--negozio', required=True, help='Codice negozio (es. 280)')
        parser.add_argument('--applica', action='store_true')

    def handle(self, *args, **options):
        negozio = Store.objects.filter(codice_store=options['negozio']).first()
        if negozio is None:
            raise CommandError(f'Negozio {options["negozio"]} non trovato')
        corsi = {c.codice: c for c in EHSCorso.objects.filter(codice__in={c[0] for c in COLONNE_CORSI} | {'DIRIGENTI'})}
        mansioni = {m.nome: m for m in EHSMansione.objects.all()}
        self.log = collections.defaultdict(list)
        self.conteggi = collections.Counter()

        utenti = (User.objects.filter(is_active=True).exclude(livello_accesso__in=('store', 'fornitore'))
                  .exclude(ruolo__nome__in=RUOLI_ESCLUSI_OBBLIGHI).select_related('store'))
        per_nome = collections.defaultdict(list)
        for u in utenti:
            per_nome[norm(f'{u.cognome} {u.nome}')].append(u)
            per_nome[norm(f'{u.nome} {u.cognome}')].append(u)

        idx = lambda lettera: column_index_from_string(lettera) - 1
        ws = openpyxl.load_workbook(options['file'], read_only=True, data_only=True)[FOGLIO]
        abbinati = set()

        with transaction.atomic():
            for riga in ws.iter_rows(min_row=PRIMA_RIGA_DATI, max_col=idx('CI') + 1, values_only=True):
                cognome, nome = riga[idx(COL_COGNOME)], riga[idx(COL_NOME)]
                if not cognome:
                    continue
                nome_file = ' '.join(f'{cognome} {nome or ""}'.split())
                candidati = {u.id: u for u in per_nome.get(norm(nome_file), [])}
                if len(candidati) > 1:
                    stesso_negozio = {k: u for k, u in candidati.items() if u.store_id == negozio.id}
                    candidati = stesso_negozio if len(stesso_negozio) == 1 else candidati
                if len(candidati) != 1:
                    if len(candidati) > 1:
                        self.log['ATTENZIONE omonimi (riga saltata)'].append((nome_file, len(candidati)))
                    else:
                        self.conteggi['righe senza persona monitorata in Kollegas (RA, usciti, ...)'] += 1
                    continue
                u = next(iter(candidati.values()))
                abbinati.add(u.id)
                if u.store_id != negozio.id:
                    self.log['abbinati in altro negozio (trasferiti?)'].append(
                        (nome_file, u.store.nome if u.store else None))

                for codice, col_data, col_ore, aggiornamento in COLONNE_CORSI:
                    data = data_valida(riga[idx(col_data)])
                    if data and codice in corsi:
                        ore = ore_valide(riga[idx(col_ore)]) if col_ore else None
                        self.registra(u, corsi[codice], data, ore, aggiornamento, nome_file)

                # Anche un solo modulo vale come formazione Dirigenti svolta (deciso con EHS).
                moduli = [(data_valida(riga[idx(d)]), ore_valide(riga[idx(o)])) for d, o in DIRIGENTI_MODULI]
                fatti = [(d, o) for d, o in moduli if d]
                if fatti and 'DIRIGENTI' in corsi:
                    note = 'Moduli 1-2 e 3-4' if len(fatti) == 2 else 'Un solo modulo nel file storico'
                    self.registra(u, corsi['DIRIGENTI'], max(d for d, _ in fatti),
                                  sum(o or 8 for _, o in fatti), False, nome_file, note=note)

                # La mansione del file vale solo per chi lavora ancora in questo negozio.
                mansione = mansioni.get(MANSIONE_DA_JOB_TITLE.get(str(riga[idx(COL_JOB_TITLE)] or '').strip()))
                if mansione and u.store_id == negozio.id and not u.ehs_mansioni.filter(pk=mansione.pk).exists():
                    u.ehs_mansioni.add(mansione)
                    self.log['mansioni assegnate'].append((nome_file, mansione.nome))

            mancanti = [u for u in utenti if u.store_id == negozio.id and u.id not in abbinati]
            for u in mancanti:
                self.log[f'persone di {negozio.nome} in Kollegas non trovate nel file'].append(
                    (u.cognome, u.nome, u.ruolo.nome if u.ruolo else None))

            self.riepilogo(options['applica'])
            if not options['applica']:
                transaction.set_rollback(True)

    def registra(self, utente, corso, data, ore, aggiornamento, nome_file, note=''):
        _, creata = EHSFormazione.objects.get_or_create(
            utente=utente, corso=corso, data=data,
            defaults={'ore': ore, 'aggiornamento': aggiornamento, 'fonte': 'import',
                      'note': note or 'Import file formazione negozio'},
        )
        chiave = f'{corso.nome}{" (aggiornamento)" if aggiornamento else ""}'
        self.conteggi[f'formazioni {"importate" if creata else "già presenti"}: {chiave}'] += 1
        if creata:
            self.log['formazioni importate'].append((nome_file, chiave, data, ore))

    def riepilogo(self, applica):
        titolo = 'MODIFICHE APPLICATE' if applica else 'PROVA - nessuna modifica salvata (usa --applica)'
        self.stdout.write(self.style.SUCCESS(f'\n##### {titolo} #####'))
        for chiave in sorted(self.log, key=lambda k: (not k.startswith('ATTENZIONE'), k)):
            voci = self.log[chiave]
            stile = self.style.WARNING if chiave.startswith('ATTENZIONE') else self.style.HTTP_INFO
            self.stdout.write(stile(f'\n=== {chiave}: {len(voci)}'))
            for v in voci:
                self.stdout.write('    ' + ' | '.join(str(x) for x in v))
        self.stdout.write(self.style.HTTP_INFO('\n=== conteggi'))
        for k, v in sorted(self.conteggi.items()):
            self.stdout.write(f'    {k}: {v}')
