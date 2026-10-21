import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import EHSSessioneLog

logger = logging.getLogger(__name__)

RUOLI_FORNITORE = ('fornitore', 'admin', 'admin_ehs', 'ho')
RUOLI_STORE = ('store', 'admin', 'admin_ehs', 'ho')
RUOLI_ADMIN = ('admin', 'admin_ehs', 'ho')
# Solo l'EHS Admin (e l'Admin generale) decide sulle richieste eccezionali.
RUOLI_APPROVAZIONE_ECCEZIONI = ('admin', 'admin_ehs')

# Store e fornitore possono cancellare iscritti o l'intera formazione confermata solo
# fino a questo numero di giorni prima della data; dopo resta possibile solo all'Admin.
GIORNI_LIMITE_CANCELLAZIONE = 7
# Finestra del pannello "Alert scadenze" e del popup di scadenza per lo store.
GIORNI_ALERT_SCADENZA = 45


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


def _nome_fornitore(fornitore):
    return fornitore.fornitore_ragione_sociale or fornitore.nome_completo


# --- Email -------------------------------------------------------------------

def _url_app():
    return getattr(settings, 'FRONTEND_URL', '').rstrip('/')


def _invia_email(destinatari, oggetto, corpo, allegati=None):
    """Alert email di sistema: invito a controllare la sezione EHS sull'app. Inviata
    dopo il commit della transazione e mai bloccante — se l'SMTP non è configurato o
    fallisce, l'azione in app resta valida e l'errore viene solo loggato.
    Nessun invio finché EHS_EMAIL_ATTIVE è disattivato (vedi settings)."""
    if not getattr(settings, 'EHS_EMAIL_ATTIVE', False):
        return
    destinatari = [d for d in dict.fromkeys(destinatari or []) if d]
    if not destinatari:
        return
    url = _url_app()
    if url:
        corpo = f'{corpo}\n\nAccedi a Kollegas per i dettagli: {url}/ehs'
    corpo = f'{corpo}\n\n— Messaggio automatico Kollegas EHS, non rispondere a questa email.'

    def _send():
        try:
            email = EmailMessage(subject=f'[Kollegas EHS] {oggetto}', body=corpo, to=destinatari)
            for nome, contenuto in allegati or []:
                email.attach(nome, contenuto)
            email.send(fail_silently=False)
        except Exception:
            logger.exception('Invio email EHS fallito (%s) a %s', oggetto, destinatari)

    transaction.on_commit(_send)


def _email_fornitore(sessione):
    return [sessione.fornitore.email] if sessione.fornitore_id and sessione.fornitore.email else []


def _email_store(sessione):
    return [sessione.negozio.email_store] if sessione.negozio.email_store else []


def _email_admin_ehs():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return list(User.objects.filter(livello_accesso='admin_ehs', is_active=True)
                .exclude(email='').values_list('email', flat=True))


def _descrizione(sessione):
    return f'{sessione.corso.nome} — {sessione.negozio}'


def _fmt(dt):
    return timezone.localtime(dt).strftime('%d/%m/%Y %H:%M') if dt else '—'


# --- Perimetro fornitori (offerte corso) --------------------------------------

def fornitori_idonei(corso, negozio):
    """Fornitori attivi che erogano il corso per questo negozio (offerta valida per
    tutti i negozi o che include esplicitamente il negozio)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.filter(
        Q(ehs_offerte__tutti_negozi=True) | Q(ehs_offerte__negozi=negozio),
        ehs_offerte__corso=corso, livello_accesso='fornitore', is_active=True,
    ).distinct().order_by('fornitore_ragione_sociale')


def fornitori_eccezionali(corso, negozio):
    """Fornitori attivi che erogano il corso ma NON per questo negozio: richiedibili
    solo con una richiesta eccezionale da approvare dall'EHS Admin."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    idonei = fornitori_idonei(corso, negozio).values_list('pk', flat=True)
    return (User.objects.filter(ehs_offerte__corso=corso, livello_accesso='fornitore', is_active=True)
            .exclude(pk__in=list(idonei)).distinct().order_by('fornitore_ragione_sociale'))


# --- Creazione richiesta e assegnazione fornitore ----------------------------

