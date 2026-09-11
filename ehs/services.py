import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from .models import EHSSessioneLog

logger = logging.getLogger(__name__)

RUOLI_FORNITORE = ('fornitore', 'admin', 'ho')
RUOLI_STORE = ('store', 'admin', 'ho')


class TransizioneNonValida(Exception):
    """Azione richiesta da uno stato o un ruolo non ammessi dalla macchina a stati EHS."""


def _log(sessione, stato_precedente, stato_nuovo, utente, nota=''):
    EHSSessioneLog.objects.create(
        sessione=sessione, stato_precedente=stato_precedente, stato_nuovo=stato_nuovo,
        utente=utente, nota=nota,
    )


def _valida_mezzora(dt, campo='data'):
    """Gli orari EHS sono sempre a 00 o 30 minuti, per calcolare ore intere o mezz'ore."""
    if dt is not None and dt.minute not in (0, 30):
        raise TransizioneNonValida(f'{campo}: l\'orario deve essere in punto o e mezza (es. 14:00 o 14:30).')


def crea_richiesta(store_user, corso, negozio, contatto_negozio_nome, contatto_negozio_telefono,
                    note='', fornitore=None, partecipanti_previsti=None, data_suggerita_store=None):
    if store_user.livello_accesso not in RUOLI_STORE:
        raise TransizioneNonValida('Solo uno Store (o Admin/HO) può creare una richiesta EHS.')
    if fornitore is not None and fornitore.livello_accesso != 'fornitore':
        raise TransizioneNonValida('Il fornitore selezionato non è un utente di livello Fornitore EHS.')
    _valida_mezzora(data_suggerita_store, 'Data suggerita')

    from .models import EHSSessione

    with transaction.atomic():
        sessione = EHSSessione.objects.create(
            corso=corso, negozio=negozio, creata_da=store_user, fornitore=fornitore,
            durata_ore=corso.durata_ore,
            contatto_negozio_nome=contatto_negozio_nome,
            contatto_negozio_telefono=contatto_negozio_telefono,
            note=note,
            partecipanti_previsti=partecipanti_previsti,
            data_suggerita_store=data_suggerita_store,
        )
        nota = 'Richiesta creata dallo store'
        if fornitore:
            nota += f' — assegnata a {fornitore.fornitore_ragione_sociale or fornitore.nome_completo}'
        _log(sessione, '', sessione.stato, store_user, nota)
    return sessione


def proponi_data(sessione, fornitore, data_proposta, docente_nome, docente_telefono):
    """Il fornitore propone data e docente insieme, sia alla prima proposta sia dopo
    aver rifiutato una contro-proposta (§3: il ciclo può ripetersi finché non si arriva
    a CONFERMATA tramite l'accettazione di una delle due parti)."""
    if fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può proporre una data.')
    if sessione.stato not in ('RICHIESTA_INVIATA', 'DATA_CONTROPROPOSTA'):
        raise TransizioneNonValida(f'Non è possibile proporre una data dallo stato {sessione.stato}.')
    if not docente_nome or not docente_telefono:
        raise TransizioneNonValida('Nome e telefono del docente sono obbligatori.')
    _valida_mezzora(data_proposta, 'Data proposta')

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.data_proposta = data_proposta
        sessione.fornitore = fornitore
        sessione.docente_nome = docente_nome
        sessione.docente_telefono = docente_telefono
        sessione.stato = 'DATA_PROPOSTA'
        sessione.save()
        _log(sessione, stato_precedente, sessione.stato, fornitore,
             f'Data proposta: {data_proposta} — docente: {docente_nome}')
    return sessione


def _crea_evento_calendario(sessione):
    """Crea l'evento 'leggero' sul calendario principale al raggiungimento di CONFERMATA (§5).
    Titolo fisso 'EHS' (nessun dettaglio su fornitore/docente/corso visibile fuori da EHS):
    riusa un'Attività Catalogo e un Host fissi, dedicati, così da non toccare i vincoli
    esistenti su Evento.attivita/Evento.host (entrambi FK obbligatorie, vedi ricognizione step 1)."""
    from events.models import AttivitaCatalogo, Evento, Host, TipologiaAttivita

    host, _ = Host.objects.get_or_create(
        descrizione='Fornitore Esterno EHS', defaults={'posizione': 'esterno'}
    )
    attivita, _ = AttivitaCatalogo.objects.get_or_create(
        nome='EHS', defaults={'tipologia': TipologiaAttivita.EHS}
    )

    ora_inizio = sessione.data_confermata.time()
    ora_fine = (sessione.data_confermata + timedelta(hours=float(sessione.durata_ore))).time()

    evento = Evento.objects.create(
        data=sessione.data_confermata.date(),
        ora_inizio=ora_inizio,
        ora_fine=ora_fine,
        attivita=attivita,
        host=host,
        location_store=sessione.negozio,
        created_by=sessione.fornitore,
        is_ehs=True,
        ehs_luogo=sessione.negozio.indirizzo or sessione.negozio.nome,
    )
    sessione.calendario_evento = evento
    sessione.save(update_fields=['calendario_evento'])
    return evento


