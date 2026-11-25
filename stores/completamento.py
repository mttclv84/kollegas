"""Completamento dei programmi formativi: per ogni programma, quante persone del target
(per ruolo) hanno svolto ciascuna aula. Nei percorsi su più aule c'è anche la voce
"Percorso completo": conta chi le ha svolte tutte, come se fossero un unico corso."""
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import IsAdminOrHOOrAreaEHS

from .models import Area, Store

PROGRAMMI = {
    'gwu-ratm': {
        'titolo': 'GWU RA-TM',
        'ruoli': ['GWU RA-TM', 'Team Manager'],
        'corsi': [
            'GWU RA-TM / Management di Base | OBBLIGATORIO',
            'GWU RA-TM / Valutazione e Feedback | OBBLIGATORIO',
            'GWU RA-TM / Report&Sistemi | OBBLIGATORIO',
        ],
        'percorso': False,
    },
    # Corso unico su più giornate (aule accorpate con il comando accorpa_aule). Finché
    # l'accorpamento non è applicato si usano le vecchie aule, unite nel "percorso completo".
    'dm-leadership': {
        'titolo': 'DM Leadership',
        'ruoli': ['Department Manager'],
        'corsi': ['DM Leadership'],
        'corsi_precedenti': ['DM Leadership - Aula 1/2', 'DM Leadership - Aula 2/2'],
        'percorso': False,
    },
    'gwu-tm-dm': {
        'titolo': 'GWU TM-DM Leadership',
        'ruoli': ['Department Manager'],
        # Il nome corretto è "Leadership Program"; il secondo vale finché non è rinominata.
        'corsi': ['GWU TM-DM Leadership Program', 'GWU TM-DM - Leadership'],
        'corsi_precedenti': ['GWU TM-DM - Leadership - Aula 1/2', 'GWU TM-DM - Leadership - Aula 2/2'],
        'percorso': False,
    },
}
PROGRAMMA_PREDEFINITO = 'gwu-ratm'
ETICHETTE_BREVI = {'Team Manager': 'TM', 'Department Manager': 'DM'}
ID_PERCORSO = 'percorso'


def programma_richiesto(request):
    chiave = request.query_params.get('programma') or PROGRAMMA_PREDEFINITO
    if chiave not in PROGRAMMI:
        raise Http404('Programma sconosciuto.')
    programma = PROGRAMMI[chiave]
    return {'chiave': chiave, 'titolo': programma['titolo'], 'ruoli': programma['ruoli']}, programma


def nome_breve(nome):
    if ' - Aula ' in nome:
        return nome.rsplit(' - ', 1)[-1]
    if ' / ' in nome:
        return nome.split(' / ', 1)[1].split('|')[0].strip()
    return nome


def utenti_target(programma, **filtri):
    from users.models import User
    return list(User.objects.filter(is_active=True, ruolo__nome__in=programma['ruoli'], **filtri)
                .select_related('ruolo').order_by('ruolo__nome', 'cognome', 'nome'))


def _trova_attivita(nomi):
    from events.models import AttivitaCatalogo
    trovate = {a.nome: a for a in AttivitaCatalogo.objects.filter(nome__in=nomi)}
    return [trovate[n] for n in nomi if n in trovate]


def struttura_programma(programma):
    """(attività, percorso): le attività del programma e se unirle nel percorso completo."""
    attivita = _trova_attivita(programma['corsi'])
    if attivita or not programma.get('corsi_precedenti'):
        return attivita, programma['percorso']
    return _trova_attivita(programma['corsi_precedenti']), True


def voci_programma(attivita, user_ids, percorso):
    """Per ogni attività: chi l'ha completata, chi è iscritto a un'edizione non ancora
    svolta e chi è "parziale" (non presente a tutte le giornate: non conta come fatto)."""
    from events.edizioni import ISCRITTO, PARTECIPATO, PARZIALE, esiti_partecipazione, iscrizioni_complete
    from participants.models import Iscrizione
    gruppi = {PARTECIPATO: {a.id: set() for a in attivita}, ISCRITTO: {a.id: set() for a in attivita},
              PARZIALE: {a.id: set() for a in attivita}}
    iscrizioni = iscrizioni_complete(Iscrizione.objects.filter(evento__attivita__in=attivita, user_id__in=user_ids))
    for (user_id, _), (esito, att_id) in esiti_partecipazione(iscrizioni).items():
        if esito in gruppi and att_id in gruppi[esito]:
            gruppi[esito][att_id].add(user_id)
    voci = []
    for a in attivita:
        fatti = gruppi[PARTECIPATO][a.id]
        iscritti = gruppi[ISCRITTO][a.id] - fatti
        voci.append({'id': a.id, 'nome': a.nome, 'nome_breve': nome_breve(a.nome), 'percorso': False,
                     'fatti': fatti, 'iscritti': iscritti, 'parziali': gruppi[PARZIALE][a.id] - fatti - iscritti})
    if percorso and len(voci) > 1:
        # Completo = tutte le aule svolte; in procinto = ogni aula mancante ha già un'iscrizione.
        completi = set.intersection(*(v['fatti'] for v in voci))
        coperti = set.intersection(*(v['fatti'] | v['iscritti'] for v in voci))
        voci.append({'id': ID_PERCORSO, 'nome': 'Percorso completo',
                     'nome_breve': 'Percorso completo', 'percorso': True,
                     'fatti': completi, 'iscritti': coperti - completi, 'parziali': set()})
    return voci