def crea_richiesta(store_user, corso, negozio, contatto_negozio_nome, contatto_negozio_telefono,
                    note='', fornitore=None, partecipanti_previsti=None, data_suggerita_store=None,
                    modalita='PRESENZA', eccezionale=False, motivazione_eccezione=''):
    if store_user.livello_accesso not in RUOLI_STORE:
        raise TransizioneNonValida('Solo uno Store (o Admin/HO) può creare una richiesta EHS.')
    if modalita not in ('PRESENZA', 'ONLINE'):
        raise TransizioneNonValida('Modalità non valida.')
    _valida_mezzora(data_suggerita_store, 'Data suggerita')

    idonei = list(fornitori_idonei(corso, negozio))
    if eccezionale:
        if fornitore is None:
            raise TransizioneNonValida('Seleziona il fornitore per la richiesta eccezionale.')
        if not motivazione_eccezione.strip():
            raise TransizioneNonValida('La motivazione è obbligatoria per una richiesta eccezionale.')
        if not fornitori_eccezionali(corso, negozio).filter(pk=fornitore.pk).exists():
            raise TransizioneNonValida('Il fornitore selezionato non è richiedibile in via eccezionale per questo corso.')
    else:
        if fornitore is None and len(idonei) == 1:
            fornitore = idonei[0]
        if fornitore is None:
            if not idonei:
                raise TransizioneNonValida(
                    'Nessun fornitore disponibile per questo corso nel tuo negozio: invia una richiesta eccezionale.'
                )
            raise TransizioneNonValida('Seleziona il fornitore.')
        if fornitore not in idonei:
            raise TransizioneNonValida('Il fornitore selezionato non eroga questo corso per il negozio.')

    from .models import EHSSessione

    with transaction.atomic():
        sessione = EHSSessione.objects.create(
            corso=corso, negozio=negozio, creata_da=store_user,
            fornitore=None if eccezionale else fornitore,
            fornitore_richiesto=fornitore if eccezionale else None,
            eccezionale=eccezionale,
            motivazione_eccezione=motivazione_eccezione.strip() if eccezionale else '',
            stato='IN_APPROVAZIONE' if eccezionale else 'RICHIESTA_INVIATA',
            modalita=modalita,
            durata_ore=corso.durata_ore,
            contatto_negozio_nome=contatto_negozio_nome,
            contatto_negozio_telefono=contatto_negozio_telefono,
            note=note,
            partecipanti_previsti=partecipanti_previsti,
            data_suggerita_store=data_suggerita_store,
        )
        if eccezionale:
            _log(sessione, '', sessione.stato, store_user,
                 f'Richiesta eccezionale per {_nome_fornitore(fornitore)}: {sessione.motivazione_eccezione}')
            _email_richiesta_eccezionale(sessione)
        else:
            _log(sessione, '', sessione.stato, store_user,
                 f'Richiesta creata dallo store — assegnata a {_nome_fornitore(fornitore)}')
            _notifica_nuova_richiesta(sessione, fornitore)
    return sessione


def _notifica_nuova_richiesta(sessione, fornitore):
    from .models import EHSNotificaNuovaRichiesta
    EHSNotificaNuovaRichiesta.objects.create(sessione=sessione, fornitore=fornitore)
    if fornitore.email:
        modalita = 'online' if sessione.modalita == 'ONLINE' else 'in presenza'
        corpo = (f'Hai ricevuto una nuova richiesta di formazione EHS.\n\n'
                 f'Corso: {sessione.corso.nome}\nNegozio: {sessione.negozio}\nModalità: {modalita}\n'
                 f'Partecipanti previsti: {sessione.partecipanti_previsti or "—"}\n'
                 f'Data suggerita dallo store: {_fmt(sessione.data_suggerita_store)}\n\n'
                 f'Accedi all\'app per proporre una data o segnalare la tua non disponibilità.')
        _invia_email([fornitore.email], f'Nuova richiesta: {_descrizione(sessione)}', corpo)


def _email_richiesta_eccezionale(sessione):
    corpo = (f'Lo store {sessione.negozio} ha inviato una richiesta eccezionale da approvare.\n\n'
             f'Corso: {sessione.corso.nome}\n'
             f'Fornitore richiesto: {_nome_fornitore(sessione.fornitore_richiesto)}\n'
             f'Motivazione: {sessione.motivazione_eccezione}')
    _invia_email(_email_admin_ehs(), f'Richiesta eccezionale da approvare: {_descrizione(sessione)}', corpo)


