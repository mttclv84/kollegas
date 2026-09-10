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


def crea_richiesta(store_user, corso, negozio, contatto_negozio_nome, contatto_negozio_telefono, note=''):
    if store_user.livello_accesso not in RUOLI_STORE:
        raise TransizioneNonValida('Solo uno Store (o Admin/HO) può creare una richiesta EHS.')

    from .models import EHSSessione

    with transaction.atomic():
        sessione = EHSSessione.objects.create(
            corso=corso, negozio=negozio, creata_da=store_user,
            durata_ore=corso.durata_ore,
            contatto_negozio_nome=contatto_negozio_nome,
            contatto_negozio_telefono=contatto_negozio_telefono,
            note=note,
        )
        _log(sessione, '', sessione.stato, store_user, 'Richiesta creata dallo store')
    return sessione


def proponi_data(sessione, fornitore, data_proposta):
    if fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può proporre una data.')
    if sessione.stato not in ('RICHIESTA_INVIATA', 'DATA_CONTROPROPOSTA'):
        raise TransizioneNonValida(f'Non è possibile proporre una data dallo stato {sessione.stato}.')

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.data_proposta = data_proposta
        sessione.fornitore = fornitore
        sessione.stato = 'DATA_PROPOSTA'
        sessione.save()
        _log(sessione, stato_precedente, sessione.stato, fornitore, f'Data proposta: {data_proposta}')
    return sessione


def rispondi_data(sessione, store_user, accetta, nuova_data=None):
    """Lo store accetta la data proposta (in attesa che il fornitore confermi con `conferma`)
    oppure contro-propone una nuova data (torna al fornitore per una nuova proposta)."""
    if store_user.livello_accesso not in RUOLI_STORE:
        raise TransizioneNonValida('Solo lo Store (o Admin/HO) può rispondere alla data proposta.')
    if sessione.stato != 'DATA_PROPOSTA':
        raise TransizioneNonValida(f'Non è possibile rispondere a una data dallo stato {sessione.stato}.')

    with transaction.atomic():
        stato_precedente = sessione.stato
        if accetta:
            _log(sessione, stato_precedente, sessione.stato, store_user,
                 'Store ha accettato la data proposta, in attesa di conferma del fornitore')
        else:
            if not nuova_data:
                raise TransizioneNonValida('Serve una nuova data per la contro-proposta.')
            sessione.data_proposta = nuova_data
            sessione.stato = 'DATA_CONTROPROPOSTA'
            sessione.save()
            _log(sessione, stato_precedente, sessione.stato, store_user, f'Contro-proposta: {nuova_data}')
    return sessione


def _crea_evento_calendario(sessione):
    """Crea l'evento 'leggero' sul calendario principale al raggiungimento di CONFERMATA (§5).
    Titolo fisso 'EHS' (nessun dettaglio su fornitore/docente/corso visibile fuori da EHS):
    riusa un'Attività Catalogo e un Host fissi, dedicati, così da non toccare i vincoli
    esistenti su Evento.attivita/Evento.host (entrambi FK obbligatorie, vedi ricognizione step 1)."""
    from datetime import timedelta

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


def conferma(sessione, fornitore, docente_nome, docente_telefono):
    """Conferma definitiva del fornitore: fissa la data e assegna il docente.
    Valida sia dopo un'accettazione diretta (DATA_PROPOSTA) sia dopo una contro-proposta
    accettata dal fornitore (DATA_CONTROPROPOSTA) — coerente con §3, dove entrambi gli
    archi confluiscono in CONFERMATA. Alla conferma, sincronizza il calendario principale (§5)."""
    if fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può confermare la sessione.')
    if sessione.stato not in ('DATA_PROPOSTA', 'DATA_CONTROPROPOSTA'):
        raise TransizioneNonValida(f'Non è possibile confermare dallo stato {sessione.stato}.')
    if not sessione.data_proposta:
        raise TransizioneNonValida('Nessuna data proposta da confermare.')

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.data_confermata = sessione.data_proposta
        sessione.docente_nome = docente_nome
        sessione.docente_telefono = docente_telefono
        sessione.fornitore = fornitore
        sessione.stato = 'CONFERMATA'
        sessione.save()
        _crea_evento_calendario(sessione)
        _log(sessione, stato_precedente, sessione.stato, fornitore,
             f'Sessione confermata — docente: {docente_nome}')
    return sessione


