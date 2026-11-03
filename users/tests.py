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


class StatsOrePersonaTest(TestCase):
    def test_ore_per_persone_e_ns_come_donne(self):
        from participants.models import Iscrizione
        from .views import _compute_stats
        evento = Evento.objects.create(  # 9-13 meno pausa = 3 ore
            data=date(2026, 1, 10), ora_inizio=time(9), ora_fine=time(13),
            attivita=AttivitaCatalogo.objects.create(nome='Corso', tipologia='ld'),
            host=Host.objects.create(descrizione='T', posizione='interno'))
        for i, sesso in enumerate(['M', 'F', 'NS']):
            u = User.objects.create_user(email=f'u{i}@x.it', password='x', cognome=f'C{i}', nome='N', sesso=sesso,
                                         is_active=(sesso != 'NS'))
            Iscrizione.objects.create(evento=evento, user=u, stato='partecipato')
        _, totale = _compute_stats({})
        self.assertEqual(totale['ore_erogate'], 9.0)  # 3 ore x 3 persone, disattivati compresi
        self.assertEqual((totale['maschi'], totale['femmine'], totale['ns']), (1, 2, 0))