def assegna_fornitore(sessione, utente, fornitore):
    """Assegna un fornitore idoneo a una richiesta ancora senza fornitore oppure
    dopo che il fornitore precedente si è dichiarato non disponibile."""
    if utente.livello_accesso not in RUOLI_STORE:
        raise TransizioneNonValida('Solo lo Store (o Admin/HO) può assegnare un fornitore.')
    if not (sessione.stato == 'NON_DISPONIBILE' or (sessione.stato == 'RICHIESTA_INVIATA' and not sessione.fornitore_id)):
        raise TransizioneNonValida(f'Non è possibile assegnare un fornitore dallo stato {sessione.stato}.')
    if fornitore.livello_accesso != 'fornitore':
        raise TransizioneNonValida('Il fornitore selezionato non è un utente di livello Fornitore EHS.')
    # Admin/HO possono forzare qualunque fornitore; lo store resta nel proprio perimetro
    # (fuori perimetro deve passare dalla richiesta eccezionale).
    if utente.livello_accesso == 'store' and not fornitori_idonei(sessione.corso, sessione.negozio).filter(pk=fornitore.pk).exists():
        raise TransizioneNonValida('Il fornitore non eroga questo corso per il tuo negozio: usa la richiesta eccezionale.')

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.fornitore = fornitore
        sessione.stato = 'RICHIESTA_INVIATA'
        sessione.data_proposta = None
        sessione.docente_nome = None
        sessione.docente_telefono = None
        sessione.save()
        _notifica_nuova_richiesta(sessione, fornitore)
        _log(sessione, stato_precedente, sessione.stato, utente,
             f'Fornitore assegnato: {_nome_fornitore(fornitore)}')
    return sessione


def dichiara_non_disponibile(sessione, fornitore, motivo=''):
    """Il fornitore segnala che non può erogare la formazione: lo store potrà
    assegnare un altro fornitore idoneo o inviare una richiesta eccezionale."""
    if fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può dichiararsi non disponibile.')
    if sessione.stato not in ('RICHIESTA_INVIATA', 'DATA_CONTROPROPOSTA') or not sessione.fornitore_id:
        raise TransizioneNonValida(f'Non è possibile dichiarare non disponibilità dallo stato {sessione.stato}.')

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.stato = 'NON_DISPONIBILE'
        sessione.save(update_fields=['stato', 'aggiornata_il'])
        nota = f'{_nome_fornitore(sessione.fornitore)} non disponibile'
        if motivo:
            nota += f': {motivo}'
        _log(sessione, stato_precedente, sessione.stato, fornitore, nota)
        _invia_email(_email_store(sessione), f'Fornitore non disponibile: {_descrizione(sessione)}',
                     f'{nota}.\n\nPuoi assegnare la richiesta a un altro fornitore oppure inviare una '
                     f'richiesta eccezionale a un fornitore esterno alla tua rete.')
    return sessione


def richiedi_eccezione(sessione, utente, fornitore, motivazione):
    """Trasforma una richiesta senza fornitore disponibile in richiesta eccezionale
    verso un fornitore fuori perimetro, da approvare dall'EHS Admin."""
    if utente.livello_accesso not in RUOLI_STORE:
        raise TransizioneNonValida('Solo lo Store (o Admin/HO) può inviare una richiesta eccezionale.')
    if not (sessione.stato == 'NON_DISPONIBILE' or (sessione.stato == 'RICHIESTA_INVIATA' and not sessione.fornitore_id)):
        raise TransizioneNonValida(f'Non è possibile inviare una richiesta eccezionale dallo stato {sessione.stato}.')
    if not (motivazione or '').strip():
        raise TransizioneNonValida('La motivazione è obbligatoria per una richiesta eccezionale.')
    if not fornitori_eccezionali(sessione.corso, sessione.negozio).filter(pk=fornitore.pk).exists():
        raise TransizioneNonValida('Il fornitore selezionato non è richiedibile in via eccezionale per questo corso.')

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.eccezionale = True
        sessione.fornitore_richiesto = fornitore
        sessione.motivazione_eccezione = motivazione.strip()
        sessione.fornitore = None
        sessione.data_proposta = None
        sessione.stato = 'IN_APPROVAZIONE'
        sessione.save()
        _log(sessione, stato_precedente, sessione.stato, utente,
             f'Richiesta eccezionale per {_nome_fornitore(fornitore)}: {sessione.motivazione_eccezione}')
        _email_richiesta_eccezionale(sessione)
    return sessione