def _conferma_sessione(sessione, utente, nota):
    """Transizione condivisa verso CONFERMATA: fissa data_confermata, sincronizza il
    calendario e notifica il fornitore (popup sulla sua home) — usata sia quando lo
    store accetta la proposta, sia quando il fornitore accetta una contro-proposta."""
    from .models import EHSNotificaSessioneConfermata

    stato_precedente = sessione.stato
    sessione.data_confermata = sessione.data_proposta
    sessione.stato = 'CONFERMATA'
    sessione.save()
    _crea_evento_calendario(sessione)
    _log(sessione, stato_precedente, sessione.stato, utente, nota)
    if sessione.fornitore:
        EHSNotificaSessioneConfermata.objects.create(sessione=sessione, fornitore=sessione.fornitore)


def rispondi_data(sessione, store_user, accetta, nuova_data=None):
    """Lo store accetta la data proposta (la sessione diventa CONFERMATA subito,
    l'aula appare sul calendario EHS e il fornitore riceve un popup di notifica)
    oppure contro-propone una nuova data (torna al fornitore per una nuova proposta)."""
    if store_user.livello_accesso not in RUOLI_STORE:
        raise TransizioneNonValida('Solo lo Store (o Admin/HO) può rispondere alla data proposta.')
    if sessione.stato != 'DATA_PROPOSTA':
        raise TransizioneNonValida(f'Non è possibile rispondere a una data dallo stato {sessione.stato}.')

    with transaction.atomic():
        if accetta:
            _conferma_sessione(sessione, store_user, 'Store ha accettato la data proposta: sessione confermata')
        else:
            if not nuova_data:
                raise TransizioneNonValida('Serve una nuova data per la contro-proposta.')
            _valida_mezzora(nuova_data, 'Nuova data')
            stato_precedente = sessione.stato
            sessione.data_proposta = nuova_data
            sessione.stato = 'DATA_CONTROPROPOSTA'
            sessione.save()
            _log(sessione, stato_precedente, sessione.stato, store_user, f'Contro-proposta: {nuova_data}')
    return sessione


def accetta_controproposta(sessione, fornitore):
    """Il fornitore accetta la data contro-proposta dallo store così com'è: la sessione
    diventa CONFERMATA (stessa transizione condivisa di rispondi_data(accetta=True))."""
    if fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può accettare la contro-proposta.')
    if sessione.stato != 'DATA_CONTROPROPOSTA':
        raise TransizioneNonValida(f'Non è possibile accettare una contro-proposta dallo stato {sessione.stato}.')

    with transaction.atomic():
        _conferma_sessione(sessione, fornitore, 'Fornitore ha accettato la contro-proposta: sessione confermata')
    return sessione


def invia_email_registro(sessione):
    """Invio di sistema del registro compilato al momento della chiusura aula:
    non è un'azione manuale del fornitore, lui carica solo in app."""
    destinatario = getattr(settings, 'EHS_EMAIL_ATTESTATI', 'vspampinato@primark.it')
    try:
        email = EmailMessage(
            subject=f'Registro EHS — {sessione.corso.nome} — {sessione.negozio}',
            body=(
                f'Registro compilato del corso {sessione.corso.nome} presso {sessione.negozio}, '
                f'sessione del {sessione.data_confermata}.'
            ),
            to=[destinatario],
        )
        sessione.registro_compilato_file.open('rb')
        try:
            email.attach(sessione.registro_compilato_file.name.rsplit('/', 1)[-1], sessione.registro_compilato_file.read())
        finally:
            sessione.registro_compilato_file.close()
        email.send(fail_silently=False)
    except Exception:
        # SMTP non ancora configurato (vedi ricognizione step 1): l'invio è un
        # side-effect di notifica e non deve far fallire la chiusura aula.
        logger.exception('Invio email registro fallito per sessione %s', sessione.id)


