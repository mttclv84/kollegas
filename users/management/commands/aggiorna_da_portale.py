import collections
import datetime
import re

import openpyxl
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.models import AttivitaCatalogo, Evento, Host
from participants.models import Iscrizione
from stores.models import Store
from users.models import Role

User = get_user_model()

# --- Regole decise con l'utente (aggiornamento del 20/10/2026) ---

# id del vecchio portale da non importare: account di prova e doppioni presenti nel vecchio portale
ID_ESCLUSI = {
    '775',   # Supervisore Test
    '1310',  # testo testa
    '1332',  # doppione di Centesimo Vania (1274)
    '1311',  # doppione di Trincanato Fosca (1164)
    '1312',  # doppione di Rotondi Beatrice (887)
}
# doppione -> record da tenere: le iscrizioni del doppione vengono spostate e il doppione disattivato
DUPLICATI = {
    '1288': '1229',  # Taurino Rebecca
    '1239': '709',   # Labalestra Domenica
}
RUOLO_FORZATO = {'709': 'Department Manager'}
LIVELLO_FORZATO = {'268': 'base', '942': 'base'}  # Mariolu Giulia, Campagnola Veronica
NOME_FORZATO = {'1349': ('Zappulla', 'Noemi')}    # cognome/nome invertiti nel vecchio portale
RUOLO_HO_FISSO = {'596'}                          # Nardi Emanuele: resta Head Office
DA_DISATTIVARE = {'551'}                          # Vollero Salvatore

# Livello numerico del vecchio portale. 50 = account negozio (gestito dagli Store), 30 = account di prova
LIVELLO_MAP = {100: 'base', 60: 'area', 40: 'ho', 41: 'ho', 42: 'ho'}
LIVELLI_NON_IMPORTATI = {50, 30}
LIVELLI_INTOCCABILI = ('admin', 'admin_ehs', 'fornitore', 'store')

RUOLO_MAP = {
    'area manager retail':          'Area Manager Retail',
    'assistant manager':            'Assistant Manager',
    'department manager':           'Department Manager',
    'grow with us ra-tm':           'GWU RA-TM',
    'guest':                        'Guest',
    'head office':                  'Head Office',
    'p & c administrator':          'P&C Admin',
    'p & c coordinator':            'P&C Coordinator',
    'retail assistant':             'Retail Assistant',
    'stage p&c':                    'Stage P&C',
    'store manager':                'Store Manager',
    'store p & c business partner': 'P&C Store Business Partner',
    'team manager':                 'Team Manager',
    'team visual manager':          'Team Visual Manager',
    'visual manager':               'Visual Manager',
    'area bp':                      'Area BP',
}
LONG_ABSENCE = '** long absence **'
# Ruoli esistenti solo nel portale nuovo: non vengono sovrascritti dal vecchio
RUOLI_SOLO_PORTALE_NUOVO = {'L&D', 'Recruiting'}

STATO_MAP = {'validato': 'partecipato', 'da definire': 'iscritto'}
PRIORITA_STATO = {'partecipato': 3, 'assente': 2, 'iscritto': 1}
NOMI_MASCHILI_IN_A = {'andrea', 'luca', 'mattia', 'nicola', 'elia', 'enea', 'battista', 'gianluca', 'tobia', 'zaccaria'}
PASSWORD_INIZIALE = 'Primark2026!'


def norm(s):
    return ' '.join(str(s or '').split()).lower()


def leggi_xlsx(path):
    rows = list(openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True))
    return [r for r in rows[1:] if any(r)]


def sesso_da_nome(nome):
    parti = norm(nome).split()
    if not parti:
        return 'NS'
    if parti[0] in NOMI_MASCHILI_IN_A:
        return 'M'
    return 'F' if parti[0].endswith('a') else 'M'