def decidi_eccezione(sessione, admin, approva, nota=''):
    """L'EHS Admin approva (la richiesta parte verso il fornitore richiesto) o
    rifiuta (stato terminale RIFIUTATA) una richiesta eccezionale."""
    if admin.livello_accesso not in RUOLI_APPROVAZIONE_ECCEZIONI:
        raise TransizioneNonValida('Solo l\'EHS Admin può approvare o rifiutare una richiesta eccezionale.')
    if sessione.stato != 'IN_APPROVAZIONE':
        raise TransizioneNonValida(f'La richiesta non è in approvazione (stato {sessione.stato}).')
    if not approva and not (nota or '').strip():
        raise TransizioneNonValida('Indica il motivo del rifiuto.')

    with transaction.atomic():
        if approva:
            fornitore = sessione.fornitore_richiesto
            if not fornitore or not fornitore.is_active:
                raise TransizioneNonValida('Il fornitore richiesto non è più attivo.')
            sessione.fornitore = fornitore
            sessione.stato = 'RICHIESTA_INVIATA'
            sessione.save()
            testo = f'Richiesta eccezionale approvata — inviata a {_nome_fornitore(fornitore)}'
            if nota:
                testo += f' ({nota})'
            _log(sessione, 'IN_APPROVAZIONE', sessione.stato, admin, testo)
            _notifica_nuova_richiesta(sessione, fornitore)
            _invia_email(_email_store(sessione), f'Richiesta eccezionale approvata: {_descrizione(sessione)}',
                         f'{testo}.')
        else:
            sessione.stato = 'RIFIUTATA'
            sessione.save(update_fields=['stato', 'aggiornata_il'])
            _log(sessione, 'IN_APPROVAZIONE', sessione.stato, admin, f'Richiesta eccezionale rifiutata: {nota}')
            _invia_email(_email_store(sessione), f'Richiesta eccezionale rifiutata: {_descrizione(sessione)}',
                         f'La richiesta eccezionale è stata rifiutata dall\'EHS Admin.\nMotivo: {nota}')
    return sessione


# --- Negoziazione data --------------------------------------------------------

def proponi_data(sessione, fornitore, data_proposta, docente_nome, docente_telefono, link_online=None):
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
    if link_online is not None:
        sessione.link_online = link_online
    if sessione.modalita == 'ONLINE' and not sessione.link_online:
        raise TransizioneNonValida('Per una formazione online il link alla call è obbligatorio.')

    with transaction.atomic():
        stato_precedente = sessione.stato
        sessione.data_proposta = data_proposta
        # Non sovrascrivere un fornitore già assegnato quando l'azione è compiuta da
        # Admin/HO per suo conto — altrimenti la sessione risulterebbe erroneamente
        # "posseduta" dall'Admin, invisibile poi al vero fornitore assegnato.
        if fornitore.livello_accesso == 'fornitore':
            sessione.fornitore = fornitore
        sessione.docente_nome = docente_nome
        sessione.docente_telefono = docente_telefono
        sessione.stato = 'DATA_PROPOSTA'
        sessione.save()
        _log(sessione, stato_precedente, sessione.stato, fornitore,
             f'Data proposta: {data_proposta} — docente: {docente_nome}')
        _notifica_data_proposta(sessione)
    return sessione


def _notifica_data_proposta(sessione):
    from .models import EHSNotificaDataProposta
    EHSNotificaDataProposta.objects.create(sessione=sessione, negozio_destinatario=sessione.negozio)
    _invia_email(_email_store(sessione), f'Data proposta: {_descrizione(sessione)}',
                 f'Il fornitore ha proposto il {_fmt(sessione.data_proposta)} '
                 f'(docente: {sessione.docente_nome}).\n\nAccedi all\'app per accettare o proporre un\'altra data.')


def _crea_evento_calendario(sessione):
    """Crea l'evento 'leggero' sul calendario principale al raggiungimento di CONFERMATA (§5).
    Riusa un Host fisso, dedicato, così da non toccare i vincoli esistenti su Evento.host
    (FK obbligatoria, vedi ricognizione step 1). L'Attività Catalogo è invece agganciata al
    nome dello specifico corso EHS (non più a una voce fissa 'EHS' generica): così Report e
    Stats, che raggruppano per attività, mostrano il dettaglio per singolo corso EHS."""
    from events.models import AttivitaCatalogo, Evento, Host, ModalitaPartecipazione, TipologiaAttivita

    host, _ = Host.objects.get_or_create(
        descrizione='Fornitore Esterno EHS', defaults={'posizione': 'esterno'}
    )
    attivita, _ = AttivitaCatalogo.objects.get_or_create(
        nome=sessione.corso.nome, defaults={'tipologia': TipologiaAttivita.EHS}
    )

    inizio = timezone.localtime(sessione.data_confermata)
    fine = inizio + timedelta(hours=float(sessione.durata_ore))
    online = sessione.modalita == 'ONLINE'

    evento = Evento.objects.create(
        data=inizio.date(),
        ora_inizio=inizio.time(),
        ora_fine=fine.time(),
        attivita=attivita,
        host=host,
        location_store=sessione.negozio,
        created_by=sessione.fornitore,
        modalita_partecipazione=ModalitaPartecipazione.ONLINE if online else ModalitaPartecipazione.PRESENZA,
        is_ehs=True,
        ehs_luogo='Online' if online else (sessione.negozio.indirizzo or sessione.negozio.nome),
    )
    sessione.calendario_evento = evento
    sessione.save(update_fields=['calendario_evento'])
    return evento