def chiudi_aula(sessione, presenze, registro_compilato_file, utente_fornitore, assenze_motivo=None):
    """Azione unica del fornitore a fine sessione: conferma presenze, carica il
    registro compilato (un solo documento per l'intera sessione, consultabile poi
    dal negozio nella sezione Registri), invia email di sistema, chiude formalmente
    e calcola le scadenze. presenze: {partecipante_id: bool}."""
    assenze_motivo = assenze_motivo or {}
    if utente_fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida("Solo il Fornitore (o Admin/HO) può chiudere l'aula.")
    if sessione.stato != 'CONFERMATA':
        raise TransizioneNonValida(f"Non è possibile chiudere l'aula dallo stato {sessione.stato}.")
    if not registro_compilato_file:
        raise TransizioneNonValida('Il registro compilato è obbligatorio per chiudere l\'aula.')

    with transaction.atomic():
        now = timezone.now()
        sessione.data_chiusura = now
        sessione.chiusa_da = utente_fornitore
        sessione.registro_compilato_file = registro_compilato_file
        sessione.stato = 'COMPLETATA'
        sessione.save()

        for partecipante in sessione.partecipanti.all():
            partecipante.presente = bool(presenze.get(partecipante.id, False))
            if partecipante.presente:
                partecipante.completato = True
                partecipante.completato_il = now
                partecipante.assente_motivo = ''
                if sessione.corso.scadenza_giorni:
                    partecipante.scadenza_formazione = now.date() + timedelta(days=sessione.corso.scadenza_giorni)
            else:
                partecipante.completato = False
                partecipante.assente_motivo = assenze_motivo.get(partecipante.id, '')
            partecipante.save()

        invia_email_registro(sessione)

        _log(sessione, 'CONFERMATA', 'COMPLETATA', utente_fornitore,
             'Chiusura aula: presenze confermate, registro compilato caricato e inviato')
    return sessione


def genera_notifiche_scadenza():
    """Job giornaliero (§8bis): genera una notifica per il negozio dove l'utente è
    attualmente in forza (`User.store`, non necessariamente il negozio dove ha fatto
    il corso — es. trasferimenti) quando mancano 30 giorni o meno alla scadenza.
    Usa `<=` invece dell'uguaglianza esatta della spec per coprire eventuali gap se il
    job salta un giorno (nota esplicita in §8bis); l'idempotenza è garantita dal vincolo
    OneToOne su `partecipante`, quindi eseguire il job più volte è sempre sicuro.
    Ritorna il numero di notifiche create."""
    from .models import EHSNotificaScadenza, EHSPartecipante

    soglia = timezone.now().date() + timedelta(days=30)
    partecipanti = EHSPartecipante.objects.filter(
        scadenza_formazione__isnull=False,
        scadenza_formazione__lte=soglia,
        completato=True,
    ).select_related('utente', 'sessione__corso')

    creati = 0
    for p in partecipanti:
        negozio_attuale = p.utente.store
        if not negozio_attuale:
            continue
        _, created = EHSNotificaScadenza.objects.get_or_create(
            partecipante=p, defaults={'negozio_destinatario': negozio_attuale}
        )
        if created:
            creati += 1
    return creati


def annulla_sessione(sessione, utente):
    """Cascata definita in §5: rimuove evento di calendario e iscrizioni collegate,
    senza step di conferma intermedi. Raggiungibile da qualunque stato precedente a COMPLETATA."""
    if sessione.stato in ('COMPLETATA', 'ANNULLATA'):
        raise TransizioneNonValida(f'Non è possibile annullare una sessione nello stato {sessione.stato}.')

    # Import locale: evita una dipendenza a livello di modulo tra le app ehs e participants.
    from participants.models import Iscrizione

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.stato = 'ANNULLATA'
        sessione.save()

        if sessione.calendario_evento:
            Iscrizione.objects.filter(evento=sessione.calendario_evento).delete()
            sessione.calendario_evento.delete()

        sessione.partecipanti.all().delete()

        _log(sessione, stato_precedente, 'ANNULLATA', utente,
             'Sessione annullata: evento e iscrizioni rimossi automaticamente')
    return sessione
