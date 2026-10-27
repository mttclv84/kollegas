from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from participants.models import Iscrizione
from stores.models import Store

from . import services
from .models import EHSCorso, EHSOffertaCorso, EHSPartecipante, EHSSessione
from .services import TransizioneNonValida

User = get_user_model()


def _prossima_mezzora(giorni):
    dt = timezone.now() + timedelta(days=giorni)
    return dt.replace(minute=0, second=0, microsecond=0)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EHS_EMAIL_ATTIVE=True)
class EHSFlussiTest(TestCase):
    def setUp(self):
        self.negozio = Store.objects.create(nome='Firenze', comune='Firenze', provincia='FI', email_store='fi@store.it')
        self.altro_negozio = Store.objects.create(nome='Roma', comune='Roma', provincia='RM', email_store='rm@store.it')
        self.store_user = User.objects.create_user(
            email='store@x.it', password='x', cognome='Store', nome='Fi', livello_accesso='store', store=self.negozio)
        self.admin_ehs = User.objects.create_user(
            email='adminehs@x.it', password='x', cognome='Admin', nome='EHS', livello_accesso='admin_ehs')
        self.f_rete = User.objects.create_user(
            email='rete@forn.it', password='x', cognome='A', nome='A', livello_accesso='fornitore',
            fornitore_ragione_sociale='Rete Srl')
        self.f_fuori = User.objects.create_user(
            email='fuori@forn.it', password='x', cognome='B', nome='B', livello_accesso='fornitore',
            fornitore_ragione_sociale='Fuori Srl')
        self.collaboratore = User.objects.create_user(
            email='collab@x.it', password='x', cognome='Rossi', nome='Mario', store=self.negozio)

        self.corso = EHSCorso.objects.create(codice='EHS0001', nome='Antincendio', durata_ore=4, scadenza_giorni=365)
        EHSOffertaCorso.objects.create(corso=self.corso, fornitore=self.f_rete, tutti_negozi=True)
        offerta_fuori = EHSOffertaCorso.objects.create(corso=self.corso, fornitore=self.f_fuori, tutti_negozi=False)
        offerta_fuori.negozi.set([self.altro_negozio])

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _crea(self, **kw):
        return services.crea_richiesta(self.store_user, self.corso, self.negozio, 'Ref', '', **kw)

    def _conferma(self, sessione, giorni=10, link=None):
        services.proponi_data(sessione, self.f_rete, _prossima_mezzora(giorni), 'Docente', '333', link_online=link,
                              partecipanti_min=3, partecipanti_max=10)
        services.rispondi_data(sessione, self.store_user, accetta=True)
        sessione.refresh_from_db()
        return sessione

    # --- eliminazione definitiva ---

    def test_elimina_definitivamente_solo_admin_con_conferma(self):
        sessione = self._conferma(self._crea())
        evento_id = sessione.calendario_evento_id
        self.assertIsNotNone(evento_id)
        url = f'/api/ehs/sessioni/{sessione.id}/'
        self.assertEqual(self._client(self.store_user).delete(
            url, {'conferma': 'ELIMINA DEFINITIVAMENTE'}, format='json').status_code, 403)
        self.assertEqual(self._client(self.admin_ehs).delete(
            url, {'conferma': 'elimina'}, format='json').status_code, 400)
        self.assertEqual(self._client(self.admin_ehs).delete(
            url, {'conferma': 'ELIMINA DEFINITIVAMENTE'}, format='json').status_code, 204)
        self.assertFalse(EHSSessione.objects.filter(pk=sessione.id).exists())
        from events.models import Evento
        self.assertFalse(Evento.objects.filter(pk=evento_id).exists())

    def test_elimina_fornitore_definitivamente(self):
        url = f'/api/ehs/fornitori/{self.f_fuori.id}/'
        corpo = {'definitivo': True, 'conferma': 'ELIMINA DEFINITIVAMENTE'}
        self.assertEqual(self._client(self.store_user).delete(url, corpo, format='json').status_code, 403)
        self.assertEqual(self._client(self.admin_ehs).delete(
            url, {'definitivo': True, 'conferma': 'no'}, format='json').status_code, 400)
        # Con una formazione in corso il fornitore non si può cancellare.
        self._crea()
        r = self._client(self.admin_ehs).delete(f'/api/ehs/fornitori/{self.f_rete.id}/', corpo, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._client(self.admin_ehs).delete(url, corpo, format='json').status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.f_fuori.id).exists())

    # --- perimetro fornitori ---

    def test_fornitori_idonei_ed_eccezionali(self):
        self.assertEqual(list(services.fornitori_idonei(self.corso, self.negozio)), [self.f_rete])
        self.assertEqual(list(services.fornitori_eccezionali(self.corso, self.negozio)), [self.f_fuori])
        self.assertCountEqual(services.fornitori_idonei(self.corso, self.altro_negozio), [self.f_rete, self.f_fuori])

    def test_unico_idoneo_assegnato_in_automatico_con_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            sessione = self._crea()
        self.assertEqual(sessione.fornitore, self.f_rete)
        self.assertEqual(sessione.stato, 'RICHIESTA_INVIATA')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['rete@forn.it'])

    def test_fornitore_fuori_perimetro_rifiutato_senza_eccezione(self):
        with self.assertRaises(TransizioneNonValida):
            self._crea(fornitore=self.f_fuori)

    # --- richiesta eccezionale ---

    def test_richiesta_eccezionale_approvata(self):
        sessione = self._crea(fornitore=self.f_fuori, eccezionale=True, motivazione_eccezione='Nessuna data')
        self.assertEqual(sessione.stato, 'IN_APPROVAZIONE')
        self.assertIsNone(sessione.fornitore)
        # Il fornitore richiesto non la vede finché non è approvata
        r = self._client(self.f_fuori).get('/api/ehs/sessioni/')
        self.assertEqual(r.json(), [])
        with self.assertRaises(TransizioneNonValida):
            services.decidi_eccezione(sessione, self.store_user, True)
        services.decidi_eccezione(sessione, self.admin_ehs, True)
        sessione.refresh_from_db()
        self.assertEqual(sessione.stato, 'RICHIESTA_INVIATA')
        self.assertEqual(sessione.fornitore, self.f_fuori)
        self.assertEqual(len(self._client(self.f_fuori).get('/api/ehs/sessioni/').json()), 1)

    def test_richiesta_eccezionale_rifiutata_richiede_motivo(self):
        sessione = self._crea(fornitore=self.f_fuori, eccezionale=True, motivazione_eccezione='x')
        with self.assertRaises(TransizioneNonValida):
            services.decidi_eccezione(sessione, self.admin_ehs, False, '')
        services.decidi_eccezione(sessione, self.admin_ehs, False, 'Budget')
        self.assertEqual(sessione.stato, 'RIFIUTATA')

    def test_non_disponibile_poi_eccezione(self):
        sessione = self._crea()
        services.dichiara_non_disponibile(sessione, self.f_rete, 'Agenda piena')
        self.assertEqual(sessione.stato, 'NON_DISPONIBILE')
        services.richiedi_eccezione(sessione, self.store_user, self.f_fuori, 'Fornitore di rete non disponibile')
        self.assertEqual(sessione.stato, 'IN_APPROVAZIONE')
        self.assertIsNone(sessione.fornitore)

    # --- online ---

    def test_online_richiede_link_e_lo_invia_allo_store(self):
        sessione = self._crea(modalita='ONLINE')
        with self.assertRaises(TransizioneNonValida):
            services.proponi_data(sessione, self.f_rete, _prossima_mezzora(10), 'Doc', '333', partecipanti_min=3, partecipanti_max=10)
        with self.captureOnCommitCallbacks(execute=True):
            sessione = self._conferma(sessione, link='https://teams.microsoft.com/l/abc')
        self.assertEqual(sessione.calendario_evento.ehs_luogo, 'Online')
        email_store = [m for m in mail.outbox if m.to == ['fi@store.it'] and 'confermata' in m.subject]
        self.assertTrue(email_store)
        self.assertIn('https://teams.microsoft.com/l/abc', email_store[0].body)

    def test_evento_calendario_in_ora_locale(self):
        sessione = self._conferma(self._crea())
        locale = timezone.localtime(sessione.data_confermata)
        self.assertEqual(sessione.calendario_evento.ora_inizio, locale.time())

    # --- regola dei 7 giorni ---

    def test_cancellazione_bloccata_negli_ultimi_7_giorni(self):
        sessione = self._conferma(self._crea(), giorni=3)
        Iscrizione.objects.create(evento=sessione.calendario_evento, user=self.collaboratore, stato='iscritto')
        p = EHSPartecipante.objects.get(sessione=sessione)
        for utente in (self.store_user, self.f_rete):
            with self.assertRaises(TransizioneNonValida):
                services.rimuovi_partecipante(sessione, p, utente)
            with self.assertRaises(TransizioneNonValida):
                services.annulla_sessione(sessione, utente)
        # l'EHS Admin può sempre
        services.rimuovi_partecipante(sessione, p, self.admin_ehs)
        self.assertFalse(EHSPartecipante.objects.filter(pk=p.pk).exists())
        self.assertFalse(Iscrizione.objects.filter(evento=sessione.calendario_evento).exists())

    def test_cancellazione_consentita_oltre_7_giorni(self):
        sessione = self._conferma(self._crea(), giorni=10)
        Iscrizione.objects.create(evento=sessione.calendario_evento, user=self.collaboratore, stato='iscritto')
        p = EHSPartecipante.objects.get(sessione=sessione)
        r = self._client(self.f_rete).delete(f'/api/ehs/sessioni/{sessione.id}/partecipanti/{p.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['partecipanti'], [])
        services.annulla_sessione(sessione, self.store_user)
        self.assertEqual(sessione.stato, 'ANNULLATA')

    def test_store_cancellazione_iscrizione_standard_ehs_soglia_7(self):
        sessione = self._conferma(self._crea(), giorni=10)
        isc = Iscrizione.objects.create(evento=sessione.calendario_evento, user=self.collaboratore, stato='iscritto')
        r = self._client(self.store_user).delete(f'/api/iscrizioni/{isc.id}/')
        self.assertEqual(r.status_code, 204)

    # --- chiusura aula, documenti multipli, attestati ---

    def test_chiusura_con_piu_file_e_attestati(self):
        sessione = self._conferma(self._crea(), giorni=10)
        Iscrizione.objects.create(evento=sessione.calendario_evento, user=self.collaboratore, stato='iscritto')
        p = EHSPartecipante.objects.get(sessione=sessione)
        c = self._client(self.f_rete)
        r = c.post(f'/api/ehs/sessioni/{sessione.id}/chiudi-aula/', {
            f'presente_{p.id}': 'true',
            'files': [SimpleUploadedFile('registro.pdf', b'%PDF-1', content_type='application/pdf'),
                      SimpleUploadedFile('foto.jpg', b'jpg', content_type='image/jpeg')],
        }, format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()['documenti']), 2)
        r = self._client(self.store_user).get('/api/ehs/registri/')
        self.assertEqual(len(r.json()[0]['documenti']), 2)
        r = c.patch(f'/api/ehs/sessioni/{sessione.id}/attestati-caricati/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.json()['attestati_caricati_il'])
        for d in sessione.documenti.all():
            d.file.delete(save=False)

    # --- calendario fornitore ---

    def test_calendario_fornitore_vede_solo_occupato_altrui(self):
        sessione = self._conferma(self._crea(), giorni=10)
        mese = timezone.localtime(sessione.data_confermata)
        params = {'anno': mese.year, 'mese': mese.month}
        mio = self._client(self.f_rete).get('/api/ehs/calendario/', params).json()
        self.assertEqual(mio[0]['ehs_corso_nome'], 'Antincendio')
        altrui = self._client(self.f_fuori).get('/api/ehs/calendario/', params).json()
        self.assertEqual(altrui[0]['attivita_nome'], 'Occupato')
        self.assertEqual(altrui[0]['location_display'], 'Firenze')
        self.assertTrue(altrui[0]['occupato'])
        self.assertIsNone(altrui[0]['ehs_sessione_id'])

    # --- scadenze ---

    def test_scadenze_45_giorni_solo_ultima_formazione(self):
        from .models import EHSFormazione
        oggi = timezone.now().date()
        # Corso con validità 365 giorni: fatto 345 giorni fa, scade tra 20.
        EHSFormazione.objects.create(utente=self.collaboratore, corso=self.corso,
                                     data=oggi - timedelta(days=345), fonte='import')
        sessione = self._conferma(self._crea(), giorni=10)
        EHSPartecipante.objects.create(sessione=sessione, utente=self.collaboratore)
        r = self._client(self.store_user).get('/api/ehs/scadenze/').json()
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]['giorni_mancanti'], 20)
        self.assertTrue(r[0]['rinnovo_pianificato'])
        # Un rinnovo con scadenza lontana fa sparire l'alert
        EHSFormazione.objects.create(utente=self.collaboratore, corso=self.corso,
                                     data=oggi - timedelta(days=65), fonte='manuale')
        self.assertEqual(self._client(self.store_user).get('/api/ehs/scadenze/').json(), [])

    def test_notifiche_scadenza_dal_registro_una_volta_al_giorno(self):
        from .models import EHSConfigurazione, EHSFormazione, EHSNotificaScadenza
        oggi = timezone.now().date()
        EHSFormazione.objects.create(utente=self.collaboratore, corso=self.corso,
                                     data=oggi - timedelta(days=345), fonte='import')
        # Già scaduta: resta nel pannello ma non genera popup.
        altro = EHSCorso.objects.create(codice='EHS0002', nome='Primo soccorso', durata_ore=4, scadenza_giorni=365)
        EHSFormazione.objects.create(utente=self.collaboratore, corso=altro,
                                     data=oggi - timedelta(days=400), fonte='import')
        EHSConfigurazione.objects.update_or_create(pk=1, defaults={'ultimo_controllo_giornaliero': None})
        self.assertEqual(services.esegui_automatismi_giornalieri(), 1)
        self.assertIsNone(services.esegui_automatismi_giornalieri())  # stesso giorno: non riparte
        self.assertEqual(EHSNotificaScadenza.objects.count(), 1)
        popup = self._client(self.store_user).get('/api/ehs/notifiche-scadenza/').json()
        self.assertEqual([(p['corso_nome'], p['utente_nome']) for p in popup], [('Antincendio', 'Rossi Mario')])

    # --- gestione corsi con offerte ---

    def test_crea_corso_con_offerte(self):
        c = self._client(self.admin_ehs)
        r = c.post('/api/ehs/corsi/', {
            'nome': 'Primo soccorso', 'durata_ore': '8',
            'offerte': [{'fornitore': self.f_rete.id, 'tutti_negozi': False, 'negozi': [self.negozio.id]}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['offerte'][0]['negozi'], [self.negozio.id])
        # Senza fornitori il corso si crea, ma non è richiedibile.
        r = c.post('/api/ehs/corsi/', {'nome': 'Senza', 'durata_ore': '0.25', 'offerte': []}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        richiedibili = [x['nome'] for x in c.get('/api/ehs/corsi/', {'richiedibili': 1}).json()]
        self.assertIn('Primo soccorso', richiedibili)
        self.assertNotIn('Senza', richiedibili)
        r = c.post('/api/ehs/corsi/', {
            'nome': 'Vuoto', 'durata_ore': '1',
            'offerte': [{'fornitore': self.f_rete.id, 'tutti_negozi': False, 'negozi': []}],
        }, format='json')
        self.assertEqual(r.status_code, 400)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EHS_EMAIL_ATTIVE=False)
class EHSEmailBloccateTest(TestCase):
    def test_nessuna_email_con_interruttore_spento(self):
        negozio = Store.objects.create(nome='Fi', comune='Fi', provincia='FI', email_store='fi@s.it')
        store_user = User.objects.create_user(email='s@x.it', password='x', cognome='S', nome='S',
                                              livello_accesso='store', store=negozio)
        f = User.objects.create_user(email='f@x.it', password='x', cognome='F', nome='F', livello_accesso='fornitore')
        corso = EHSCorso.objects.create(codice='EHS0002', nome='C', durata_ore=2)
        EHSOffertaCorso.objects.create(corso=corso, fornitore=f)
        with self.captureOnCommitCallbacks(execute=True):
            sessione = services.crea_richiesta(store_user, corso, negozio, 'Ref', '')
            services.dichiara_non_disponibile(sessione, f)
        self.assertEqual(mail.outbox, [])


class EHSFormazioneObbligatoriaTest(TestCase):
    def setUp(self):
        from users.models import Role
        from .models import EHSMansione
        self.negozio = Store.objects.create(nome='Caserta', comune='Caserta', provincia='CE', email_store='ce@store.it')
        self.altro = Store.objects.create(nome='Roma', comune='Roma', provincia='RM', email_store='rm2@store.it')
        self.tm = Role.objects.get_or_create(nome='Team Manager')[0]
        self.ra = Role.objects.get_or_create(nome='Retail Assistant')[0]
        self.store_user = User.objects.create_user(
            email='st@x.it', password='x', cognome='Store', nome='Ce', livello_accesso='store', store=self.negozio)
        self.area = User.objects.create_user(email='area@x.it', password='x', cognome='A', nome='A', livello_accesso='area')
        self.admin_ehs = User.objects.create_user(
            email='ae@x.it', password='x', cognome='E', nome='E', livello_accesso='admin_ehs')
        self.tm_user = User.objects.create_user(
            email='tm@x.it', password='x', cognome='Bianchi', nome='Anna', store=self.negozio, ruolo=self.tm)
        self.ra_user = User.objects.create_user(
            email='ra@x.it', password='x', cognome='Verdi', nome='Luca', store=self.negozio, ruolo=self.ra)
        self.altro_user = User.objects.create_user(
            email='ro@x.it', password='x', cognome='Neri', nome='Sara', store=self.altro, ruolo=self.tm)
        self.corso = EHSCorso.objects.create(codice='PREP', nome='Preposti test', durata_ore=12, scadenza_giorni=730)
        self.mansione = EHSMansione.objects.create(nome='Stockroom test')

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_scadenza_calcolata_dal_corso(self):
        from .models import EHSFormazione
        f = EHSFormazione.objects.create(utente=self.tm_user, corso=self.corso,
                                         data=timezone.now().date(), fonte='manuale')
        self.assertEqual(f.scadenza, f.data + timedelta(days=730))

    def test_chiusura_aula_registra_formazione(self):
        fornitore = User.objects.create_user(
            email='f@x.it', password='x', cognome='F', nome='F', livello_accesso='fornitore', fornitore_ragione_sociale='F')
        EHSOffertaCorso.objects.create(corso=self.corso, fornitore=fornitore)
        sessione = services.crea_richiesta(self.store_user, self.corso, self.negozio, 'Ref', '', fornitore=fornitore)
        services.proponi_data(sessione, fornitore, _prossima_mezzora(5), 'Doc', '333',
                              partecipanti_min=3, partecipanti_max=10)
        services.rispondi_data(sessione, self.store_user, accetta=True)
        sessione.refresh_from_db()
        p = EHSPartecipante.objects.create(sessione=sessione, utente=self.tm_user)
        services.chiudi_aula(sessione, {p.id: True}, [SimpleUploadedFile('r.pdf', b'x')], fornitore)
        f = self.tm_user.ehs_formazioni.get()
        self.assertEqual((f.corso, f.fonte, f.partecipante), (self.corso, 'aula', p))
        self.assertIsNotNone(f.scadenza)

    def test_matrice_modificabile_solo_da_admin_ehs(self):
        body = {'corso': self.corso.id, 'ruolo': self.tm.id, 'stato': 'obbligatorio'}
        self.assertEqual(self._client(self.area).put('/api/ehs/matrice/', body, format='json').status_code, 403)
        self.assertEqual(self._client(self.admin_ehs).put('/api/ehs/matrice/', body, format='json').status_code, 200)
        self.assertTrue(self.corso.obblighi.filter(ruolo=self.tm, facoltativo=False).exists())
        body['stato'] = None
        self._client(self.admin_ehs).put('/api/ehs/matrice/', body, format='json')
        self.assertFalse(self.corso.obblighi.exists())
        r = self._client(self.area).get('/api/ehs/matrice/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('Retail Assistant', [x['nome'] for x in r.json()['ruoli']])

    def test_persone_escludono_retail_assistant_e_store_vede_solo_il_suo(self):
        ids = [p['id'] for p in self._client(self.store_user).get('/api/ehs/persone/', {'negozio': self.altro.id}).json()]
        self.assertEqual(ids, [self.tm_user.id])
        ids = [p['id'] for p in self._client(self.area).get('/api/ehs/persone/', {'negozio': self.altro.id}).json()]
        self.assertEqual(ids, [self.altro_user.id])

    def test_mansioni_store_solo_propri_collaboratori(self):
        url = '/api/ehs/persone/{}/mansioni/'
        c = self._client(self.store_user)
        self.assertEqual(c.put(url.format(self.tm_user.id), {'mansioni': [self.mansione.id]}, format='json').status_code, 200)
        self.assertEqual(c.put(url.format(self.altro_user.id), {'mansioni': [self.mansione.id]}, format='json').status_code, 403)
        self.assertEqual(list(self.tm_user.ehs_mansioni.all()), [self.mansione])

    def test_stati_e_completamento(self):
        from .models import EHSFormazione, EHSObbligo
        EHSObbligo.objects.create(corso=self.corso, ruolo=self.tm)
        oggi = timezone.now().date()
        stati = services.calcola_stati([self.tm_user, self.altro_user])
        self.assertEqual(stati[self.tm_user.id][self.corso.id]['stato'], 'mancante')
        # 700 giorni fa con validità 730: scade tra 30 giorni -> in scadenza (soglia 45)
        EHSFormazione.objects.create(utente=self.tm_user, corso=self.corso, data=oggi - timedelta(days=700), fonte='manuale')
        EHSFormazione.objects.create(utente=self.altro_user, corso=self.corso, data=oggi - timedelta(days=800), fonte='manuale')
        stati = services.calcola_stati([self.tm_user, self.altro_user])
        self.assertEqual(stati[self.tm_user.id][self.corso.id]['stato'], 'in_scadenza')
        self.assertEqual(stati[self.altro_user.id][self.corso.id]['stato'], 'scaduta')
        r = services.riepiloga(stati.values(), [self.corso.id])[self.corso.id]
        self.assertEqual((r['dovuti'], r['conformi'], r['percentuale']), (2, 1, 50))

    def test_permessi_completamento(self):
        self.assertEqual(self._client(self.store_user).get('/api/ehs/completamento/').status_code, 403)
        self.assertEqual(self._client(self.area).get('/api/ehs/completamento/').status_code, 200)
        url = '/api/ehs/completamento/negozio/{}/'
        self.assertEqual(self._client(self.store_user).get(url.format(self.negozio.id)).status_code, 200)
        self.assertEqual(self._client(self.store_user).get(url.format(self.altro.id)).status_code, 403)
        persone = self._client(self.area).get(url.format(self.negozio.id)).json()['persone']
        self.assertEqual([p['id'] for p in persone], [self.tm_user.id])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EHS_EMAIL_ATTIVE=True)
class EHSRegoleAuleTest(TestCase):
    """Fornitori secondari, minimo/massimo partecipanti, rinnovo anticipato, richieste EHS."""
    setUp = EHSFlussiTest.setUp
    _client = EHSFlussiTest._client
    _crea = EHSFlussiTest._crea

    def _conferma(self, sessione, giorni=10, minimo=3, massimo=10):
        services.proponi_data(sessione, self.f_rete, _prossima_mezzora(giorni), 'Doc', '333',
                              partecipanti_min=minimo, partecipanti_max=massimo)
        services.rispondi_data(sessione, self.store_user, accetta=True)
        sessione.refresh_from_db()
        return sessione

    def _iscrivi(self, sessione, n):
        for i in range(n):
            u = User.objects.create_user(email=f'p{sessione.id}_{i}@x.it', password='x', cognome=f'P{i}', nome='X',
                                         store=self.negozio)
            Iscrizione.objects.create(evento=sessione.calendario_evento, user=u, stato='iscritto')

    def test_fornitore_secondario_va_validato(self):
        f_sec = User.objects.create_user(email='sec@forn.it', password='x', cognome='S', nome='S',
                                         livello_accesso='fornitore', fornitore_ragione_sociale='Sec Srl')
        EHSOffertaCorso.objects.create(corso=self.corso, fornitore=f_sec, secondario=True)
        sessione = self._crea(fornitore=f_sec)
        self.assertEqual((sessione.stato, sessione.fornitore, sessione.fornitore_secondario),
                         ('IN_APPROVAZIONE', None, True))
        services.decidi_eccezione(sessione, self.admin_ehs, approva=False, nota='usa il principale')
        self.assertEqual((sessione.stato, sessione.fornitore), ('RICHIESTA_INVIATA', None))
        services.assegna_fornitore(sessione, self.store_user, f_sec)
        self.assertEqual(sessione.stato, 'IN_APPROVAZIONE')
        services.decidi_eccezione(sessione, self.admin_ehs, approva=True)
        self.assertEqual((sessione.stato, sessione.fornitore), ('RICHIESTA_INVIATA', f_sec))
        # il principale non va validato ed è l'unico assegnato in automatico
        self.assertEqual(self._crea().fornitore, self.f_rete)

    def test_minimo_e_massimo_dal_fornitore(self):
        sessione = self._crea()
        with self.assertRaises(TransizioneNonValida):
            services.proponi_data(sessione, self.f_rete, _prossima_mezzora(10), 'Doc', '333',
                                  partecipanti_min=2, partecipanti_max=10)
        with self.assertRaises(TransizioneNonValida):
            services.proponi_data(sessione, self.f_rete, _prossima_mezzora(10), 'Doc', '333',
                                  partecipanti_min=5, partecipanti_max=4)
        sessione = self._conferma(sessione, massimo=3)
        self.assertEqual(sessione.calendario_evento.max_partecipanti, 3)
        self._iscrivi(sessione, 3)
        r = self._client(self.store_user).post('/api/iscrizioni/', {
            'evento': sessione.calendario_evento_id, 'user': self.collaboratore.id, 'stato': 'iscritto'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('Posti esauriti', r.json()['detail'])

    def test_avviso_e_annullamento_sotto_minimo(self):
        from .models import EHSAvviso
        lontana = self._conferma(self._crea(), giorni=10)
        vicina = self._conferma(self._crea(), giorni=4)
        piena = self._conferma(self._crea(), giorni=4)
        self._iscrivi(vicina, 2)
        self._iscrivi(piena, 3)
        self.assertEqual(services.controlla_minimo_partecipanti(), (1, 0))
        avvisi = EHSAvviso.objects.filter(sessione=vicina, tipo='minimo_partecipanti')
        self.assertEqual({(a.negozio_id, a.utente_id) for a in avvisi},
                         {(self.negozio.id, None), (None, self.admin_ehs.id), (None, self.f_rete.id)})
        self.assertEqual(self._client(self.store_user).get('/api/ehs/avvisi/').json()[0]['tipo'],
                         'minimo_partecipanti')
        # stesso giorno nessun annullamento, il giorno dopo sì
        self.assertEqual(services.controlla_minimo_partecipanti(), (0, 0))
        self.assertEqual(services.controlla_minimo_partecipanti(timezone.now() + timedelta(days=1)), (0, 1))
        for s in (lontana, vicina, piena):
            s.refresh_from_db()
        self.assertEqual((lontana.stato, vicina.stato, piena.stato), ('CONFERMATA', 'ANNULLATA', 'CONFERMATA'))
        self.assertIsNone(vicina.calendario_evento)
        self.assertEqual(EHSAvviso.objects.filter(sessione=vicina, tipo='annullata_minimo').count(), 3)

    def test_rinnovo_solo_negli_ultimi_120_giorni(self):
        from .models import EHSFormazione
        sessione = self._conferma(self._crea(), giorni=10)
        f = EHSFormazione.objects.create(utente=self.collaboratore, corso=self.corso, fonte='manuale',
                                         data=timezone.now().date())  # valida per altri 365 giorni
        dati = {'evento': sessione.calendario_evento_id, 'user': self.collaboratore.id, 'stato': 'iscritto'}
        r = self._client(self.store_user).post('/api/iscrizioni/', dati)
        self.assertEqual(r.status_code, 400)
        self.assertIn('120 giorni', r.json()['detail'])
        v = self._client(self.store_user).get('/api/ehs/verifica-partecipante/', {
            'utente': self.collaboratore.id, 'corso': self.corso.id, 'evento': sessione.calendario_evento_id}).json()
        self.assertTrue(v['bloccato'])
        f.data = timezone.now().date() - timedelta(days=300)  # scade tra 65 giorni
        f.save()
        self.assertEqual(self._client(self.store_user).post('/api/iscrizioni/', dati).status_code, 201)

    def test_richieste_cancellazione_ehs_all_admin_ehs(self):
        from participants.models import RichiestaCancellazione
        ho = User.objects.create_user(email='ho@x.it', password='x', cognome='H', nome='O', livello_accesso='ho')
        ehs = RichiestaCancellazione.objects.create(richiedente=self.store_user, motivazione='x', snap_tipologia='ehs')
        altra = RichiestaCancellazione.objects.create(richiedente=self.store_user, motivazione='x', snap_tipologia='ld')

        def visibili(u):
            return {x['id'] for x in self._client(u).get('/api/richieste-cancellazione/').json()}

        def decidi(u, r):
            return self._client(u).patch(f'/api/richieste-cancellazione/{r.id}/', {'stato': 'rifiutata'}).status_code

        self.assertEqual(visibili(self.admin_ehs), {ehs.id})
        self.assertEqual(visibili(ho), {altra.id})
        self.assertEqual(decidi(ho, ehs), 403)
        self.assertEqual(decidi(self.admin_ehs, altra), 403)
        self.assertEqual(decidi(self.admin_ehs, ehs), 200)

    def test_cerca_formazioni_e_matrice_per_tutti(self):
        sessione = self._conferma(self._crea(), giorni=10)
        altro_store = User.objects.create_user(email='rm@x.it', password='x', cognome='S', nome='R',
                                               livello_accesso='store', store=self.altro_negozio)
        trovate = self._client(altro_store).get('/api/ehs/cerca-formazioni/', {'citta': 'fire'}).json()
        self.assertEqual([t['id'] for t in trovate], [sessione.id])
        self.assertEqual((trovate[0]['minimo'], trovate[0]['massimo'], trovate[0]['mio_negozio']), (3, 10, False))
        self.assertEqual(self._client(altro_store).get('/api/ehs/cerca-formazioni/', {'citta': 'roma'}).json(), [])
        self.assertEqual(self._client(self.collaboratore).get('/api/ehs/matrice/').status_code, 200)

    def test_fornitore_conferma_la_data_dello_store_e_sceglie_la_modalita(self):
        data_store = _prossima_mezzora(12)
        sessione = self._crea(data_suggerita_store=data_store)
        with self.assertRaises(TransizioneNonValida):  # online senza link
            services.proponi_data(sessione, self.f_rete, data_store, 'Doc', '333', partecipanti_min=3,
                                  partecipanti_max=8, modalita='ONLINE')
        services.proponi_data(sessione, self.f_rete, data_store, 'Doc', '333', partecipanti_min=3,
                              partecipanti_max=8, modalita='ONLINE', link_online='https://call.example/x')
        sessione.refresh_from_db()
        self.assertEqual((sessione.stato, sessione.modalita, sessione.data_confermata),
                         ('CONFERMATA', 'ONLINE', data_store))
        self.assertEqual(sessione.calendario_evento.ehs_luogo, 'Online')
        # data diversa da quella dello store: resta una proposta da accettare
        altra = self._crea(data_suggerita_store=data_store)
        services.proponi_data(altra, self.f_rete, _prossima_mezzora(13), 'Doc', '333', partecipanti_min=3,
                              partecipanti_max=8, modalita='PRESENZA')
        self.assertEqual(altra.stato, 'DATA_PROPOSTA')