def _conferma_sessione(sessione, utente, nota, notifica_lato='fornitore'):
    """Transizione condivisa verso CONFERMATA: fissa data_confermata, sincronizza il
    calendario e notifica chi non ha compiuto l'azione (popup sulla sua home) — usata
    sia quando lo store accetta la proposta (notifica al fornitore), sia quando il
    fornitore accetta una contro-proposta (notifica allo store)."""
    from .models import EHSNotificaSessioneConfermata, EHSNotificaSessioneConfermataStore

    stato_precedente = sessione.stato
    sessione.data_confermata = sessione.data_proposta
    sessione.stato = 'CONFERMATA'
    sessione.save()
    _crea_evento_calendario(sessione)
    _log(sessione, stato_precedente, sessione.stato, utente, nota)
    if notifica_lato == 'store':
        EHSNotificaSessioneConfermataStore.objects.create(sessione=sessione, negozio_destinatario=sessione.negozio)
    elif sessione.fornitore:
        EHSNotificaSessioneConfermata.objects.create(sessione=sessione, fornitore=sessione.fornitore)

    corpo = f'Formazione confermata per il {_fmt(sessione.data_confermata)}.\nDocente: {sessione.docente_nome or "—"}'
    corpo_store = corpo
    if sessione.modalita == 'ONLINE' and sessione.link_online:
        corpo_store += f'\n\nFormazione ONLINE — link per partecipare alla call:\n{sessione.link_online}'
    _invia_email(_email_store(sessione), f'Formazione confermata: {_descrizione(sessione)}', corpo_store)
    _invia_email(_email_fornitore(sessione), f'Formazione confermata: {_descrizione(sessione)}', corpo)


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
            _invia_email(_email_fornitore(sessione), f'Nuova data proposta dallo store: {_descrizione(sessione)}',
                         f'Lo store ha proposto il {_fmt(nuova_data)}.\n\nAccedi all\'app per accettare o proporre un\'altra data.')
    return sessione


def accetta_controproposta(sessione, fornitore):
    """Il fornitore accetta la data contro-proposta dallo store così com'è: la sessione
    diventa CONFERMATA (stessa transizione condivisa di rispondi_data(accetta=True))."""
    if fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può accettare la contro-proposta.')
    if sessione.stato != 'DATA_CONTROPROPOSTA':
        raise TransizioneNonValida(f'Non è possibile accettare una contro-proposta dallo stato {sessione.stato}.')
    if sessione.modalita == 'ONLINE' and not sessione.link_online:
        raise TransizioneNonValida('Per una formazione online inserisci prima il link alla call.')

    with transaction.atomic():
        _conferma_sessione(sessione, fornitore, 'Fornitore ha accettato la contro-proposta: sessione confermata',
                           notifica_lato='store')
    return sessione


def aggiorna_link_online(sessione, utente, link):
    """Il fornitore inserisce o aggiorna il link alla call di una sessione online
    ancora da svolgere; se la sessione è già confermata lo store riceve il nuovo link."""
    if utente.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può modificare il link della call.')
    if sessione.modalita != 'ONLINE':
        raise TransizioneNonValida('La sessione non è in modalità online.')
    if sessione.stato in ('COMPLETATA', 'ANNULLATA', 'RIFIUTATA'):
        raise TransizioneNonValida(f'Non è possibile modificare il link dallo stato {sessione.stato}.')
    if not link:
        raise TransizioneNonValida('Il link è obbligatorio.')

    with transaction.atomic():
        sessione.link_online = link
        sessione.save(update_fields=['link_online', 'aggiornata_il'])
        _log(sessione, sessione.stato, sessione.stato, utente, 'Link della call aggiornato')
        if sessione.stato == 'CONFERMATA':
            _invia_email(_email_store(sessione), f'Link call aggiornato: {_descrizione(sessione)}',
                         f'Formazione del {_fmt(sessione.data_confermata)}.\n\nNuovo link per partecipare alla call:\n{link}')
    return sessione