class Command(BaseCommand):
    help = ('Aggiorna utenti e storico formazione dagli export del vecchio portale. '
            'Senza --applica esegue solo una prova e non salva nulla.')

    def add_arguments(self, parser):
        parser.add_argument('--anagrafica', help='xlsx: id, cognome, nome, livello utente, store, ruolo')
        parser.add_argument('--formazione', help='xlsx: Data, Attività, Ore, Store, Collaboratore, sesso, Location, Stato')
        parser.add_argument('--applica', action='store_true', help='Salva le modifiche (default: solo prova)')
        parser.add_argument('--no-disattiva', action='store_true',
                            help='Non disattivare gli utenti assenti dall\'anagrafica')

    def handle(self, *args, **options):
        if not options['anagrafica'] and not options['formazione']:
            raise CommandError('Indicare almeno --anagrafica o --formazione')
        self.log = collections.defaultdict(list)
        self.conteggi = collections.Counter()

        with transaction.atomic():
            self.store_by_num = {int(s.codice_store): s for s in Store.objects.all() if s.codice_store.isdigit()}
            self.regional_office = Store.objects.filter(codice_store='979').first()
            sesso_formazione = {}
            righe_formazione = leggi_xlsx(options['formazione']) if options['formazione'] else []
            for r in righe_formazione:
                if str(r[5] or '').strip().upper() in ('M', 'F'):
                    sesso_formazione[norm(r[4])] = str(r[5]).strip().upper()

            if options['anagrafica']:
                self.importa_anagrafica(leggi_xlsx(options['anagrafica']), sesso_formazione, not options['no_disattiva'])
            if righe_formazione:
                self.importa_formazione(righe_formazione)

            self.stampa_riepilogo(options['applica'])
            if not options['applica']:
                transaction.set_rollback(True)

    def risolvi_store(self, testo):
        t = str(testo or '').strip()
        if t == 'Regional Office Italy':
            return self.regional_office
        m = re.search(r'(\d{3,4})$', t)
        return self.store_by_num.get(int(m.group(1))) if m else None

    # ------------------------------------------------------------------ anagrafica
    def importa_anagrafica(self, righe, sesso_formazione, disattiva_assenti):
        ruoli = {r.nome: r for r in Role.objects.all()}
        by_mat = {u.codice_matricola: u for u in User.objects.exclude(codice_matricola='')}
        presenti = set()

        for id_portale, cognome, nome, livello_num, store_txt, ruolo_txt in (r[:6] for r in righe):
            mid = str(id_portale)
            if livello_num in LIVELLI_NON_IMPORTATI or mid in ID_ESCLUSI:
                continue
            presenti.add(mid)
            if mid in DUPLICATI:
                continue
            cognome, nome = NOME_FORZATO.get(mid, (str(cognome).strip(), str(nome).strip()))

            store = self.risolvi_store(store_txt)
            if store is None:
                self.log['ATTENZIONE store sconosciuto (negozio non aggiornato)'].append((mid, cognome, nome, store_txt))
            ruolo_norm = norm(ruolo_txt)
            long_absence = ruolo_norm == LONG_ABSENCE
            ruolo_nome = RUOLO_FORZATO.get(mid) or RUOLO_MAP.get(ruolo_norm)
            if ruolo_norm and not long_absence and not ruolo_nome:
                self.log['ATTENZIONE ruolo non mappato'].append((mid, cognome, nome, ruolo_txt))
            livello = LIVELLO_FORZATO.get(mid) or LIVELLO_MAP.get(livello_num)
            if livello is None:
                self.log['ATTENZIONE livello non mappato (utente saltato)'].append((mid, cognome, nome, livello_num))
                continue

            u = by_mat.get(mid)
            if u is None:
                omonimi = list(User.objects.filter(cognome__iexact=cognome, nome__iexact=nome))
                if omonimi:
                    self.log['ATTENZIONE nuovo id con nome già presente (saltato)'].append(
                        (mid, cognome, nome, [o.codice_matricola for o in omonimi]))
                    continue
                sesso = sesso_formazione.get(norm(f'{cognome} {nome}')) or sesso_da_nome(nome)
                u = User(email=f'user{mid}@primark.it', cognome=cognome, nome=nome, codice_matricola=mid,
                         livello_accesso=livello, store=store, ruolo=ruoli.get(ruolo_nome),
                         long_absence=long_absence, sesso=sesso)
                u.set_password(PASSWORD_INIZIALE)
                u.save()
                by_mat[mid] = u
                self.log['utenti creati'].append(
                    (mid, cognome, nome, livello, ruolo_nome, store.nome if store else None, sesso))
                continue

            modifiche = []
            if (u.cognome, u.nome) != (cognome, nome):
                modifiche.append(f'nome {u.cognome} {u.nome} -> {cognome} {nome}')
                u.cognome, u.nome = cognome, nome
            if u.livello_accesso not in LIVELLI_INTOCCABILI and u.livello_accesso != livello:
                modifiche.append(f'livello {u.livello_accesso} -> {livello}')
                u.livello_accesso = livello
            if store and u.store_id != store.id:
                modifiche.append(f'store {u.store.nome if u.store else None} -> {store.nome}')
                u.store = store
            ruolo_attuale = u.ruolo.nome if u.ruolo else None
            tieni_ruolo = (not ruolo_nome or long_absence or mid in RUOLO_HO_FISSO
                           or ruolo_attuale in RUOLI_SOLO_PORTALE_NUOVO)
            if not tieni_ruolo and ruolo_nome != ruolo_attuale:
                modifiche.append(f'ruolo {ruolo_attuale} -> {ruolo_nome}')
                u.ruolo = ruoli[ruolo_nome]
            if u.long_absence != long_absence:
                modifiche.append(f'long_absence -> {long_absence}')
                u.long_absence = long_absence
            if not u.is_active and mid not in DA_DISATTIVARE:
                modifiche.append('riattivato')
                u.is_active = True
            if modifiche:
                u.save()
                self.log['utenti aggiornati'].append((mid, f'{cognome} {nome}', '; '.join(modifiche)))

        self.unisci_duplicati(by_mat)

        for mid, u in by_mat.items():
            if not u.is_active or u.livello_accesso in LIVELLI_INTOCCABILI:
                continue
            if mid in DA_DISATTIVARE or (disattiva_assenti and mid not in presenti):
                u.is_active = False
                u.save()
                motivo = 'richiesta' if mid in DA_DISATTIVARE else 'assente dall\'anagrafica'
                self.log['utenti disattivati'].append((mid, u.cognome, u.nome, motivo))

    def unisci_duplicati(self, by_mat):
        for mid_doppione, mid_tenuto in DUPLICATI.items():
            doppione, tenuto = by_mat.get(mid_doppione), by_mat.get(mid_tenuto)
            if not doppione or not tenuto:
                continue
            for isc in list(doppione.iscrizioni.select_related('evento__attivita')):
                esistente = Iscrizione.objects.filter(evento=isc.evento, user=tenuto).first()
                if esistente:
                    if PRIORITA_STATO[isc.stato] > PRIORITA_STATO[esistente.stato]:
                        esistente.stato = isc.stato
                        esistente.save()
                    isc.delete()
                else:
                    isc.user = tenuto
                    isc.save()
                self.log['iscrizioni spostate da doppioni'].append(
                    (f'{mid_doppione}->{mid_tenuto}', isc.evento.data, isc.evento.attivita.nome[:50], isc.stato))
            if doppione.is_active:
                doppione.is_active = False
                doppione.save()
                self.log['utenti disattivati'].append((mid_doppione, doppione.cognome, doppione.nome, f'doppione di {mid_tenuto}'))

    # ------------------------------------------------------------------ formazione
    def importa_formazione(self, righe):
        attivita = {norm(a.nome): a for a in AttivitaCatalogo.objects.all()}
        host_storico, _ = Host.objects.get_or_create(descrizione='Dato Storico', defaults={'posizione': 'interno'})
        utenti = collections.defaultdict(dict)
        for u in User.objects.filter(is_active=True).exclude(livello_accesso='store'):
            utenti[norm(f'{u.cognome} {u.nome}')][u.id] = u
            utenti[norm(f'{u.nome} {u.cognome}')][u.id] = u
        nota = f'Importato da storico (agg. {datetime.date.today():%d/%m/%Y})'

        for data_val, att_nome, ore, store_txt, collab, _sesso, loc_txt, stato_txt in (r[:8] for r in righe):
            if str(store_txt or '').strip() == 'DISATTIVATI':
                self.conteggi['righe saltate (DISATTIVATI)'] += 1
                continue
            data = data_val.date() if isinstance(data_val, datetime.datetime) else datetime.date.fromisoformat(str(data_val)[:10])
            stato = STATO_MAP.get(norm(stato_txt))
            if stato is None:
                self.log['ATTENZIONE stato sconosciuto (riga saltata)'].append((data, collab, stato_txt))
                continue
            candidati = utenti.get(norm(collab), {})
            if len(candidati) != 1:
                self.log['ATTENZIONE collaboratore non trovato o omonimo (riga saltata)'].append(
                    (collab, store_txt, len(candidati)))
                continue
            u = next(iter(candidati.values()))

            att = attivita.get(norm(att_nome))
            if att is None:
                att = AttivitaCatalogo.objects.create(nome=str(att_nome).strip(), tipologia='altro')
                attivita[norm(att_nome)] = att
                self.log['attività create (tipologia ALTRO, da verificare)'].append((att.nome,))

            loc = str(loc_txt or '').strip()
            if loc.upper() == 'ONLINE':
                loc_store, loc_esterna, modalita = None, 'Online', 'online'
            else:
                loc_store = self.risolvi_store(loc)
                loc_esterna, modalita = ('' if loc_store else loc), 'presenza'

            evento = self.trova_evento(data, att, loc_store, loc_esterna, u)
            if evento is None:
                minuti = int(float(ore or 8) * 60) + 60  # +60 pausa pranzo
                ora_fine = (datetime.datetime(2000, 1, 1, 9) + datetime.timedelta(minutes=minuti)).time()
                evento = Evento.objects.create(
                    data=data, attivita=att, ora_inizio=datetime.time(9), ora_fine=ora_fine, host=host_storico,
                    location_store=loc_store, location_esterna=loc_esterna,
                    modalita_partecipazione=modalita, nota=nota,
                )
                self.log['eventi creati'].append((data, att.nome[:55], evento.location_display))

            isc = Iscrizione.objects.filter(evento=evento, user=u).first()
            if isc is None:
                Iscrizione.objects.create(evento=evento, user=u, stato=stato)
                self.conteggi[f'iscrizioni create ({stato})'] += 1
            elif isc.stato == stato:
                self.conteggi['iscrizioni invariate'] += 1
            elif stato == 'iscritto':
                # "da definire" non declassa una presenza/assenza già registrata
                self.conteggi[f'iscrizioni non declassate ({isc.stato})'] += 1
            else:
                self.conteggi[f'iscrizioni {isc.stato} -> {stato}'] += 1
                isc.stato = stato
                isc.save()

    def trova_evento(self, data, att, loc_store, loc_esterna, user):
        eventi = Evento.objects.filter(data=data, attivita=att)
        n = eventi.count()
        if n <= 1:
            return eventi.first()
        return (eventi.filter(location_store=loc_store, location_esterna=loc_esterna).first()
                or eventi.filter(iscrizioni__user=user).first()
                or eventi.first())

    # ------------------------------------------------------------------ output
    def stampa_riepilogo(self, applica):
        titolo = 'MODIFICHE APPLICATE' if applica else 'PROVA - nessuna modifica salvata (usa --applica)'
        self.stdout.write(self.style.SUCCESS(f'\n##### {titolo} #####'))
        for chiave in sorted(self.log, key=lambda k: (not k.startswith('ATTENZIONE'), k)):
            voci = self.log[chiave]
            stile = self.style.WARNING if chiave.startswith('ATTENZIONE') else self.style.HTTP_INFO
            self.stdout.write(stile(f'\n=== {chiave}: {len(voci)}'))
            for v in voci:
                self.stdout.write('    ' + ' | '.join(str(x) for x in v))
        if self.conteggi:
            self.stdout.write(self.style.HTTP_INFO('\n=== formazione'))
            for k, v in sorted(self.conteggi.items()):
                self.stdout.write(f'    {k}: {v}')
        self.stdout.write(
            f'\nUtenti attivi: {User.objects.filter(is_active=True).count()} | '
            f'Iscrizioni: {Iscrizione.objects.count()} | Eventi: {Evento.objects.count()}')
