"""Regole delle formazioni su più giornate (Edizione).

- Una persona ha *partecipato* solo se è presente a tutte le giornate.
- Se è presente ad alcune giornate ma non a tutte è *parziale*: non conta come partecipato.
- Le ore restano quelle delle giornate effettivamente frequentate.
- Un evento senza edizione è un'edizione di una sola giornata.
"""
from collections import defaultdict

from django.db.models import Count

PARTECIPATO, PARZIALE, ISCRITTO, ASSENTE = 'partecipato', 'parziale', 'iscritto', 'assente'

# Campi uguali per tutte le giornate di un'edizione (data e orari invece cambiano).
CAMPI_COMUNI = ('attivita', 'host', 'location_store', 'location_esterna', 'max_partecipanti',
                'modalita_partecipazione', 'nota')


def esito(stati, n_giornate=1):
    """Esito dell'edizione per una persona; le giornate senza iscrizione valgono come assenze."""
    stati = list(stati) + [ASSENTE] * max(0, n_giornate - len(stati))
    if stati and all(s == PARTECIPATO for s in stati):
        return PARTECIPATO
    if ISCRITTO in stati:
        return ISCRITTO
    if PARTECIPATO in stati:
        return PARZIALE
    return ASSENTE


def chiave(evento_id, edizione_id):
    return ('ed', edizione_id) if edizione_id else ('ev', evento_id)


def giornate_per_edizione(edizione_ids):
    from .models import Evento
    return dict(Evento.objects.filter(edizione_id__in=edizione_ids).values('edizione_id')
                .annotate(n=Count('id')).values_list('edizione_id', 'n'))


def esiti_partecipazione(iscrizioni):
    """{(user_id, chiave_edizione): (esito, attivita_id)} per un queryset di Iscrizione.
    Il queryset deve contenere tutte le giornate delle edizioni da valutare."""
    righe = list(iscrizioni.values_list('user_id', 'evento_id', 'evento__edizione_id', 'evento__attivita_id', 'stato'))
    n_giornate = giornate_per_edizione({r[2] for r in righe if r[2]})
    stati, attivita = defaultdict(list), {}
    for user_id, evento_id, edizione_id, attivita_id, stato in righe:
        k = (user_id, chiave(evento_id, edizione_id))
        stati[k].append(stato)
        attivita[k] = attivita_id
    return {k: (esito(s, n_giornate.get(k[1][1], 1) if k[1][0] == 'ed' else 1), attivita[k])
            for k, s in stati.items()}


def iscrizioni_complete(iscrizioni):
    """Allarga un queryset di Iscrizione a tutte le giornate delle edizioni coinvolte."""
    from django.db.models import Q
    from participants.models import Iscrizione
    edizioni = set(iscrizioni.exclude(evento__edizione__isnull=True).values_list('evento__edizione_id', flat=True))
    if not edizioni:
        return iscrizioni
    utenti = iscrizioni.values('user_id')
    return Iscrizione.objects.filter(Q(pk__in=iscrizioni.values('pk')) |
                                     Q(evento__edizione_id__in=edizioni, user_id__in=utenti))
