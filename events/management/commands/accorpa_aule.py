"""Accorpa le aule "1/2" e "2/2" in un'unica attività con edizioni su due giornate.

Per ogni percorso nasce una nuova attività (es. "DM Leadership"): ogni giornata 1 viene
abbinata alla giornata 2 dello stesso gruppo (data entro 3 giorni, a parità scelta per
persone in comune) e le due diventano una Edizione della nuova attività. Le vecchie aule
rimaste vuote vengono disattivate; le giornate senza abbinamento restano dove sono.

Chi era presente a una sola giornata risulta "Parziale". Per le edizioni future chi è
iscritto a una giornata viene iscritto anche all'altra. Senza --applica è solo una prova.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from events.edizioni import PARZIALE, esito
from events.models import AttivitaCatalogo, Edizione, Evento
from participants.models import Iscrizione

ACCORPAMENTI = [
    ('DM Leadership', [['DM Leadership - Aula 1/2'], ['DM Leadership - Aula 2/2']]),
    ('GWU TM-DM - Leadership', [['GWU TM-DM - Leadership - Aula 1/2'], ['GWU TM-DM - Leadership - Aula 2/2']]),
    ('LOAS Modulo 1', [['LOAS Modulo1 - Aula 1/2', 'LOAS mod.1 - 1/2'], ['LOAS Modulo1 - aula 2/2']]),
    ('LOAS Modulo 2', [['LOAS Modulo 2 - aula 1/2'], ['LOAS Modulo 2 - aula 2/2']]),
    ('LOAS Modulo 3', [['LOAS Modulo 3 - aula 1/2'], ['LOAS Modulo 3 - aula 2/2']]),
]
MAX_GIORNI_TRA_GIORNATE = 3


def _iscritti(evento):
    return set(evento.iscrizioni.values_list('user_id', flat=True))


def abbina(prime, seconde):
    """Coppie (giornata 1, giornata 2) e giornate rimaste senza abbinamento."""
    libere = list(seconde)
    coppie, sole = [], []
    for prima in sorted(prime, key=lambda e: (e.data, e.id)):
        candidate = [s for s in libere if 0 < (s.data - prima.data).days <= MAX_GIORNI_TRA_GIORNATE]
        if not candidate:
            sole.append(prima)
            continue
        persone = _iscritti(prima)
        scelta = max(candidate, key=lambda s: (len(persone & _iscritti(s)), -(s.data - prima.data).days, -s.id))
        libere.remove(scelta)
        coppie.append((prima, scelta))
    return coppie, sole + libere


class Command(BaseCommand):
    help = 'Accorpa le aule 1/2 e 2/2 in edizioni su due giornate. Senza --applica esegue solo una prova.'

    def add_arguments(self, parser):
        parser.add_argument('--applica', action='store_true')

    def handle(self, *args, **options):
        oggi = timezone.localdate()
        with transaction.atomic():
            for nome_finale, gruppi in ACCORPAMENTI:
                self._accorpa(nome_finale, gruppi, oggi)
            if not options['applica']:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS('APPLICATO.' if options['applica'] else 'PROVA, nessuna modifica salvata.'))

    def _accorpa(self, nome_finale, gruppi, oggi):
        self.stdout.write(f'\n== {nome_finale}')
        attivita_gruppi = [list(AttivitaCatalogo.objects.filter(nome__in=nomi)) for nomi in gruppi]
        for nomi, trovate in zip(gruppi, attivita_gruppi):
            mancanti = set(nomi) - {a.nome for a in trovate}
            if mancanti:
                self.stdout.write(f'   non trovate nel catalogo: {", ".join(sorted(mancanti))}')
        if not all(attivita_gruppi):
            self.stdout.write('   SALTATO: manca una delle due aule.')
            return
        esistente = AttivitaCatalogo.objects.filter(nome=nome_finale).first()
        if esistente:
            self.stdout.write(f'   SALTATO: esiste già l\'attività "{nome_finale}" (id {esistente.id}): già accorpato?')
            return

        prime = list(Evento.objects.filter(attivita__in=attivita_gruppi[0], is_ehs=False, edizione__isnull=True))
        seconde = list(Evento.objects.filter(attivita__in=attivita_gruppi[1], is_ehs=False, edizione__isnull=True))
        coppie, sole = abbina(prime, seconde)

        # Nuova attività: le giornate senza abbinamento restano nelle vecchie aule, così
        # non vengono mai contate come corso completo.
        modello = attivita_gruppi[0][0]
        destinazione = AttivitaCatalogo.objects.create(nome=nome_finale, tipologia=modello.tipologia,
                                                       dettaglio=modello.dettaglio)
        for vecchia in (a for g in attivita_gruppi for a in g):
            destinazione.ruoli_destinatari.add(*vecchia.ruoli_destinatari.all())

        parziali = aggiunte = 0
        for prima, seconda in coppie:
            edizione = Edizione.objects.create()
            for giornata in (prima, seconda):
                giornata.edizione = edizione
                giornata.attivita = destinazione
                giornata.save()
            persone = _iscritti(prima) | _iscritti(seconda)
            # Edizioni future: l'iscrizione vale per entrambe le giornate.
            for giornata in (prima, seconda):
                if giornata.data >= oggi:
                    for user_id in persone - _iscritti(giornata):
                        Iscrizione.objects.create(evento=giornata, user_id=user_id, stato='iscritto')
                        aggiunte += 1
            for user_id in persone:
                stati = Iscrizione.objects.filter(evento__edizione=edizione, user_id=user_id).values_list('stato', flat=True)
                parziali += esito(stati, 2) == PARZIALE
            self.stdout.write(f'   edizione {prima.data:%d/%m/%Y} + {seconda.data:%d/%m/%Y}: {len(persone)} persone')

        for giornata in sole:
            self.stdout.write(f'   SENZA ABBINAMENTO (lasciata com\'è): {giornata.attivita.nome} del '
                              f'{giornata.data:%d/%m/%Y}, {len(_iscritti(giornata))} iscritti')
        disattivate = []
        for altra in (a for g in attivita_gruppi for a in g):
            if not altra.eventi.exists() and altra.is_active:
                altra.is_active = False
                altra.save(update_fields=['is_active'])
                disattivate.append(altra.nome)
        self.stdout.write(f'   {len(coppie)} edizioni create, {parziali} partecipazioni parziali, '
                          f'{aggiunte} iscrizioni aggiunte alle giornate future')
        if disattivate:
            self.stdout.write(f'   disattivate (vuote): {", ".join(disattivate)}')
