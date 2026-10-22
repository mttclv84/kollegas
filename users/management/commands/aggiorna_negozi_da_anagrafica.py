import collections
import re
import unicodedata

import openpyxl
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.deletion import Collector

from stores.models import Store, StoreCluster
from stores.views import _sync_store_user
from users.models import Role

from .aggiorna_da_portale import PASSWORD_INIZIALE, sesso_da_nome

User = get_user_model()

# --- Regole decise con l'utente (anagrafica 25 negozi del 22/10/2026) ---

RUOLO_FILE = {
    'Team Visual Merchandising Manager': 'Team Visual Manager',
    'Visual Merchandising Manager': 'Visual Manager',
    'P&C Administrator Coordinator': 'P&C Coordinator',
    'Store BP': 'P&C Store Business Partner',
}
# Nome nel file scritto diversamente dal database -> matricola della persona
MATRICOLA_FORZATA = {
    'Max Squeo': '402', 'Maria Popa Cerasella': '780', 'Roberta Tomaso': '963',
    'Mariavittoria Chessari': '697', 'Giusi Chiavazzo': '128', 'Yamile Nayeli Anchai Ttito': '836',
    'Greta Silistrini': '579', 'Nicholas Matteo Salazar Palachagua': '848', 'Jocelyne Missinhoun': '1336',
    'Alfredo Mountuori': '641', 'Giorgia Vitielli': '37', 'Xkekseona Sinani': '223',
    'Leonardo Cignitti': '845', 'Jona Bajca': '336', 'Nicoletta Pirtac': '1193',
    'Anais Liziana Rocio Tello': '801', 'Corina M. Trandafir': '240', 'Stanislav V. Radev': '239',
    'G. Elisa Bonafè': '275', 'Beatrice R. Silmo': '164',
    'Domenica Labalestra': '709', 'Rebecca Taurino': '1229',      # doppioni già risolti a ottobre
    'Antonino Guglielmino': '1213', 'Christian Mola': '1281', 'Giuseppe Acanfora': '1326',
}
NOME_FORZATO = {'1326': ('Acanfora', 'Giuseppe')}
RUOLO_FORZATO = {'Giuseppe Acanfora': 'Team Manager'}
# Persone presenti su più negozi: negozio da tenere (None = da eliminare definitivamente)
NEGOZIO_FORZATO = {
    'Gioia Foti': None, 'Antonio Lanzano': '280', 'Liliana Capasso': '274', 'Ornela Marku': '275',
    'Shada Vitali': '277', 'Valentina Caruso': '279', 'Diana Garofalo': '280', 'Daniela Maggio': '285',
}
RUOLO_INVARIATO = {'Antonio Lanzano'}
RIGHE_IGNORATE = {'Ott in training'}
# Nuove persone con più nomi di battesimo: (cognome, nome)
DIVISIONE_NOME = {
    'Iuliana Bianca Iancu': ('Iancu', 'Iuliana Bianca'),
    'Salvatore Jonathan Bartolotta': ('Bartolotta', 'Salvatore Jonathan'),
    'Antonio Iulian Boroica': ('Boroica', 'Antonio Iulian'),
}
SESSO_FORZATO = {'Engy El Nagar': 'F', 'Beatrice Palmirani': 'F', 'Deborah Nuccio': 'F', 'Nicole Sulpizio': 'F'}
NUOVI_NEGOZI = {'297': {'nome': 'Perugia 297', 'comune': 'Perugia', 'provincia': 'PG'}}
PASSWORD_NEGOZIO = 'Primark01!'

# Ruoli che il file non contiene: chi li ha non viene disattivato
RUOLI_NON_NEL_FILE = {'P&C Admin', 'Stage P&C', 'Retail Assistant'}
LIVELLI_INTOCCABILI = ('admin', 'admin_ehs', 'fornitore', 'store')


def parole(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z ]', ' ', s).split()


