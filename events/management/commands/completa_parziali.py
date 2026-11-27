"""Considera completati i Parziali esistenti: chi è presente ad alcune giornate di
un'edizione ma non a tutte viene segnato presente anche alle giornate mancanti.
Riguarda solo la situazione di oggi; la regola del Parziale resta per il futuro.
Senza --applica è solo una prova.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from events.edizioni import PARZIALE, esiti_partecipazione
from events.models import Evento
from participants.models import Iscrizione


class Command(BaseCommand):
    help = 'Segna presenti a tutte le giornate i Parziali attuali. Senza --applica esegue solo una prova.'

    def add_arguments(self, parser):
        parser.add_argument('--applica', action='store_true')

    def handle(self, *args, **opt):
        esiti = esiti_partecipazione(Iscrizione.objects.filter(evento__edizione__isnull=False))
        parziali = sorted(((uid, k[1]) for (uid, k), (esito, _) in esiti.items() if esito == PARZIALE),
                          key=lambda x: (x[1], x[0]))
        aggiornate = create = 0
        with transaction.atomic():
            for user_id, edizione_id in parziali:
                giornate = list(Evento.objects.filter(edizione_id=edizione_id).select_related('attivita').order_by('data'))
                for giornata in giornate:
                    iscrizione, creata = Iscrizione.objects.get_or_create(
                        evento=giornata, user_id=user_id, defaults={'stato': 'partecipato'})
                    if creata:
                        create += 1
                    elif iscrizione.stato != 'partecipato':
                        iscrizione.stato = 'partecipato'
                        iscrizione.save(update_fields=['stato', 'updated_at'])
                        aggiornate += 1
                persona = Iscrizione.objects.filter(user_id=user_id).select_related('user').first().user
                self.stdout.write(f'   {persona.cognome} {persona.nome} — {giornate[0].attivita.nome}, '
                                  f'{" + ".join(f"{g.data:%d/%m/%Y}" for g in giornate)}')
            if not opt['applica']:
                transaction.set_rollback(True)
        self.stdout.write(f'{len(parziali)} parziali diventano completati: {aggiornate} giornate segnate presenti, '
                          f'{create} giornate aggiunte.')
        self.stdout.write(self.style.SUCCESS('APPLICATO.' if opt['applica'] else 'PROVA, nessuna modifica salvata.'))
