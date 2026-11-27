from datetime import date, time, timedelta

from django.test import TestCase, override_settings
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

    def test_audit_archivio_e_richieste_ehs_non_accessibili(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from participants.models import RichiestaCancellazione
        self.assertEqual(self.c.get('/api/users/audit/').status_code, 403)
        self.assertEqual(self.c.get('/api/ehs/archivio-documenti/').status_code, 403)
        ehs = RichiestaCancellazione.objects.create(richiedente=self.persona, motivazione='x', snap_tipologia='ehs')
        altra = RichiestaCancellazione.objects.create(richiedente=self.persona, motivazione='x', snap_tipologia='ld')
        self.assertEqual({r['id'] for r in self.c.get('/api/richieste-cancellazione/', {'ambito': 'ehs'}).json()}, set())
        self.assertEqual({r['id'] for r in self.c.get('/api/richieste-cancellazione/').json()}, set())  # solo formazioni proprie
        self.assertNotEqual(ehs.id, altra.id)
        admin_ehs = User.objects.create_user(email='ae@x.it', password='x', cognome='A', nome='E', livello_accesso='admin_ehs')
        admin = User.objects.create_user(email='ad@x.it', password='x', cognome='A', nome='D', livello_accesso='admin')
        for utente, atteso in ((admin_ehs, 403), (admin, 200)):
            c = APIClient()
            c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(utente).access_token}')
            self.assertEqual(c.get('/api/users/audit/').status_code, atteso)

    def test_fuori_da_ehs_resta_operativo(self):
        dati = {'evento': self.normale.id, 'user': self.altra.id, 'stato': 'iscritto'}
        self.assertEqual(self.c.post('/api/iscrizioni/', dati, format='json').status_code, 201)
        Evento.objects.filter(pk=self.normale.pk).update(created_by=self.ho)  # gli HO modificano solo le proprie
        self.assertEqual(self.c.patch(f'/api/eventi/{self.normale.id}/', {'nota': 'x'}, format='json').status_code, 200)


