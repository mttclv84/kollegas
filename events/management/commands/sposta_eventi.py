"""Sposta tutte le formazioni (eventi ed edizioni su più giornate) di un'attività in
un'altra: chi le ha fatte risulta aver fatto l'attività di destinazione. L'attività di
origine, rimasta vuota, viene disattivata. Senza --applica è solo una prova.

Esempio: manage.py sposta_eventi --origine "DM Leadership" --destinazione "GWU TM-DM Leadership"
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.edizioni import PARTECIPATO, PARZIALE, esiti_partecipazione
from events.models import AttivitaCatalogo, Evento
from participants.models import Iscrizione


class Command(BaseCommand):
    help = 'Sposta tutte le formazioni di un\'attività in un\'altra. Senza --applica esegue solo una prova.'

    def add_arguments(self, parser):
        parser.add_argument('--origine', required=True)
        parser.add_argument('--destinazione', required=True)
        parser.add_argument('--applica', action='store_true')

    def handle(self, *args, **opt):
        origine = AttivitaCatalogo.objects.filter(nome=opt['origine']).first()
        destinazione = AttivitaCatalogo.objects.filter(nome=opt['destinazione']).first()
        if not origine or not destinazione or origine.pk == destinazione.pk:
            raise CommandError('Attività di origine o di destinazione non trovata (o coincidenti).')
        eventi = Evento.objects.filter(attivita=origine)
        edizioni = {e.edizione_id or f'ev{e.id}' for e in eventi}
        esiti = esiti_partecipazione(Iscrizione.objects.filter(evento__attivita=origine))
        persone = {u for u, _ in esiti}
        completati = sum(e == PARTECIPATO for e, _ in esiti.values())
        parziali = sum(e == PARZIALE for e, _ in esiti.values())
        n_eventi = eventi.count()

        with transaction.atomic():
            eventi.update(attivita=destinazione)
            destinazione.ruoli_destinatari.add(*origine.ruoli_destinatari.all())
            if origine.is_active:
                origine.is_active = False
                origine.save(update_fields=['is_active'])
            if not opt['applica']:
                transaction.set_rollback(True)

        self.stdout.write(f'"{origine.nome}" → "{destinazione.nome}": {n_eventi} giornate, {len(edizioni)} edizioni, '
                          f'{len(persone)} persone ({completati} partecipazioni complete, {parziali} parziali).')
        self.stdout.write(f'"{origine.nome}" disattivata.')
        self.stdout.write(self.style.SUCCESS('APPLICATO.' if opt['applica'] else 'PROVA, nessuna modifica salvata.'))