# --- Cancellazioni (regola dei 7 giorni) --------------------------------------

def cancellazione_consentita(sessione, utente):
    """Store e fornitore possono cancellare iscritti o la formazione confermata solo
    fino a GIORNI_LIMITE_CANCELLAZIONE giorni prima della data; Admin/HO sempre.
    Prima della conferma non c'è ancora una data fissata e la regola non si applica."""
    if utente.livello_accesso in RUOLI_ADMIN:
        return True
    if sessione.stato != 'CONFERMATA' or not sessione.data_confermata:
        return True
    return timezone.now() <= sessione.data_confermata - timedelta(days=GIORNI_LIMITE_CANCELLAZIONE)


def _verifica_cancellazione(sessione, utente, cosa):
    if not cancellazione_consentita(sessione, utente):
        raise TransizioneNonValida(
            f'Non è più possibile cancellare {cosa}: mancano meno di {GIORNI_LIMITE_CANCELLAZIONE} giorni '
            f'alla formazione. Contatta l\'EHS Admin.'
        )


def rimuovi_partecipante(sessione, partecipante, utente):
    """Cancella l'iscrizione di un partecipante a una sessione confermata (store,
    fornitore o Admin), nel rispetto della regola dei 7 giorni."""
    if sessione.stato != 'CONFERMATA':
        raise TransizioneNonValida(f'Non è possibile rimuovere partecipanti dallo stato {sessione.stato}.')
    if utente.livello_accesso == 'store' and utente.store_id not in (sessione.negozio_id, partecipante.utente.store_id):
        raise TransizioneNonValida('Puoi rimuovere solo partecipanti della tua sessione o del tuo negozio.')
    _verifica_cancellazione(sessione, utente, "l'iscrizione")

    from participants.models import Iscrizione

    with transaction.atomic():
        nome = partecipante.utente.nome_completo
        if sessione.calendario_evento_id:
            Iscrizione.objects.filter(evento_id=sessione.calendario_evento_id, user=partecipante.utente).delete()
        # Il signal su Iscrizione rimuove già il partecipante; questo copre i dati incoerenti.
        type(partecipante).objects.filter(pk=partecipante.pk).delete()
        _log(sessione, sessione.stato, sessione.stato, utente, f'Iscrizione cancellata: {nome}')
        if utente.livello_accesso == 'fornitore':
            _invia_email(_email_store(sessione), f'Iscrizione cancellata: {_descrizione(sessione)}',
                         f'Il fornitore ha cancellato l\'iscrizione di {nome} alla formazione del {_fmt(sessione.data_confermata)}.')
        elif utente.livello_accesso == 'store':
            _invia_email(_email_fornitore(sessione), f'Iscrizione cancellata: {_descrizione(sessione)}',
                         f'Lo store ha cancellato l\'iscrizione di {nome} alla formazione del {_fmt(sessione.data_confermata)}.')


def annulla_sessione(sessione, utente):
    """Cascata definita in §5: rimuove evento di calendario e iscrizioni collegate,
    senza step di conferma intermedi. Raggiungibile da qualunque stato precedente a
    COMPLETATA; per una sessione confermata vale la regola dei 7 giorni."""
    if sessione.stato in ('COMPLETATA', 'ANNULLATA', 'RIFIUTATA'):
        raise TransizioneNonValida(f'Non è possibile annullare una sessione nello stato {sessione.stato}.')
    _verifica_cancellazione(sessione, utente, 'la formazione')

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

        oggetto = f'Formazione annullata: {_descrizione(sessione)}'
        corpo = f'La formazione {_descrizione(sessione)} è stata annullata da {utente.nome_completo}.'
        if stato_precedente == 'CONFERMATA':
            corpo += f'\nData prevista: {_fmt(sessione.data_confermata)}'
        if utente.livello_accesso != 'store':
            _invia_email(_email_store(sessione), oggetto, corpo)
        if utente.livello_accesso != 'fornitore':
            _invia_email(_email_fornitore(sessione), oggetto, corpo)
    return sessione


# --- Chiusura aula e attestati -------------------------------------------------