@override_settings(KOLLEGAS_PASSWORD_COMUNE='Comune-Test-9x')
class PasswordTemporaneaTest(TestCase):
    NUOVA = 'Girasole-Blu-47'

    def setUp(self):
        self.negozio = Store.objects.create(nome='Roma', comune='Roma', provincia='RM', email_store='rm@x.it')
        self.admin = User.objects.create_user(email='admin@x.it', password='Admin-Pwd-77', cognome='A', nome='A',
                                              livello_accesso='admin')
        self.utente = User.objects.create_user(email='area@x.it', password='x', cognome='Rossi', nome='Anna',
                                               livello_accesso='area', store=self.negozio)
        self.utente.imposta_password_temporanea('Comune-Test-9x')
        self.utente.save()

    def _login(self, email='area@x.it', password='Comune-Test-9x'):
        return APIClient().post('/api/auth/login/', {'email': email, 'password': password}, format='json')

    def _client(self, access):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        return c

    def _admin(self):
        return self._client(self._login('admin@x.it', 'Admin-Pwd-77').data['access'])

    def test_obbligo_di_cambio_al_primo_accesso(self):
        r = self._login()
        self.assertTrue(r.data['user']['deve_cambiare_password'])
        c = self._client(r.data['access'])
        bloccata = c.get('/api/stores/')
        self.assertEqual((bloccata.status_code, bloccata.data['codice']), (403, 'cambio_password_richiesto'))
        self.assertEqual(c.get('/api/me/').status_code, 200)
        url = '/api/auth/cambia-password/'
        self.assertEqual(c.post(url, {'password_attuale': 'no', 'nuova_password': self.NUOVA}, format='json').status_code, 400)
        for debole in ('Comune-Test-9x', 'Primark99!', '12345678'):
            self.assertEqual(c.post(url, {'password_attuale': 'Comune-Test-9x', 'nuova_password': debole},
                                    format='json').status_code, 400, debole)
        ok = c.post(url, {'password_attuale': 'Comune-Test-9x', 'nuova_password': self.NUOVA}, format='json')
        self.assertEqual(ok.status_code, 200)
        self.assertFalse(ok.data['user']['deve_cambiare_password'])
        self.assertEqual(self._client(ok.data['access']).get('/api/stores/').status_code, 200)
        self.utente.refresh_from_db()
        self.assertEqual(self.utente.raw_password, '')
        self.assertEqual(self._login().status_code, 401)
        self.assertEqual(self._login(password=self.NUOVA).status_code, 200)

    def test_vecchia_sessione_chiusa_dopo_il_cambio(self):
        from datetime import timedelta as td
        from django.utils import timezone
        from rest_framework_simplejwt.tokens import RefreshToken
        vecchio = RefreshToken.for_user(self.utente)
        User.objects.filter(pk=self.utente.pk).update(
            deve_cambiare_password=False, password_cambiata_il=timezone.now() + td(seconds=5))
        self.assertEqual(self._client(vecchio.access_token).get('/api/me/').status_code, 401)

    def test_password_temporanea_scaduta(self):
        from datetime import timedelta as td
        from django.utils import timezone
        access = self._login().data['access']
        User.objects.filter(pk=self.utente.pk).update(password_scadenza=timezone.now() - td(minutes=1))
        r = self._login()
        self.assertEqual(r.status_code, 403)
        self.assertIn('scaduta', r.data['detail'])
        self.assertEqual(self._client(access).get('/api/me/').status_code, 401)

    def test_admin_non_scade(self):
        self.admin.imposta_password_temporanea('Admin-Pwd-77')
        self.assertIsNone(self.admin.password_scadenza)

    def test_richiesta_reset_e_password_individuale(self):
        from .models import RichiestaResetPassword
        base = User.objects.create_user(email='b@x.it', password='x', cognome='B', nome='B')
        url = '/api/auth/richiedi-reset/'
        risposte = [APIClient().post(url, {'email': e}, format='json') for e in ('AREA@x.it', 'area@x.it', 'ignoto@x.it', base.email)]
        self.assertEqual(len({(r.status_code, r.data['detail']) for r in risposte}), 1)
        richiesta = RichiestaResetPassword.objects.get()
        self.assertEqual(richiesta.user, self.utente)
        ho = User.objects.create_user(email='ho@x.it', password='Ho-Pwd-5533', cognome='H', nome='O', livello_accesso='ho')
        c_ho = self._client(self._login(ho.email, 'Ho-Pwd-5533').data['access'])
        self.assertEqual(c_ho.get('/api/richieste-reset-password/').status_code, 403)
        self.assertEqual(c_ho.post(f'/api/richieste-reset-password/{richiesta.id}/', {'azione': 'reset'}, format='json').status_code, 403)
        admin = self._admin()
        self.assertEqual(len(admin.get('/api/richieste-reset-password/').json()), 1)
        r = admin.post(f'/api/richieste-reset-password/{richiesta.id}/', {'azione': 'reset'}, format='json')
        nuova = r.data['password_temporanea']
        self.assertNotEqual(nuova, 'Comune-Test-9x')
        self.assertEqual(admin.get('/api/richieste-reset-password/').json(), [])
        self.assertEqual(self._login().status_code, 401)
        self.assertTrue(self._login(password=nuova).data['user']['deve_cambiare_password'])
        self.assertFalse(AuditLog.objects.filter(dettaglio__contains=nuova).exists())

    def test_blocco_dopo_troppi_tentativi(self):
        for _ in range(10):
            self.assertEqual(self._login(password='errata').status_code, 401)
        self.assertEqual(self._login().status_code, 429)

    def test_solo_admin_reimposta_e_store_non_cambia_livello(self):
        account = User.objects.create_user(email='s@x.it', password='Store-Pwd-81', cognome='S', nome='S',
                                           livello_accesso='store', store=self.negozio)
        collega = User.objects.create_user(email='c@x.it', password='x', cognome='C', nome='C', store=self.negozio)
        c = self._client(self._login(account.email, 'Store-Pwd-81').data['access'])
        self.assertEqual(c.patch(f'/api/users/{collega.id}/', {'password': self.NUOVA}, format='json').status_code, 403)
        self.assertEqual(c.patch(f'/api/users/{collega.id}/', {'livello_accesso': 'admin'}, format='json').status_code, 400)
        c.patch('/api/me/', {'password': self.NUOVA}, format='json')
        account.refresh_from_db()
        collega.refresh_from_db()
        self.assertTrue(account.check_password('Store-Pwd-81'))
        self.assertFalse(collega.check_password(self.NUOVA))
        self.assertEqual(collega.livello_accesso, 'base')

    def test_proprio_profilo_non_modificabile_e_admin_protetto_da_ho(self):
        altro = Store.objects.create(nome='Milano', comune='Milano', provincia='MI', email_store='mi@x.it')
        account = User.objects.create_user(email='s@x.it', password='Store-Pwd-81', cognome='S', nome='S',
                                           livello_accesso='store', store=self.negozio)
        c = self._client(self._login(account.email, 'Store-Pwd-81').data['access'])
        self.assertEqual(c.patch('/api/me/', {'store': altro.id, 'is_active': False}, format='json').status_code, 405)
        account.refresh_from_db()
        self.assertEqual((account.store_id, account.is_active), (self.negozio.id, True))

        ho = User.objects.create_user(email='ho@x.it', password='Ho-Pwd-5533', cognome='H', nome='O', livello_accesso='ho')
        admin_ehs = User.objects.create_user(email='ae@x.it', password='x', cognome='A', nome='E', livello_accesso='admin_ehs')
        c_ho = self._client(self._login(ho.email, 'Ho-Pwd-5533').data['access'])
        for target in (self.admin, admin_ehs):
            self.assertEqual(c_ho.patch(f'/api/users/{target.id}/', {'livello_accesso': 'base'}, format='json').status_code, 403)
            self.assertEqual(c_ho.patch(f'/api/users/{target.id}/', {'email': 'x@x.it'}, format='json').status_code, 403)
            self.assertEqual(c_ho.delete(f'/api/users/{target.id}/').status_code, 403)
            target.refresh_from_db()
            self.assertTrue(target.is_active)
        self.assertEqual((self.admin.livello_accesso, self.admin.email), ('admin', 'admin@x.it'))
        # L'HO modifica solo i profili Base: l'Area Manager no.
        self.assertEqual(c_ho.patch(f'/api/users/{self.utente.id}/', {'nome': 'Anna Maria'}, format='json').status_code, 403)
        base = User.objects.create_user(email='base@x.it', password='x', cognome='B', nome='B', livello_accesso='base', store=self.negozio)
        self.assertEqual(c_ho.patch(f'/api/users/{base.id}/', {'nome': 'Bea'}, format='json').status_code, 200)

    def test_refresh_restituisce_un_nuovo_token_e_invalida_il_vecchio(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        self.utente.imposta_password_personale(self.NUOVA)
        self.utente.save()
        vecchio = str(RefreshToken.for_user(self.utente))
        r = APIClient().post('/api/auth/refresh/', {'refresh': vecchio}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('refresh', r.data)
        self.assertEqual(APIClient().post('/api/auth/refresh/', {'refresh': vecchio}, format='json').status_code, 401)
        self.assertEqual(APIClient().post('/api/auth/refresh/', {'refresh': r.data['refresh']}, format='json').status_code, 200)

    def test_modifica_negozio_non_riscrive_la_password(self):
        from stores.views import _sync_store_user
        self.negozio.portale_password = 'Vecchia-Pwd-1'
        self.negozio.save()
        account = User.objects.create(email='rm@x.it', cognome='Roma', livello_accesso='store', store=self.negozio)
        account.imposta_password_personale(self.NUOVA)
        account.save()
        _sync_store_user(self.negozio)
        account.refresh_from_db()
        self.assertTrue(account.check_password(self.NUOVA))

    def test_comando_di_lancio_con_data_di_scadenza(self):
        from datetime import timedelta as td
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from django.utils import timezone
        User.objects.filter(pk=self.utente.pk).update(password_cambiata_il=None, deve_cambiare_password=False,
                                                      password_scadenza=None)
        giorno = timezone.localdate() + td(days=20)
        with self.assertRaises(CommandError):
            call_command('avvia_password_temporanea', scadenza='2020-01-01', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('avvia_password_temporanea', scadenza='24/12/2026', stdout=StringIO())
        call_command('avvia_password_temporanea', scadenza=giorno.isoformat(), applica=True, stdout=StringIO())
        self.utente.refresh_from_db()
        fine = timezone.localtime(self.utente.password_scadenza)
        self.assertEqual((fine.date(), fine.hour, fine.minute), (giorno, 23, 59))

    def test_comando_di_lancio(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        User.objects.filter(pk=self.utente.pk).update(password_cambiata_il=None, deve_cambiare_password=False,
                                                      password_scadenza=None, raw_password='in-chiaro')
        base = User.objects.create_user(email='b@x.it', password='base-pwd', cognome='B', nome='B')
        fatto = User.objects.create_user(email='f@x.it', password='x', cognome='F', nome='F', livello_accesso='ho')
        fatto.imposta_password_personale(self.NUOVA)
        fatto.save()
        call_command('avvia_password_temporanea', stdout=StringIO())
        self.utente.refresh_from_db()
        self.assertFalse(self.utente.deve_cambiare_password)
        self.assertEqual(self.utente.raw_password, 'in-chiaro')
        call_command('avvia_password_temporanea', applica=True, stdout=StringIO())
        for u in (self.utente, self.admin, base, fatto):
            u.refresh_from_db()
        self.assertTrue(self.utente.deve_cambiare_password and self.utente.check_password('Comune-Test-9x'))
        self.assertIsNotNone(self.utente.password_scadenza)
        self.assertEqual(self.utente.raw_password, '')
        self.assertTrue(self.admin.deve_cambiare_password and self.admin.check_password('Admin-Pwd-77'))
        self.assertIsNone(self.admin.password_scadenza)
        self.assertTrue(base.check_password('base-pwd') and not base.deve_cambiare_password)
        self.assertTrue(fatto.check_password(self.NUOVA) and not fatto.deve_cambiare_password)
        with override_settings(KOLLEGAS_PASSWORD_COMUNE=''):
            with self.assertRaises(CommandError):
                call_command('avvia_password_temporanea', stdout=StringIO())


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


class LimitiHOTest(TestCase):
    """HO: crea e modifica solo profili Base, non elimina percorsi Development,
    decide solo le richieste di modifica delle formazioni create da sé."""

    def setUp(self):
        from rest_framework.test import APIClient
        self.negozio = Store.objects.create(nome='Roma', comune='Roma', provincia='RM', email_store='rm@x.it')
        self.ho = User.objects.create_user(email='ho@x.it', password='x', cognome='H', nome='O', livello_accesso='ho')
        self.ho2 = User.objects.create_user(email='ho2@x.it', password='x', cognome='H2', nome='O', livello_accesso='ho')
        self.store = User.objects.create_user(email='st@x.it', password='x', cognome='S', nome='T', livello_accesso='store',
                                              store=self.negozio)
        self.c = APIClient()
        self.c.force_authenticate(self.ho)

    def test_crea_solo_profili_base(self):
        dati = {'cognome': 'Nuovo', 'nome': 'N', 'store': self.negozio.id}
        self.assertEqual(self.c.post('/api/users/', {**dati, 'email': 'a@x.it', 'livello_accesso': 'area'}, format='json').status_code, 400)
        self.assertEqual(self.c.post('/api/users/', {**dati, 'email': 'b@x.it', 'livello_accesso': 'base'}, format='json').status_code, 201)
        self.assertEqual(self.c.patch(f'/api/users/{self.store.id}/', {'nome': 'X'}, format='json').status_code, 403)
        self.assertEqual(self.c.delete(f'/api/users/{self.store.id}/').status_code, 403)

    def test_richieste_profilo_solo_base(self):
        from .models import RichiestaCreazioneProfilo, RichiestaEliminazioneProfilo
        area = RichiestaCreazioneProfilo.objects.create(richiedente=self.store, cognome='A', nome='A', email='na@x.it',
                                                        livello_accesso='area', store=self.negozio)
        base = RichiestaCreazioneProfilo.objects.create(richiedente=self.store, cognome='B', nome='B', email='nb@x.it',
                                                        livello_accesso='base', store=self.negozio)
        self.assertEqual(self.c.get('/api/account-badge/').json()['count'], 1)
        self.assertEqual(self.c.patch(f'/api/richieste-creazione/{area.id}/', {'stato': 'rifiutata'}, format='json').status_code, 403)
        self.assertEqual(self.c.patch(f'/api/richieste-creazione/{base.id}/', {'stato': 'rifiutata'}, format='json').status_code, 200)
        elim = RichiestaEliminazioneProfilo.objects.create(richiedente=self.store, target_user=self.ho2, snap_nome='H2 O')
        self.assertEqual(self.c.patch(f'/api/richieste-eliminazione/{elim.id}/', {'stato': 'approvata'}, format='json').status_code, 403)
        self.ho2.refresh_from_db()
        self.assertTrue(self.ho2.is_active)

    def test_percorso_development_solo_admin(self):
        from .models import PercorsoCrescita
        from datetime import date
        p = PercorsoCrescita.objects.create(user=self.store, data=date.today(), tipo_evento='nota')
        self.assertEqual(self.c.delete(f'/api/percorso/{p.id}/').status_code, 403)
        self.assertTrue(PercorsoCrescita.objects.filter(pk=p.pk).exists())

    def test_richieste_di_modifica_solo_formazioni_proprie(self):
        from datetime import date, time
        from events.models import AttivitaCatalogo, Evento, Host
        from participants.models import Iscrizione, RichiestaCancellazione
        att = AttivitaCatalogo.objects.create(nome='CS', tipologia='ld')
        host = Host.objects.create(descrizione='T', posizione='interno')
        persona = User.objects.create_user(email='p@x.it', password='x', cognome='P', nome='P', livello_accesso='base',
                                           store=self.negozio)

        def richiesta(autore):
            ev = Evento.objects.create(data=date(2027, 3, 1), ora_inizio=time(9), ora_fine=time(13), attivita=att,
                                       host=host, created_by=autore)
            isc = Iscrizione.objects.create(evento=ev, user=persona, stato='iscritto')
            return RichiestaCancellazione.objects.create(iscrizione=isc, richiedente=self.store, motivazione='x',
                                                         snap_tipologia='ld')
        mia, altrui = richiesta(self.ho), richiesta(self.ho2)
        self.assertEqual({r['id'] for r in self.c.get('/api/richieste-cancellazione/').json()}, {mia.id})
        url = '/api/richieste-cancellazione/{}/'
        self.assertEqual(self.c.patch(url.format(altrui.id), {'stato': 'rifiutata'}, format='json').status_code, 403)
        self.assertEqual(self.c.patch(url.format(mia.id), {'stato': 'rifiutata'}, format='json').status_code, 200)
