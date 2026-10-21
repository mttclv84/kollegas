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
        services.proponi_data(sessione, self.f_rete, _prossima_mezzora(giorni), 'Docente', '333', link_online=link)
        services.rispondi_data(sessione, self.store_user, accetta=True)
        sessione.refresh_from_db()
        return sessione

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
            services.proponi_data(sessione, self.f_rete, _prossima_mezzora(10), 'Doc', '333')
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
        sessione = self._conferma(self._crea(), giorni=10)
        oggi = timezone.now().date()
        vecchia = EHSPartecipante.objects.create(
            sessione=sessione, utente=self.collaboratore, completato=True,
            scadenza_formazione=oggi + timedelta(days=20))
        r = self._client(self.store_user).get('/api/ehs/scadenze/').json()
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]['giorni_mancanti'], 20)
        self.assertTrue(r[0]['rinnovo_pianificato'])
        # Un rinnovo con scadenza lontana fa sparire l'alert
        altra = EHSSessione.objects.create(corso=self.corso, negozio=self.negozio, creata_da=self.store_user,
                                           durata_ore=4, contatto_negozio_nome='x', contatto_negozio_telefono='',
                                           stato='COMPLETATA')
        EHSPartecipante.objects.create(sessione=altra, utente=self.collaboratore, completato=True,
                                       scadenza_formazione=oggi + timedelta(days=300))
        self.assertEqual(self._client(self.store_user).get('/api/ehs/scadenze/').json(), [])
        self.assertTrue(vecchia.pk)

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
        services.proponi_data(sessione, fornitore, _prossima_mezzora(5), 'Doc', '333')
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
