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
# Un'aula non parte mai con meno di PARTECIPANTI_MINIMI iscritti: GIORNI_AVVISO_MINIMO
# giorni prima della data store, fornitore ed EHS Admin ricevono l'avviso, e se il
# giorno dopo il minimo non è ancora raggiunto l'aula viene annullata in automatico.
PARTECIPANTI_MINIMI = 3
GIORNI_AVVISO_MINIMO = 4
# Chi ha una formazione ancora valida può rifarla solo negli ultimi N giorni prima della scadenza.
GIORNI_RINNOVO_ANTICIPATO = 120


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


def fornitore_secondario(corso, fornitore):
    return corso.offerte.filter(fornitore=fornitore, secondario=True).exists()


def _richiede_validazione_secondario(utente, corso, fornitore):
    # L'EHS Admin e l'Admin non devono validare le proprie scelte.
    return utente.livello_accesso not in RUOLI_APPROVAZIONE_ECCEZIONI and fornitore_secondario(corso, fornitore)


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
        principali = [f for f in idonei if not fornitore_secondario(corso, f)]
        if fornitore is None and len(principali) == 1:
            fornitore = principali[0]
        if fornitore is None:
            if not idonei:
                raise TransizioneNonValida(
                    'Nessun fornitore disponibile per questo corso nel tuo negozio: invia una richiesta eccezionale.'
                )
            raise TransizioneNonValida('Seleziona il fornitore.')
        if fornitore not in idonei:
            raise TransizioneNonValida('Il fornitore selezionato non eroga questo corso per il negozio.')

    from .models import EHSSessione

    secondario = not eccezionale and _richiede_validazione_secondario(store_user, corso, fornitore)
    in_approvazione = eccezionale or secondario
    with transaction.atomic():
        sessione = EHSSessione.objects.create(
            corso=corso, negozio=negozio, creata_da=store_user,
            fornitore=None if in_approvazione else fornitore,
            fornitore_richiesto=fornitore if in_approvazione else None,
            eccezionale=eccezionale,
            fornitore_secondario=secondario,
            motivazione_eccezione=motivazione_eccezione.strip() if eccezionale else '',
            stato='IN_APPROVAZIONE' if in_approvazione else 'RICHIESTA_INVIATA',
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
        elif secondario:
            _log(sessione, '', sessione.stato, store_user,
                 f'Richiesta al fornitore secondario {_nome_fornitore(fornitore)}: in validazione EHS Admin')
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
        corpo = (f'Hai ricevuto una nuova richiesta di formazione EHS.\n\n'
                 f'Corso: {sessione.corso.nome}\nNegozio: {sessione.negozio}\n'
                 f'Partecipanti previsti: {sessione.partecipanti_previsti or "—"}\n'
                 f'Data suggerita dallo store: {_fmt(sessione.data_suggerita_store)}\n\n'
                 f'Accedi all\'app per confermare la data (indicando modalità e partecipanti), '
                 f'proporne un\'altra o segnalare la tua non disponibilità.')
        _invia_email([fornitore.email], f'Nuova richiesta: {_descrizione(sessione)}', corpo)


def _email_richiesta_eccezionale(sessione):
    tipo = 'a un fornitore secondario' if sessione.fornitore_secondario else 'eccezionale'
    corpo = (f'Lo store {sessione.negozio} ha inviato una richiesta {tipo} da approvare.\n\n'
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
        sessione.data_proposta = None
        sessione.docente_nome = None
        sessione.docente_telefono = None
        if _richiede_validazione_secondario(utente, sessione.corso, fornitore):
            sessione.fornitore = None
            sessione.fornitore_richiesto = fornitore
            sessione.fornitore_secondario = True
            sessione.stato = 'IN_APPROVAZIONE'
            sessione.save()
            _log(sessione, stato_precedente, sessione.stato, utente,
                 f'Richiesta al fornitore secondario {_nome_fornitore(fornitore)}: in validazione EHS Admin')
            _email_richiesta_eccezionale(sessione)
            return sessione
        sessione.fornitore = fornitore
        sessione.stato = 'RICHIESTA_INVIATA'
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
        elif sessione.fornitore_secondario:
            # Fornitore secondario non validato: la richiesta torna allo store senza
            # fornitore, così può assegnarla al fornitore principale.
            sessione.stato = 'RICHIESTA_INVIATA'
            sessione.fornitore = None
            sessione.fornitore_secondario = False
            sessione.save()
            _log(sessione, 'IN_APPROVAZIONE', sessione.stato, admin, f'Fornitore secondario non validato: {nota}')
            _invia_email(_email_store(sessione), f'Fornitore secondario non validato: {_descrizione(sessione)}',
                         f"L'EHS Admin non ha validato il fornitore richiesto.\nMotivo: {nota}\n\n"
                         f"Assegna la richiesta a un altro fornitore dall'app.")
        else:
            sessione.stato = 'RIFIUTATA'
            sessione.save(update_fields=['stato', 'aggiornata_il'])
            _log(sessione, 'IN_APPROVAZIONE', sessione.stato, admin, f'Richiesta eccezionale rifiutata: {nota}')
            _invia_email(_email_store(sessione), f'Richiesta eccezionale rifiutata: {_descrizione(sessione)}',
                         f'La richiesta eccezionale è stata rifiutata dall\'EHS Admin.\nMotivo: {nota}')
    return sessione


# --- Negoziazione data --------------------------------------------------------

def minimo_partecipanti(sessione):
    return max(PARTECIPANTI_MINIMI, sessione.partecipanti_min or 0)


def _valida_min_max(partecipanti_min, partecipanti_max):
    try:
        minimo, massimo = int(partecipanti_min), int(partecipanti_max)
    except (TypeError, ValueError):
        raise TransizioneNonValida('Indica il numero minimo e massimo di partecipanti.')
    if minimo < PARTECIPANTI_MINIMI:
        raise TransizioneNonValida(f'Il minimo di partecipanti non può essere inferiore a {PARTECIPANTI_MINIMI}.')
    if massimo < minimo:
        raise TransizioneNonValida('Il massimo di partecipanti non può essere inferiore al minimo.')
    return minimo, massimo


def data_proposta_dallo_store(sessione):
    """Data e ora che lo store ha chiesto al fornitore: la contro-proposta, oppure la
    data suggerita nella richiesta."""
    if sessione.stato == 'DATA_CONTROPROPOSTA':
        return sessione.data_proposta
    return sessione.data_suggerita_store


def proponi_data(sessione, fornitore, data_proposta, docente_nome, docente_telefono, link_online=None,
                 partecipanti_min=None, partecipanti_max=None, modalita=None):
    """Il fornitore indica data, docente, modalità (in presenza/online, con il link per
    l'online) e minimo/massimo di partecipanti. Se la data è quella chiesta dallo store
    la formazione è confermata subito; altrimenti diventa una proposta che lo store
    accetta o a cui contro-propone (§3: il ciclo si ripete fino alla conferma)."""
    if fornitore.livello_accesso not in RUOLI_FORNITORE:
        raise TransizioneNonValida('Solo il Fornitore (o Admin/HO) può proporre una data.')
    if sessione.stato not in ('RICHIESTA_INVIATA', 'DATA_CONTROPROPOSTA'):
        raise TransizioneNonValida(f'Non è possibile proporre una data dallo stato {sessione.stato}.')
    if not docente_nome or not docente_telefono:
        raise TransizioneNonValida('Nome e telefono del docente sono obbligatori.')
    sessione.partecipanti_min, sessione.partecipanti_max = _valida_min_max(partecipanti_min, partecipanti_max)
    _valida_mezzora(data_proposta, 'Data proposta')
    if modalita is not None:
        if modalita not in ('PRESENZA', 'ONLINE'):
            raise TransizioneNonValida('Indica se la formazione sarà in presenza o online.')
        sessione.modalita = modalita
    if link_online is not None:
        sessione.link_online = link_online
    if sessione.modalita == 'ONLINE' and not sessione.link_online:
        raise TransizioneNonValida('Per una formazione online il link alla call è obbligatorio.')
    conferma_diretta = data_proposta == data_proposta_dallo_store(sessione)

    with transaction.atomic():
        if conferma_diretta:
            sessione.data_proposta = data_proposta
            sessione.docente_nome = docente_nome
            sessione.docente_telefono = docente_telefono
            if fornitore.livello_accesso == 'fornitore':
                sessione.fornitore = fornitore
            _conferma_sessione(sessione, fornitore,
                               f'Fornitore ha confermato la data chiesta dallo store — docente: {docente_nome} — '
                               f'partecipanti min {sessione.partecipanti_min}, max {sessione.partecipanti_max}',
                               notifica_lato='store')
            return sessione
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
             f'Data proposta: {data_proposta} — docente: {docente_nome} — '
             f'partecipanti min {sessione.partecipanti_min}, max {sessione.partecipanti_max}')
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
        max_partecipanti=sessione.partecipanti_max or 0,
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


def _annulla(sessione, utente, nota):
    """Cascata comune di annullamento: evento di calendario, iscrizioni e partecipanti."""
    # Import locale: evita una dipendenza a livello di modulo tra le app ehs e participants.
    from participants.models import Iscrizione

    stato_precedente = sessione.stato
    sessione.stato = 'ANNULLATA'
    sessione.save()
    if sessione.calendario_evento:
        Iscrizione.objects.filter(evento=sessione.calendario_evento).delete()
        sessione.calendario_evento.delete()
    sessione.partecipanti.all().delete()
    _log(sessione, stato_precedente, 'ANNULLATA', utente, nota)
    return stato_precedente


def annulla_sessione(sessione, utente):
    """Cascata definita in §5: rimuove evento di calendario e iscrizioni collegate,
    senza step di conferma intermedi. Raggiungibile da qualunque stato precedente a
    COMPLETATA; per una sessione confermata vale la regola dei 7 giorni."""
    if sessione.stato in ('COMPLETATA', 'ANNULLATA', 'RIFIUTATA'):
        raise TransizioneNonValida(f'Non è possibile annullare una sessione nello stato {sessione.stato}.')
    _verifica_cancellazione(sessione, utente, 'la formazione')

    with transaction.atomic():
        stato_precedente = _annulla(sessione, utente, 'Sessione annullata: evento e iscrizioni rimossi automaticamente')

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

def _ultime_formazioni_con_scadenza(negozio=None):
    """Per ogni utente attivo e corso, l'ultima formazione registrata (aula, import o
    manuale), se ha una scadenza. Una formazione rinnovata in seguito non conta più."""
    from .models import EHSFormazione

    qs = (EHSFormazione.objects
          .filter(utente__is_active=True)
          .select_related('utente__store', 'corso')
          .order_by('data'))
    if negozio is not None:
        qs = qs.filter(utente__store=negozio)
    ultime = {}
    for f in qs:
        ultime[(f.utente_id, f.corso_id)] = f  # ordinate per data: resta l'ultima
    return [f for f in ultime.values() if f.scadenza]


def scadenze_in_arrivo(negozio=None, giorni=GIORNI_ALERT_SCADENZA):
    """Formazioni (dal registro) con scadenza entro `giorni`, comprese quelle già
    scadute. Il negozio considerato è quello dove l'utente è in forza oggi
    (`User.store`). Ritorna una lista di dict ordinata per giorni mancanti."""
    from .models import EHSPartecipante

    oggi = timezone.now().date()
    soglia = oggi + timedelta(days=giorni)
    in_scadenza = [f for f in _ultime_formazioni_con_scadenza(negozio) if f.scadenza <= soglia]
    if not in_scadenza:
        return []

    # Rinnovo già pianificato: l'utente è iscritto a una sessione futura dello stesso corso.
    pianificati = set(EHSPartecipante.objects.filter(
        sessione__stato='CONFERMATA', sessione__data_confermata__gte=timezone.now(),
        utente_id__in={f.utente_id for f in in_scadenza},
    ).values_list('utente_id', 'sessione__corso_id'))

    risultato = [
        {
            'formazione_id': f.id,
            'utente_id': f.utente_id,
            'utente_nome': f.utente.nome_completo,
            'negozio_id': f.utente.store_id,
            'negozio_nome': f.utente.store.nome if f.utente.store else None,
            'corso_id': f.corso_id,
            'corso_nome': f.corso.nome,
            'scadenza_formazione': f.scadenza,
            'giorni_mancanti': (f.scadenza - oggi).days,
            'rinnovo_pianificato': (f.utente_id, f.corso_id) in pianificati,
        }
        for f in in_scadenza
    ]
    risultato.sort(key=lambda r: (r['giorni_mancanti'], r['utente_nome']))
    return risultato


def genera_notifiche_scadenza():
    """Genera una notifica per il negozio dove l'utente è attualmente in forza
    (`User.store`, non necessariamente quello dove ha fatto il corso) per ogni
    formazione del registro che scade entro GIORNI_ALERT_SCADENZA giorni. Le
    formazioni già scadute non generano popup (restano in rosso nel pannello
    Scadenze e nel Completamento): così un import storico non inonda i negozi.
    Idempotente grazie al vincolo OneToOne su `formazione`.
    Ritorna il numero di notifiche create."""
    from .models import EHSNotificaScadenza

    oggi = timezone.now().date()
    soglia = oggi + timedelta(days=GIORNI_ALERT_SCADENZA)
    creati = 0
    for f in _ultime_formazioni_con_scadenza():
        if not (oggi <= f.scadenza <= soglia) or not f.utente.store_id:
            continue
        _, created = EHSNotificaScadenza.objects.get_or_create(
            formazione=f, defaults={'negozio_destinatario': f.utente.store}
        )
        creati += created
    return creati


def esegui_automatismi_giornalieri():
    """Automatismi EHS da eseguire una volta al giorno. Non c'è uno schedulatore:
    li fa partire il primo accesso del giorno (vedi ehs.middleware). L'update
    condizionale garantisce che, anche con più processi, parta una sola volta."""
    from .models import EHSConfigurazione

    oggi = timezone.now().date()
    EHSConfigurazione.get()
    vinto = (EHSConfigurazione.objects.filter(pk=1)
             .exclude(ultimo_controllo_giornaliero=oggi)
             .update(ultimo_controllo_giornaliero=oggi))
    if not vinto:
        return None
    creati = genera_notifiche_scadenza()
    avvisate, annullate = controlla_minimo_partecipanti()
    logger.info('Automatismi EHS giornalieri: %s notifiche di scadenza, %s aule sotto il minimo avvisate, '
                '%s annullate', creati, avvisate, annullate)
    return creati


# --- Minimo partecipanti -------------------------------------------------------

def _avvisa(sessione, tipo, testo, oggetto):
    """Avviso in app + email a negozio richiedente, fornitore ed EHS Admin."""
    from django.contrib.auth import get_user_model
    from .models import EHSAvviso

    EHSAvviso.objects.create(sessione=sessione, tipo=tipo, testo=testo, negozio=sessione.negozio)
    destinatari = list(get_user_model().objects.filter(livello_accesso='admin_ehs', is_active=True))
    if sessione.fornitore_id:
        destinatari.append(sessione.fornitore)
    for u in destinatari:
        EHSAvviso.objects.create(sessione=sessione, tipo=tipo, testo=testo, utente=u)
    _invia_email(_email_store(sessione) + _email_fornitore(sessione) + _email_admin_ehs(),
                 f'{oggetto}: {_descrizione(sessione)}', testo)


def controlla_minimo_partecipanti(adesso=None):
    """Aule confermate sotto il minimo di partecipanti: a GIORNI_AVVISO_MINIMO giorni
    dalla data parte l'avviso (annullamento entro 24 ore); dal giorno dopo l'avviso,
    se il minimo non è ancora raggiunto, l'aula viene annullata in automatico.
    Ritorna (avvisate, annullate)."""
    from .models import EHSSessione

    adesso = adesso or timezone.now()
    oggi = timezone.localtime(adesso).date()
    avvisate = annullate = 0
    sessioni = (EHSSessione.objects.filter(stato='CONFERMATA', data_confermata__gt=adesso)
                .select_related('corso', 'negozio', 'fornitore', 'calendario_evento'))
    for sessione in sessioni:
        iscritti = sessione.partecipanti.count()
        minimo = minimo_partecipanti(sessione)
        if iscritti >= minimo:
            continue
        giorni = (timezone.localtime(sessione.data_confermata).date() - oggi).days
        quando = _fmt(sessione.data_confermata)
        with transaction.atomic():
            if sessione.avviso_minimo_il is None:
                if giorni > GIORNI_AVVISO_MINIMO:
                    continue
                sessione.avviso_minimo_il = adesso
                sessione.save(update_fields=['avviso_minimo_il', 'aggiornata_il'])
                testo = (f'La formazione {_descrizione(sessione)} del {quando} ha {iscritti} iscritti su un minimo '
                         f'di {minimo}. Se entro 24 ore non si raggiunge il minimo, la formazione verrà '
                         f'cancellata automaticamente.')
                _log(sessione, sessione.stato, sessione.stato, None, f'Avviso minimo partecipanti ({iscritti}/{minimo})')
                _avvisa(sessione, 'minimo_partecipanti', testo, 'Minimo partecipanti non raggiunto')
                avvisate += 1
            elif timezone.localtime(sessione.avviso_minimo_il).date() < oggi:
                _annulla(sessione, None, f'Annullata automaticamente: {iscritti} iscritti su un minimo di {minimo}')
                testo = (f'La formazione {_descrizione(sessione)} del {quando} è stata cancellata automaticamente: '
                         f'{iscritti} iscritti su un minimo di {minimo}.')
                _avvisa(sessione, 'annullata_minimo', testo, 'Formazione cancellata')
                annullate += 1
    return avvisate, annullate


# --- Iscrizioni alle aule --------------------------------------------------------

def ultima_formazione(utente, corso):
    from .models import EHSFormazione
    return EHSFormazione.objects.filter(utente=utente, corso=corso).order_by('-data').first()


def rinnovabile_dal(formazione):
    """Primo giorno in cui si può rifare un corso ancora valido (None = nessun vincolo)."""
    if not formazione or not formazione.scadenza:
        return None
    return formazione.scadenza - timedelta(days=GIORNI_RINNOVO_ANTICIPATO)


def verifica_iscrizione(evento, utente):
    """Regole per iscrivere una persona a un'aula EHS: posti entro il massimo indicato
    dal fornitore e, se ha già la formazione valida, rinnovo solo negli ultimi
    GIORNI_RINNOVO_ANTICIPATO giorni prima della scadenza."""
    sessione = getattr(evento, 'ehs_sessione', None)
    if sessione is None:
        return
    if sessione.partecipanti_max and sessione.partecipanti.count() >= sessione.partecipanti_max:
        raise TransizioneNonValida(f'Posti esauriti: massimo {sessione.partecipanti_max} partecipanti.')
    formazione = ultima_formazione(utente, sessione.corso)
    dal = rinnovabile_dal(formazione)
    if dal and evento.data < dal:
        raise TransizioneNonValida(
            f'{utente.nome_completo} ha {sessione.corso.nome} valido fino al '
            f'{formazione.scadenza.strftime("%d/%m/%Y")}: si può rinnovare solo negli ultimi '
            f'{GIORNI_RINNOVO_ANTICIPATO} giorni prima della scadenza, cioè con un\'aula dal '
            f'{dal.strftime("%d/%m/%Y")}.'
        )


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


# --- Completamento formazione obbligatoria --------------------------------------

STATI_CONFORMI = ('valida', 'in_scadenza')


def _persone_monitorate_tutte():
    from django.contrib.auth import get_user_model

    return (get_user_model().objects
            .filter(is_active=True, store__isnull=False)
            .exclude(livello_accesso__in=('store', 'fornitore'))
            .exclude(ruolo__nome__in=RUOLI_ESCLUSI_OBBLIGHI)
            .select_related('ruolo', 'store')
            .prefetch_related('ehs_mansioni'))


def calcola_stati(persone):
    """Per ogni persona, lo stato di ciascun corso previsto dalla matrice per il suo
    ruolo o le sue mansioni: {user_id: {corso_id: {'stato', 'facoltativo', 'scadenza', 'data'}}}.
    Stati: valida, in_scadenza (entro GIORNI_ALERT_SCADENZA), scaduta, mancante, iscritta
    (aula confermata già in calendario: vale solo se la formazione non è valida)."""
    from .models import EHSFormazione, EHSObbligo, EHSPartecipante

    persone = list(persone)
    ids = [p.id for p in persone]
    per_ruolo, per_mansione = {}, {}
    for o in EHSObbligo.objects.filter(corso__attivo=True):
        if o.ruolo_id:
            per_ruolo.setdefault(o.ruolo_id, {})[o.corso_id] = o.facoltativo
        else:
            per_mansione.setdefault(o.mansione_id, {})[o.corso_id] = o.facoltativo

    ultime = {}
    for f in EHSFormazione.objects.filter(utente_id__in=ids).order_by('data'):
        ultime[(f.utente_id, f.corso_id)] = f  # ordinate per data: resta l'ultima
    iscritte = set(EHSPartecipante.objects.filter(
        utente_id__in=ids, sessione__stato='CONFERMATA', completato=False,
    ).values_list('utente_id', 'sessione__corso_id'))

    oggi = timezone.now().date()
    soglia = oggi + timedelta(days=GIORNI_ALERT_SCADENZA)
    risultato = {}
    for p in persone:
        richiesti = dict(per_ruolo.get(p.ruolo_id, {}))
        for m in p.ehs_mansioni.all():
            for corso_id, facoltativo in per_mansione.get(m.id, {}).items():
                # Se un corso è obbligatorio per il ruolo o per una mansione, prevale l'obbligo.
                richiesti[corso_id] = richiesti.get(corso_id, True) and facoltativo
        stati = {}
        for corso_id, facoltativo in richiesti.items():
            f = ultime.get((p.id, corso_id))
            if f is None:
                stato = 'mancante'
            elif f.scadenza is None or f.scadenza > soglia:
                stato = 'valida'
            elif f.scadenza >= oggi:
                stato = 'in_scadenza'
            else:
                stato = 'scaduta'
            if stato in ('mancante', 'scaduta') and (p.id, corso_id) in iscritte:
                stato = 'iscritta'
            stati[corso_id] = {'stato': stato, 'facoltativo': facoltativo,
                               'scadenza': f.scadenza if f else None, 'data': f.data if f else None}
        risultato[p.id] = stati
    return risultato


def riepiloga(stati_persone, corsi_ids):
    """Conteggi per corso su un insieme di persone: gli obblighi entrano nella
    percentuale, i facoltativi sono contati a parte ('pronti per la promozione')."""
    out = {}
    for corso_id in corsi_ids:
        c = {'dovuti': 0, 'valida': 0, 'in_scadenza': 0, 'scaduta': 0, 'mancante': 0, 'iscritta': 0,
             'facoltativi': 0, 'facoltativi_fatti': 0}
        for stati in stati_persone:
            s = stati.get(corso_id)
            if s is None:
                continue
            if s['facoltativo']:
                c['facoltativi'] += 1
                c['facoltativi_fatti'] += s['stato'] in STATI_CONFORMI
            else:
                c['dovuti'] += 1
                c[s['stato']] += 1
        c['conformi'] = c['valida'] + c['in_scadenza']
        c['percentuale'] = round(100 * c['conformi'] / c['dovuti']) if c['dovuti'] else None
        out[corso_id] = c
    return out


def _corsi_json(corsi):
    # richiedibile: ha almeno un fornitore, quindi si può chiedere un'aula da 'Nuova Richiesta'.
    return [{'id': c.id, 'nome': c.nome, 'durata_ore': c.durata_ore, 'richiedibile': c.offerte.exists()}
            for c in corsi]


def completamento_obbligatori():
    """Riepilogo Italia, per area e per negozio di tutti i corsi della matrice."""
    from stores.models import Area
    from .models import EHSCorso

    persone = list(_persone_monitorate_tutte())
    stati = calcola_stati(persone)
    corsi = list(EHSCorso.objects.filter(attivo=True, obblighi__isnull=False).distinct().order_by('nome'))
    corsi_ids = [c.id for c in corsi]

    aree = list(Area.objects.prefetch_related('stores').order_by('numero'))
    area_di = {}
    for a in aree:
        for s in a.stores.all():
            area_di.setdefault(s.id, a.numero)

    per_negozio = {}
    for p in persone:
        per_negozio.setdefault(p.store, []).append(stati[p.id])
    per_area = {}
    for p in persone:
        per_area.setdefault(area_di.get(p.store_id), []).append(stati[p.id])

    return {
        'corsi': _corsi_json(corsi),
        'italia': riepiloga(list(stati.values()), corsi_ids),
        'aree': [
            {'numero': a.numero, 'area_manager_retail': a.area_manager_retail, 'area_bp': a.area_bp,
             'corsi': riepiloga(per_area[a.numero], corsi_ids)}
            for a in aree if a.numero in per_area
        ],
        'negozi': [
            {'id': n.id, 'nome': n.nome, 'codice_store': n.codice_store, 'area': area_di.get(n.id),
             'persone': len(lista), 'corsi': riepiloga(lista, corsi_ids)}
            for n, lista in sorted(per_negozio.items(), key=lambda x: x[0].nome)
        ],
    }


def completamento_negozio(negozio):
    """Dettaglio persona per persona di un negozio, con il riepilogo per corso."""
    from .models import EHSCorso

    persone = list(persone_monitorate(negozio))
    stati = calcola_stati(persone)
    corsi = list(EHSCorso.objects.filter(id__in={cid for s in stati.values() for cid in s}).order_by('nome'))
    return {
        'negozio': {'id': negozio.id, 'nome': negozio.nome},
        'corsi': _corsi_json(corsi),
        'riepilogo': riepiloga(list(stati.values()), [c.id for c in corsi]),
        'persone': [
            {'id': p.id, 'nome_completo': p.nome_completo, 'ruolo_nome': p.ruolo.nome if p.ruolo else None,
             'mansioni': [m.nome for m in p.ehs_mansioni.all()], 'stati': stati[p.id]}
            for p in persone
        ],
    }