def invia_email_registro(sessione):
    """Invio di sistema dei documenti di chiusura al momento della chiusura aula:
    non è un'azione manuale del fornitore, lui carica solo in app."""
    destinatario = getattr(settings, 'EHS_EMAIL_ATTESTATI', 'vspampinato@primark.it')
    allegati = []
    for doc in sessione.documenti.all():
        try:
            doc.file.open('rb')
            try:
                allegati.append((doc.nome_originale or doc.file.name.rsplit('/', 1)[-1], doc.file.read()))
            finally:
                doc.file.close()
        except Exception:
            logger.exception('Lettura documento %s fallita per sessione %s', doc.id, sessione.id)
    _invia_email(
        [destinatario], f'Registro — {_descrizione(sessione)}',
        f'Documenti di chiusura del corso {sessione.corso.nome} presso {sessione.negozio}, '
        f'sessione del {_fmt(sessione.data_confermata)}.',
        allegati=allegati,
    )


def chiudi_aula(sessione, presenze, files, utente_fornitore, assenze_motivo=None):
    """Azione unica del fornitore a fine sessione: conferma presenze, carica i
    documenti di chiusura (registro compilato ed eventuali altri file, consultabili poi
    dal negozio nella sezione Registri), invia email di sistema, chiude formalmente
    e calcola le scadenze. presenze: {partecipante_id: bool}."""
    from .models import EHSSessioneDocumento

    assenze_motivo = assenze_motivo or {}
    if utente_fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida("Solo il Fornitore (o Admin/HO) può chiudere l'aula.")
    if sessione.stato != 'CONFERMATA':
        raise TransizioneNonValida(f"Non è possibile chiudere l'aula dallo stato {sessione.stato}.")
    if not files:
        raise TransizioneNonValida('Carica almeno un documento (il registro compilato) per chiudere l\'aula.')

    from participants.models import Iscrizione

    with transaction.atomic():
        now = timezone.now()
        sessione.data_chiusura = now
        sessione.chiusa_da = utente_fornitore
        sessione.stato = 'COMPLETATA'
        sessione.save()

        for f in files:
            EHSSessioneDocumento.objects.create(
                sessione=sessione, file=f, nome_originale=getattr(f, 'name', '')[:255],
                caricato_da=utente_fornitore,
            )

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
            if partecipante.presente:
                registra_formazione_da_aula(partecipante, now.date())

            # Allinea l'iscrizione standard (Report/Completamento generali di Kollegas):
            # un assente EHS deve risultare "assente" anche fuori dalla sezione EHS.
            if sessione.calendario_evento_id:
                Iscrizione.objects.filter(
                    evento_id=sessione.calendario_evento_id, user=partecipante.utente
                ).update(stato='partecipato' if partecipante.presente else 'assente')

        invia_email_registro(sessione)

        _log(sessione, 'CONFERMATA', 'COMPLETATA', utente_fornitore,
             f'Chiusura aula: presenze confermate, {len(files)} documento/i caricato/i e inviato/i')
    return sessione


def segna_attestati_caricati(sessione, utente):
    """Il fornitore conferma di aver caricato gli attestati nella cartella SharePoint
    aziendale (anche giorni dopo la chiusura aula)."""
    if utente.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può confermare il caricamento degli attestati.')
    if sessione.stato != 'COMPLETATA':
        raise TransizioneNonValida('Gli attestati si caricano dopo la chiusura dell\'aula.')

    with transaction.atomic():
        sessione.attestati_caricati_il = timezone.now()
        sessione.attestati_caricati_da = utente
        sessione.save(update_fields=['attestati_caricati_il', 'attestati_caricati_da', 'aggiornata_il'])
        _log(sessione, sessione.stato, sessione.stato, utente, 'Attestati caricati su SharePoint')
        destinatario = getattr(settings, 'EHS_EMAIL_ATTESTATI', 'vspampinato@primark.it')
        _invia_email([destinatario], f'Attestati caricati: {_descrizione(sessione)}',
                     f'Il fornitore {utente.nome_completo} ha caricato gli attestati della sessione del '
                     f'{_fmt(sessione.data_confermata)} nella cartella SharePoint.')
    return sessione


# --- Scadenze ------------------------------------------------------------------