def email_da_nome(nome, cognome):
    base = '.'.join([''.join(parole(nome)), ''.join(parole(cognome))])
    email, n = f'{base}@primark.it', 2
    while User.objects.filter(email__iexact=email).exists():
        email, n = f'{base}{n}@primark.it', n + 1
    return email


class Command(BaseCommand):
    help = ('Rimette le persone nei negozi corretti dall\'anagrafica dei 25 negozi '
            '(foglio "Riepilogo generale": Negozio, Nome e cognome, Ruolo). '
            'Senza --applica esegue solo una prova.')

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--applica', action='store_true')

    def handle(self, *args, **options):
        ws = openpyxl.load_workbook(options['file'], read_only=True, data_only=True)['Riepilogo generale']
        righe = [(str(r[0]).strip(), ' '.join(str(r[1]).split()), str(r[2]).strip())
                 for r in ws.iter_rows(min_row=2, values_only=True) if r and r[1]]
        self.log = collections.defaultdict(list)
        with transaction.atomic():
            self.esegui(righe)
            self.stampa(options['applica'])
            if not options['applica']:
                transaction.set_rollback(True)

    def esegui(self, righe):
        ruoli = {r.nome: r for r in Role.objects.all()}
        for codice, dati in NUOVI_NEGOZI.items():
            if not Store.objects.filter(codice_store=codice).exists():
                store = Store.objects.create(codice_store=codice, email_store=f'manager{codice}@primark.it',
                                             portale_password=PASSWORD_NEGOZIO, **dati)
                StoreCluster.objects.get_or_create(store=store)
                _sync_store_user(store, password=PASSWORD_NEGOZIO)
                self.log['negozi creati'].append(f'{store.nome} ({store.email_store})')
        negozi = {s.codice_store: s for s in Store.objects.all()}

        utenti = list(User.objects.exclude(livello_accesso__in=LIVELLI_INTOCCABILI).select_related('store', 'ruolo'))
        per_matricola = {u.codice_matricola: u for u in utenti if u.codice_matricola}
        per_parole = collections.defaultdict(list)
        for u in utenti:
            per_parole[frozenset(parole(u.nome) + parole(u.cognome))].append(u)

        def trova(nome):
            if nome in MATRICOLA_FORZATA:
                return [per_matricola[MATRICOLA_FORZATA[nome]]]
            trovati = per_parole.get(frozenset(parole(nome)), [])
            if trovati:
                return trovati
            p = set(parole(nome))
            return [u for u in utenti if set(parole(u.cognome)) & p
                    and (set(parole(u.nome) + parole(u.cognome)) <= p or p <= set(parole(u.nome) + parole(u.cognome)))]

        visti, presenti = set(), set()
        for negozio_txt, nome, ruolo_txt in righe:
            if nome in RIGHE_IGNORATE or (nome, negozio_txt) in visti:
                continue
            visti.add((nome, negozio_txt))
            codice = negozio_txt.split()[-1]
            if nome in NEGOZIO_FORZATO:
                # una sola volta, sul negozio deciso (che può anche non comparire nel file)
                if nome in visti:
                    continue
                visti.add(nome)
                if NEGOZIO_FORZATO[nome] is None:
                    self.elimina(trova(nome), nome)
                    continue
                codice = NEGOZIO_FORZATO[nome]
            store = negozi[codice]
            ruolo_nome = RUOLO_FORZATO.get(nome) or RUOLO_FILE.get(ruolo_txt, ruolo_txt)
            ruolo = ruoli[ruolo_nome]
            candidati = trova(nome)
            if len(candidati) > 1:
                self.log['ATTENZIONE omonimi (saltati)'].append(f'{nome} {negozio_txt}: ' + ', '.join(
                    f'{u.cognome} {u.nome} mat {u.codice_matricola}' for u in candidati))
                continue
            if not candidati:
                self.crea(nome, store, ruolo)
                continue
            u = candidati[0]
            presenti.add(u.id)
            modifiche = []
            nuovo_nome = NOME_FORZATO.get(u.codice_matricola)
            if nuovo_nome and (u.cognome, u.nome) != nuovo_nome:
                modifiche.append(f'nome {u.nome} -> {nuovo_nome[1]}')
                self.log['nomi corretti'].append(f'{u.cognome} {u.nome} -> {nuovo_nome[0]} {nuovo_nome[1]}')
                u.cognome, u.nome = nuovo_nome
            if u.store_id != store.id:
                modifiche.append(f'negozio {u.store.codice_store if u.store else "-"} -> {codice}')
                self.log['cambi negozio'].append(f'{u.cognome} {u.nome}: {u.store.codice_store if u.store else "-"} -> {codice}')
                u.store = store
            if nome not in RUOLO_INVARIATO and u.ruolo_id != ruolo.id:
                modifiche.append(f'ruolo {u.ruolo.nome if u.ruolo else "-"} -> {ruolo.nome}')
                self.log['cambi ruolo'].append(f'{u.cognome} {u.nome} ({codice}): {u.ruolo.nome if u.ruolo else "-"} -> {ruolo.nome}')
                u.ruolo = ruolo
            if not u.is_active:
                modifiche.append('riattivato')
                self.log['riattivati'].append(f'{u.cognome} {u.nome} ({codice})')
                u.is_active = True
            if modifiche:
                u.save()

        codici = {r[0].split()[-1] for r in righe}
        for u in utenti:
            if (u.id in presenti or not u.is_active or u.long_absence or not u.store
                    or u.store.codice_store not in codici or (u.ruolo and u.ruolo.nome in RUOLI_NON_NEL_FILE)):
                continue
            if not User.objects.filter(pk=u.pk).exists():   # eliminato sopra
                continue
            u.is_active = False
            u.save(update_fields=['is_active'])
            self.log['disattivati (assenti dal file)'].append(
                f'{u.store.codice_store} {u.cognome} {u.nome} ({u.ruolo.nome if u.ruolo else "-"})')

    def crea(self, nome_completo, store, ruolo):
        if nome_completo in DIVISIONE_NOME:
            cognome, nome = DIVISIONE_NOME[nome_completo]
        else:
            nome, _, cognome = nome_completo.partition(' ')
        nome, cognome = nome[:1].upper() + nome[1:], cognome
        sesso = SESSO_FORZATO.get(nome_completo) or sesso_da_nome(nome)
        u = User(email=email_da_nome(nome, cognome), cognome=cognome, nome=nome, store=store, ruolo=ruolo,
                 livello_accesso='base', sesso=sesso)
        u.set_password(PASSWORD_INIZIALE)
        u.save()
        self.log['utenti creati'].append(f'{store.codice_store} {cognome} {nome} | {ruolo.nome} | {sesso} | {u.email}')

    def elimina(self, candidati, nome):
        for u in candidati:
            if not User.objects.filter(pk=u.pk).exists():
                continue
            collector = Collector(using='default')
            collector.collect([u])
            collegati = collections.Counter()
            for model, oggetti in collector.data.items():
                if model is not User:
                    collegati[model._meta.verbose_name_plural] += len(oggetti)
            u.delete()
            self.log['eliminati definitivamente'].append(
                f'{u.cognome} {u.nome} mat {u.codice_matricola} — eliminati anche: '
                + (', '.join(f'{n} {k}' for k, n in collegati.items()) or 'nulla'))

    def stampa(self, applica):
        for titolo, voci in self.log.items():
            self.stdout.write(f'\n== {titolo.upper()} ({len(voci)})')
            for v in sorted(voci):
                self.stdout.write(f'  {v}')
        esito = 'MODIFICHE SALVATE' if applica else 'PROVA: nessuna modifica salvata (usa --applica)'
        self.stdout.write(self.style.SUCCESS(f'\n{esito}'))