def conteggi(voci, utenti, ruoli):
    per_ruolo = [(r, {u.id for u in utenti if u.ruolo and u.ruolo.nome == r}) for r in ruoli]
    tutti = set().union(*(ids for _, ids in per_ruolo))

    def blocco(voce, ids):
        return {'completato': len(voce['fatti'] & ids), 'in_procinto': len(voce['iscritti'] & ids),
                'parziali': len(voce['parziali'] & ids), 'totale': len(ids)}

    risultato = []
    for voce in voci:
        totali = blocco(voce, tutti)
        risultato.append({
            'nome': voce['nome'], 'nome_breve': voce['nome_breve'], 'percorso': voce['percorso'], **totali,
            'percentuale': round(100 * totali['completato'] / totali['totale']) if totali['totale'] else 0,
            'ruoli': [{'nome': r, 'etichetta': ETICHETTE_BREVI.get(r, r), **blocco(voce, ids)} for r, ids in per_ruolo],
        })
    return risultato


class CompletamentoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        info, programma = programma_richiesto(request)
        store = get_object_or_404(Store, pk=store_id, is_active=True)
        utenti = utenti_target(programma, store=store)
        attivita, percorso = struttura_programma(programma)
        voci = voci_programma(attivita, [u.id for u in utenti], percorso)
        return Response({'programma': info, 'store': {'id': store.id, 'nome': store.nome},
                         'corsi': conteggi(voci, utenti, programma['ruoli'])})


class CompletamentoZoomView(APIView):
    """ZOOM: per ogni persona del target del negozio, quali aule ha svolto e quali le
    mancano. Lo store vede solo il proprio negozio."""
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from participants.models import Iscrizione
        info, programma = programma_richiesto(request)
        if request.user.livello_accesso == 'store' and request.user.store_id != store_id:
            return Response({'detail': 'Non autorizzato.'}, status=403)
        store = get_object_or_404(Store, pk=store_id, is_active=True)
        utenti = utenti_target(programma, store=store)
        attivita, percorso = struttura_programma(programma)
        voci = voci_programma(attivita, [u.id for u in utenti], percorso)
        # Iscritti a un'aula non ancora svolta: data dell'aula, mostrata al posto del trattino.
        date_iscrizione = {}
        for user_id, att_id, data in Iscrizione.objects.filter(
            evento__attivita__in=attivita, stato='iscritto', user__in=utenti,
        ).order_by('evento__data').values_list('user_id', 'evento__attivita_id', 'evento__data'):
            date_iscrizione.setdefault((user_id, att_id), data)
        return Response({
            'programma': info,
            'store': {'id': store.id, 'nome': store.nome},
            'corsi': [{'id': v['id'], 'nome_breve': v['nome_breve'], 'percorso': v['percorso']} for v in voci],
            'utenti': [{
                'id': u.id, 'cognome': u.cognome, 'nome': u.nome, 'ruolo': u.ruolo.nome,
                'fatti': [v['id'] for v in voci if u.id in v['fatti']],
                'parziali': [v['id'] for v in voci if u.id in v['parziali']],
                'iscritti': {v['id']: date_iscrizione[(u.id, v['id'])] for v in voci
                             if (u.id, v['id']) in date_iscrizione and u.id not in v['fatti']},
            } for u in utenti],
        })


class CompletamentoItaliaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        info, programma = programma_richiesto(request)
        utenti = utenti_target(programma)
        attivita, percorso = struttura_programma(programma)
        voci = voci_programma(attivita, [u.id for u in utenti], percorso)
        aree = []
        for area in Area.objects.prefetch_related('stores').all():
            negozi = set(area.stores.values_list('id', flat=True))
            aree.append({
                'numero': area.numero,
                'area_manager_retail': area.area_manager_retail,
                'area_bp': area.area_bp,
                'corsi': conteggi(voci, [u for u in utenti if u.store_id in negozi], programma['ruoli']),
            })
        return Response({'programma': info, 'italia': conteggi(voci, utenti, programma['ruoli']), 'aree': aree})


class CompletamentoAreaDetailView(APIView):
    permission_classes = [IsAdminOrHOOrAreaEHS]

    def get(self, request, numero):
        info, programma = programma_richiesto(request)
        area = get_object_or_404(Area.objects.prefetch_related('stores'), numero=numero)
        negozi = list(area.stores.filter(is_active=True))
        utenti = utenti_target(programma, store__in=negozi)
        attivita, percorso = struttura_programma(programma)
        voci = voci_programma(attivita, [u.id for u in utenti], percorso)

        stores_result = []
        for store in negozi:
            corsi = conteggi(voci, [u for u in utenti if u.store_id == store.id], programma['ruoli'])
            stores_result.append({
                'id': store.id, 'nome': store.nome, 'codice_store': store.codice_store, 'corsi': corsi,
                # Persone ancora da formare, aula per aula (la voce "percorso" non si somma).
                'total_untrained': sum(c['totale'] - c['completato'] for c in corsi if not c['percorso']),
            })
        if stores_result:
            massimo = max(s['total_untrained'] for s in stores_result)
            for s in stores_result:
                s['alert'] = s['total_untrained'] == massimo and massimo > 0

        return Response({
            'programma': info,
            'numero': area.numero,
            'area_manager_retail': area.area_manager_retail,
            'area_bp': area.area_bp,
            'stores': stores_result,
        })