def scadenze_in_arrivo(negozio=None, giorni=GIORNI_ALERT_SCADENZA):
    """Per ogni utente attivo e corso, l'ultima formazione completata con scadenza
    entro `giorni` (comprese quelle già scadute). Una formazione rinnovata in seguito
    non compare più. Il negozio considerato è quello dove l'utente è in forza oggi
    (`User.store`). Ritorna una lista di dict ordinata per giorni mancanti."""
    from .models import EHSPartecipante

    oggi = timezone.now().date()
    qs = (EHSPartecipante.objects
          .filter(completato=True, scadenza_formazione__isnull=False, utente__is_active=True)
          .select_related('utente__store', 'sessione__corso'))
    if negozio is not None:
        qs = qs.filter(utente__store=negozio)

    ultime = {}
    for p in qs:
        chiave = (p.utente_id, p.sessione.corso_id)
        if chiave not in ultime or p.scadenza_formazione > ultime[chiave].scadenza_formazione:
            ultime[chiave] = p

    soglia = oggi + timedelta(days=giorni)
    in_scadenza = [p for p in ultime.values() if p.scadenza_formazione <= soglia]
    if not in_scadenza:
        return []

    # Rinnovo già pianificato: l'utente è iscritto a una sessione futura dello stesso corso.
    pianificati = set(EHSPartecipante.objects.filter(
        sessione__stato='CONFERMATA', sessione__data_confermata__gte=timezone.now(),
        utente_id__in={p.utente_id for p in in_scadenza},
    ).values_list('utente_id', 'sessione__corso_id'))

    risultato = [
        {
            'partecipante_id': p.id,
            'utente_id': p.utente_id,
            'utente_nome': p.utente.nome_completo,
            'negozio_id': p.utente.store_id,
            'negozio_nome': p.utente.store.nome if p.utente.store else None,
            'corso_id': p.sessione.corso_id,
            'corso_nome': p.sessione.corso.nome,
            'scadenza_formazione': p.scadenza_formazione,
            'giorni_mancanti': (p.scadenza_formazione - oggi).days,
            'rinnovo_pianificato': (p.utente_id, p.sessione.corso_id) in pianificati,
        }
        for p in in_scadenza
    ]
    risultato.sort(key=lambda r: (r['giorni_mancanti'], r['utente_nome']))
    return risultato


def genera_notifiche_scadenza():
    """Job giornaliero (§8bis): genera una notifica per il negozio dove l'utente è
    attualmente in forza (`User.store`, non necessariamente il negozio dove ha fatto
    il corso — es. trasferimenti) quando mancano GIORNI_ALERT_SCADENZA giorni o meno
    alla scadenza. Usa `<=` invece dell'uguaglianza esatta per coprire eventuali gap
    se il job salta un giorno; l'idempotenza è garantita dal vincolo OneToOne su
    `partecipante`, quindi eseguire il job più volte è sempre sicuro.
    Ritorna il numero di notifiche create."""
    from .models import EHSNotificaScadenza, EHSPartecipante

    soglia = timezone.now().date() + timedelta(days=GIORNI_ALERT_SCADENZA)
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


# --- Formazione obbligatoria ----------------------------------------------------

# Ruoli esclusi dal monitoraggio della formazione obbligatoria (per ora).
RUOLI_ESCLUSI_OBBLIGHI = ('Retail Assistant',)


def registra_formazione_da_aula(partecipante, data):
    """Riporta nel registro formazioni la presenza confermata a un'aula EHS. Se per
    lo stesso giorno esiste già una registrazione (es. da import), la collega all'aula."""
    from .models import EHSFormazione

    sessione = partecipante.sessione
    formazione = (EHSFormazione.objects.filter(partecipante=partecipante).first()
                  or EHSFormazione.objects.filter(utente=partecipante.utente, corso=sessione.corso, data=data).first()
                  or EHSFormazione(utente=partecipante.utente, corso=sessione.corso, data=data))
    formazione.data = data
    formazione.ore = sessione.durata_ore
    formazione.partecipante = partecipante
    formazione.fonte = 'aula'
    formazione.save()
    return formazione


def persone_monitorate(negozio):
    """Utenti attivi del negozio soggetti alla matrice obblighi: esclusi account
    negozio/fornitore e i ruoli fuori perimetro."""
    from django.contrib.auth import get_user_model

    return (get_user_model().objects
            .filter(store=negozio, is_active=True)
            .exclude(livello_accesso__in=('store', 'fornitore'))
            .exclude(ruolo__nome__in=RUOLI_ESCLUSI_OBBLIGHI)
            .select_related('ruolo')
            .prefetch_related('ehs_mansioni')
            .order_by('cognome', 'nome'))


def imposta_cella_matrice(corso, ruolo=None, mansione=None, stato=None):
    """stato: 'obbligatorio', 'facoltativo' o None (nessun obbligo)."""
    from .models import EHSObbligo

    filtro = {'corso': corso, 'ruolo': ruolo, 'mansione': mansione}
    if stato is None:
        EHSObbligo.objects.filter(**filtro).delete()
        return None
    obbligo, _ = EHSObbligo.objects.update_or_create(**filtro, defaults={'facoltativo': stato == 'facoltativo'})
    return obbligo
