"""Unisce in una sola edizione alcune giornate già create come eventi separati e le sposta
nell'attività indicata (eventualmente rinominandola). Senza --applica è solo una prova.

Esempio:
  manage.py unisci_giornate --origine "GWU TM-DM Leadership Proram" --date 2025-03-11 2025-03-12 \
      --destinazione "GWU TM-DM - Leadership" --rinomina "GWU TM-DM Leadership"
Le giornate possono stare in attività diverse: --origine accetta più nomi.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from events.edizioni import PARZIALE, esito
from events.models import AttivitaCatalogo, Edizione, Evento
from participants.models import Iscrizione


class Command(BaseCommand):
    help = 'Unisce giornate separate in una edizione di un\'altra attività. Senza --applica esegue solo una prova.'

    def add_arguments(self, parser):
        parser.add_argument('--origine', nargs='+', required=True, help='Attività che contengono oggi le giornate')
        parser.add_argument('--date', nargs='+', required=True, help='Date delle giornate (AAAA-MM-GG)')
        parser.add_argument('--destinazione', required=True, help='Attività che riceve l\'edizione')
        parser.add_argument('--rinomina', help='Nuovo nome per l\'attività di destinazione')
        parser.add_argument('--applica', action='store_true')

    def handle(self, *args, **opt):
        try:
            giorni = sorted(date.fromisoformat(d) for d in opt['date'])
        except ValueError:
            raise CommandError('Date non valide: usa il formato AAAA-MM-GG.')
        if len(giorni) < 2 or len(set(giorni)) != len(giorni):
            raise CommandError('Indica almeno due date diverse.')
        origini = list(AttivitaCatalogo.objects.filter(nome__in=opt['origine']))
        mancanti = set(opt['origine']) - {a.nome for a in origini}
        destinazione = AttivitaCatalogo.objects.filter(nome=opt['destinazione']).first()
        if mancanti or not destinazione:
            raise CommandError(f'Attività non trovate: {", ".join(sorted(mancanti) or [opt["destinazione"]])}.')
        nuovo_nome = opt.get('rinomina')
        if nuovo_nome and AttivitaCatalogo.objects.filter(nome=nuovo_nome).exclude(pk=destinazione.pk).exists():
            raise CommandError(f'Esiste già un\'attività "{nuovo_nome}".')

        giornate = []
        for giorno in giorni:
            trovate = list(Evento.objects.filter(attivita__in=origini, data=giorno))
            if len(trovate) != 1:
                raise CommandError(f'{giorno:%d/%m/%Y}: attesa 1 giornata nelle attività di origine, trovate {len(trovate)}.')
            if trovate[0].edizione_id:
                raise CommandError(f'{giorno:%d/%m/%Y}: la giornata fa già parte di un\'edizione.')
            giornate.append(trovate[0])

        with transaction.atomic():
            edizione = Edizione.objects.create()
            for giornata in giornate:
                giornata.edizione = edizione
                giornata.attivita = destinazione
                giornata.save()
            if nuovo_nome:
                destinazione.nome = nuovo_nome
                destinazione.save(update_fields=['nome'])
            persone = set(Iscrizione.objects.filter(evento__in=giornate).values_list('user_id', flat=True))
            parziali = sum(esito(Iscrizione.objects.filter(evento__edizione=edizione, user_id=u)
                                 .values_list('stato', flat=True), len(giornate)) == PARZIALE for u in persone)
            disattivate = []
            for origine in origini:
                origine.refresh_from_db()
                if origine.pk != destinazione.pk and not origine.eventi.exists() and origine.is_active:
                    origine.is_active = False
                    origine.save(update_fields=['is_active'])
                    disattivate.append(origine.nome)
            if not opt['applica']:
                transaction.set_rollback(True)

        self.stdout.write(f'Edizione di {len(giornate)} giornate ({", ".join(f"{g:%d/%m/%Y}" for g in giorni)}) '
                          f'in "{nuovo_nome or destinazione.nome}": {len(persone)} persone, {parziali} parziali.')
        if nuovo_nome:
            self.stdout.write(f'Attività "{opt["destinazione"]}" rinominata in "{nuovo_nome}".')
        if disattivate:
            self.stdout.write(f'Disattivate (vuote): {", ".join(disattivate)}.')
        self.stdout.write(self.style.SUCCESS('APPLICATO.' if opt['applica'] else 'PROVA, nessuna modifica salvata.'))
