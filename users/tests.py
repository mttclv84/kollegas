from datetime import date, time, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from events.models import AttivitaCatalogo, Evento, Host
from stores.models import Store

from .models import AuditLog, User


class AuditAutomaticoTest(TestCase):
    def setUp(self):
        self.negozio = Store.objects.create(nome='Roma', comune='Roma', provincia='RM', email_store='rm@x.it')
        self.store_user = User.objects.create_user(email='s@x.it', password='x', cognome='Store', nome='Roma',
                                                   livello_accesso='store', store=self.negozio)
        self.persona = User.objects.create_user(email='p@x.it', password='x', cognome='Verdi', nome='Bruno',
                                                store=self.negozio)
        self.evento = Evento.objects.create(
            data=date.today() + timedelta(days=10), ora_inizio=time(9), ora_fine=time(13),
            attivita=AttivitaCatalogo.objects.create(nome='Corso vendita', tipologia='ld'),
            host=Host.objects.create(descrizione='Trainer', posizione='interno'))

    def test_iscrizione_di_uno_store_finisce_nel_log(self):
        c = APIClient()
        c.force_authenticate(self.store_user)
        r = c.post('/api/iscrizioni/', {'evento': self.evento.id, 'user': self.persona.id, 'stato': 'iscritto'},
                   format='json')
        self.assertEqual(r.status_code, 201)
        log = AuditLog.objects.get()
        self.assertEqual((log.actor, log.azione, log.target_tipo), (self.store_user, 'crea', 'Iscrizione'))
        self.assertIn('Verdi Bruno', log.target_repr)

    def test_operazione_fallita_non_registrata(self):
        c = APIClient()
        c.force_authenticate(self.store_user)
        c.post('/api/eventi/', {}, format='json')  # lo store non crea formazioni: 403
        self.assertFalse(AuditLog.objects.exists())

    def test_accesso_registrato(self):
        r = APIClient().post('/api/auth/login/', {'email': 's@x.it', 'password': 'x'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(AuditLog.objects.get().azione, 'accesso')


class AccessoProfiliBaseTest(TestCase):
    def setUp(self):
        self.base = User.objects.create_user(email='base@x.it', password='x', cognome='B', nome='B')
        self.store = User.objects.create_user(email='store@x.it', password='x', cognome='S', nome='S',
                                              livello_accesso='store')

    def _login(self, email, password='x'):
        return APIClient().post('/api/auth/login/', {'email': email, 'password': password}, format='json')

    def test_base_non_entra_e_non_viene_registrato_accesso(self):
        r = self._login('base@x.it')
        self.assertEqual(r.status_code, 403)
        self.assertIn('non ha accesso', r.data['detail'])
        self.assertNotIn('access', r.data)
        self.assertFalse(AuditLog.objects.filter(actor=self.base).exists())

    def test_password_errata_non_rivela_il_livello(self):
        self.assertEqual(self._login('base@x.it', 'sbagliata').status_code, 401)

    def test_sessione_gia_aperta_viene_chiusa(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken.for_user(self.base)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        self.assertEqual(c.get('/api/me/').status_code, 401)
        self.assertEqual(APIClient().post('/api/auth/refresh/', {'refresh': str(token)}, format='json').status_code, 401)

    def test_altri_profili_entrano(self):
        r = self._login('store@x.it')
        self.assertEqual(r.status_code, 200)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.assertEqual(c.get('/api/me/').status_code, 200)


class HOSolaVisioneEHSTest(TestCase):
    def setUp(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from participants.models import Iscrizione
        self.ho = User.objects.create_user(email='ho@x.it', password='x', cognome='H', nome='O', livello_accesso='ho')
        self.persona = User.objects.create_user(email='p@x.it', password='x', cognome='P', nome='P')
        self.altra = User.objects.create_user(email='q@x.it', password='x', cognome='Q', nome='Q')
        host = Host.objects.create(descrizione='T', posizione='interno')

        def evento(tipologia, is_ehs):
            return Evento.objects.create(
                data=date.today() + timedelta(days=1), ora_inizio=time(9), ora_fine=time(13), is_ehs=is_ehs, host=host,
                attivita=AttivitaCatalogo.objects.create(nome=f'Corso {tipologia}', tipologia=tipologia))

        self.ehs = evento('ehs', True)
        self.normale = evento('ld', False)
        self.iscrizione_ehs = Iscrizione.objects.create(evento=self.ehs, user=self.persona, stato='assente')
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.ho).access_token}')

    def test_legge_ma_non_scrive_nelle_api_ehs(self):
        self.assertEqual(self.c.get('/api/ehs/corsi/').status_code, 200)
        self.assertEqual(self.c.get('/api/ehs/fornitori/').status_code, 200)
        for metodo, url in (('post', '/api/ehs/corsi/'), ('post', '/api/ehs/sessioni/'), ('post', '/api/ehs/fornitori/'),
                            ('patch', '/api/ehs/sessioni/1/annulla/'), ('delete', '/api/ehs/fornitori/1/')):
            self.assertEqual(getattr(self.c, metodo)(url, {}, format='json').status_code, 403, url)

    def test_non_tocca_iscrizioni_ed_eventi_ehs(self):
        from participants.models import Iscrizione
        dati = {'evento': self.ehs.id, 'user': self.altra.id, 'stato': 'iscritto'}
        self.assertEqual(self.c.post('/api/iscrizioni/', dati, format='json').status_code, 403)
        self.assertEqual(self.c.patch(f'/api/iscrizioni/{self.iscrizione_ehs.id}/', {'stato': 'partecipato'},
                                      format='json').status_code, 403)
        self.assertEqual(self.c.post('/api/richieste-cancellazione/', {
            'iscrizione': self.iscrizione_ehs.id, 'motivazione': 'x'}, format='json').status_code, 403)
        self.assertEqual(self.c.patch(f'/api/eventi/{self.ehs.id}/', {'nota': 'x'}, format='json').status_code, 403)
        self.assertEqual(self.c.delete(f'/api/eventi/{self.ehs.id}/?motivazione=x').status_code, 403)
        self.c.delete('/api/iscrizioni/assenti/')
        self.assertTrue(Iscrizione.objects.filter(pk=self.iscrizione_ehs.pk).exists())

    def test_archivio_e_richieste_ehs_in_sola_visione(self):
        from participants.models import RichiestaCancellazione
        self.assertEqual(self.c.get('/api/ehs/archivio-documenti/').status_code, 200)
        self.assertEqual(self.c.post('/api/ehs/archivio-documenti/').status_code, 403)
        self.assertEqual(self.c.get('/api/ehs/archivio-documenti/1/zip/').status_code, 403)
        self.assertEqual(self.c.post('/api/ehs/archivio-documenti/1/svuota/', {}, format='json').status_code, 403)
        self.assertEqual(self.c.get('/api/ehs/sessioni/', {'stato': 'IN_APPROVAZIONE'}).status_code, 200)
        ehs = RichiestaCancellazione.objects.create(richiedente=self.persona, motivazione='x', snap_tipologia='ehs')
        altra = RichiestaCancellazione.objects.create(richiedente=self.persona, motivazione='x', snap_tipologia='ld')
        self.assertEqual({r['id'] for r in self.c.get('/api/richieste-cancellazione/', {'ambito': 'ehs'}).json()}, {ehs.id})
        self.assertEqual({r['id'] for r in self.c.get('/api/richieste-cancellazione/').json()}, {altra.id})
        self.assertEqual(self.c.patch(f'/api/richieste-cancellazione/{ehs.id}/', {'stato': 'rifiutata'},
                                      format='json').status_code, 403)

    def test_fuori_da_ehs_resta_operativo(self):
        dati = {'evento': self.normale.id, 'user': self.altra.id, 'stato': 'iscritto'}
        self.assertEqual(self.c.post('/api/iscrizioni/', dati, format='json').status_code, 201)
        self.assertEqual(self.c.patch(f'/api/eventi/{self.normale.id}/', {'nota': 'x'}, format='json').status_code, 200)


class StatsOrePersonaTest(TestCase):
    def test_ore_per_persone_e_ns_come_donne(self):
        from participants.models import Iscrizione
        from .views import _compute_stats
        evento = Evento.objects.create(  # 9-13, senza pausa pranzo = 4 ore
            data=date(2026, 1, 10), ora_inizio=time(9), ora_fine=time(13),
            attivita=AttivitaCatalogo.objects.create(nome='Corso', tipologia='ld'),
            host=Host.objects.create(descrizione='T', posizione='interno'))
        for i, sesso in enumerate(['M', 'F', 'NS']):
            u = User.objects.create_user(email=f'u{i}@x.it', password='x', cognome=f'C{i}', nome='N', sesso=sesso,
                                         is_active=(sesso != 'NS'))
            Iscrizione.objects.create(evento=evento, user=u, stato='partecipato')
        _, totale = _compute_stats({})
        self.assertEqual(totale['ore_erogate'], 12.0)  # 4 ore x 3 persone, disattivati compresi
        self.assertEqual((totale['maschi'], totale['femmine'], totale['ns']), (1, 2, 0))


class SolaLetturaTest(TestCase):
    """Il profilo guest (creato dalla migrazione) vede tutto come Admin ma non modifica né esporta."""

    def setUp(self):
        self.c = APIClient()
        r = self.c.post('/api/auth/login/', {'email': 'guest@primark.it', 'password': 'Primark01!'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['user']['sola_lettura'])
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    def test_legge_come_admin(self):
        self.assertEqual(self.c.get('/api/users/').status_code, 200)
        self.assertEqual(self.c.get('/api/users/audit/').status_code, 200)

    def test_non_scrive(self):
        conteggio = AttivitaCatalogo.objects.count()
        r = self.c.post('/api/attivita/', {'nome': 'Nuova', 'tipologia': 'ld'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(AttivitaCatalogo.objects.count(), conteggio)
        guest = User.objects.get(email='guest@primark.it')
        self.assertEqual(self.c.patch(f'/api/users/{guest.id}/', {'nome': 'X'}, format='json').status_code, 403)
        self.assertEqual(self.c.delete(f'/api/users/{guest.id}/').status_code, 403)

    def test_non_esporta(self):
        self.assertEqual(self.c.get('/api/report/excel/').status_code, 403)
        self.assertEqual(self.c.get('/api/stats/export/').status_code, 403)

    def test_password_non_visibili(self):
        guest = User.objects.get(email='guest@primark.it')
        self.assertFalse(self.c.get(f'/api/users/{guest.id}/').json().get('raw_password'))

    def test_development_solo_alaimo(self):
        negozio = Store.objects.create(nome='Torino', comune='Torino', provincia='TO', email_store='to@x.it')
        alaimo = User.objects.create_user(email='a@x.it', password='x', cognome='Alaimo', nome='Valentina', store=negozio)
        altro = User.objects.create_user(email='b@x.it', password='x', cognome='Rossi', nome='Valentina', store=negozio)
        r = self.c.get('/api/users/search/', {'nome': 'Rossi Mario'})
        self.assertEqual([u['id'] for u in r.json()], [alaimo.id])
        self.assertEqual(self.c.get(f'/api/users/{alaimo.id}/development/').status_code, 200)
        self.assertEqual(self.c.get(f'/api/users/{altro.id}/development/').status_code, 404)

    def test_dati_personali_anonimizzati(self):
        negozio = Store.objects.create(nome='Torino', comune='Torino', provincia='TO', email_store='to@x.it',
                                       portale_password='segreta')
        persona = User.objects.create_user(email='v.verdi@x.it', password='x', cognome='Verdi', nome='Bruno',
                                           store=negozio, telefono='333', codice_matricola='M1')
        u = self.c.get(f'/api/users/{persona.id}/').json()
        self.assertEqual((u['cognome'], u['nome'], u['email'], u['codice_matricola']), ('Rossi', 'Mario', '', ''))
        s = self.c.get(f'/api/stores/{negozio.id}/').json()
        self.assertEqual((s['nome'], s['email_store'], s['portale_password']), ('Torino', '', ''))