def carica_registro(sessione, fornitore, file):
    if fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può caricare il registro.')
    if sessione.stato != 'CONFERMATA':
        raise TransizioneNonValida(f'Non è possibile caricare il registro dallo stato {sessione.stato}.')

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.registro_file = file
        sessione.stato = 'REGISTRO_INVIATO'
        sessione.save()
        _log(sessione, stato_precedente, sessione.stato, fornitore, 'Registro inviato al negozio')
    return sessione


def carica_registro_compilato(sessione, fornitore, file):
    """Il registro compilato pre-aula è caricato dal fornitore esterno (non dallo store) —
    il suo arrivo segna il passaggio a SVOLTA (vedi descrizione stato in §3)."""
    if fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può caricare il registro compilato.')
    if sessione.stato != 'REGISTRO_INVIATO':
        raise TransizioneNonValida(f'Non è possibile caricare il registro compilato dallo stato {sessione.stato}.')

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.registro_compilato_file = file
        sessione.stato = 'SVOLTA'
        sessione.save()
        _log(sessione, stato_precedente, sessione.stato, fornitore, 'Registro compilato ricevuto: sessione svolta')
    return sessione


def invia_email_attestato(attestato_file, partecipante):
    """Invio di sistema (non un'azione manuale del fornitore, §5bis punto 3).
    Il destinatario di default è hardcoded come da spec; sovrascrivibile via
    settings.EHS_EMAIL_ATTESTATI una volta configurato l'SMTP reale."""
    destinatario = getattr(settings, 'EHS_EMAIL_ATTESTATI', 'vspampinato@primark.it')
    try:
        email = EmailMessage(
            subject=f'Attestato EHS — {partecipante.sessione.corso.nome} — {partecipante.utente.nome_completo}',
            body=(
                f'Attestato di partecipazione al corso {partecipante.sessione.corso.nome} '
                f'per {partecipante.utente.nome_completo} ({partecipante.sessione.negozio}).'
            ),
            to=[destinatario],
        )
        attestato_file.open('rb')
        try:
            email.attach(attestato_file.name.rsplit('/', 1)[-1], attestato_file.read())
        finally:
            attestato_file.close()
        email.send(fail_silently=False)
    except Exception:
        # SMTP non ancora configurato (vedi ricognizione step 1): l'invio è un
        # side-effect di notifica e non deve far fallire la chiusura aula.
        logger.exception('Invio email attestato fallito per partecipante %s', partecipante.id)


def chiudi_aula(sessione, presenze, attestati, assenze_motivo, utente_fornitore):
    """Azione unica del fornitore a fine sessione (§5bis): conferma presenze, carica
    attestati, invia email di sistema, chiude formalmente e calcola le scadenze.
    presenze: {partecipante_id: bool} — attestati: {partecipante_id: File} —
    assenze_motivo: {partecipante_id: str}."""
    if utente_fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida("Solo il Fornitore (o Admin/HO) può chiudere l'aula.")
    if sessione.stato != 'SVOLTA':
        raise TransizioneNonValida(f"Non è possibile chiudere l'aula dallo stato {sessione.stato}.")

    with transaction.atomic():
        now = timezone.now()
        sessione.data_chiusura = now
        sessione.chiusa_da = utente_fornitore
        sessione.stato = 'COMPLETATA'
        sessione.save()

        for partecipante in sessione.partecipanti.all():
            partecipante.presente = bool(presenze.get(partecipante.id, False))
            if partecipante.presente:
                partecipante.completato = True
                partecipante.completato_il = now
                partecipante.assente_motivo = ''
                pdf = attestati.get(partecipante.id)
                if pdf:
                    partecipante.attestato_file = pdf
                    partecipante.attestato_caricato_il = now
                if sessione.corso.scadenza_giorni:
                    partecipante.scadenza_formazione = now.date() + timedelta(days=sessione.corso.scadenza_giorni)
            else:
                partecipante.completato = False
                partecipante.assente_motivo = assenze_motivo.get(partecipante.id, '')
            partecipante.save()

            if partecipante.presente and partecipante.attestato_file:
                invia_email_attestato(partecipante.attestato_file, partecipante)

        _log(sessione, 'SVOLTA', 'COMPLETATA', utente_fornitore,
             'Chiusura aula: presenze confermate, attestati inviati')
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
    senza step di conferma intermedi. Raggiungibile da qualunque stato precedente a SVOLTA."""
    if sessione.stato in ('SVOLTA', 'COMPLETATA', 'ANNULLATA'):
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
