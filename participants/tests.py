from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from events.models import AttivitaCatalogo, Evento, Host
from stores.models import Store

User = get_user_model()


class IscrizionePostiTest(TestCase):
    """Ogni evento del calendario è aperto all'iscrizione di tutti gli store,
    fino a esaurimento dei posti disponibili."""

    def setUp(self):
        self.negozio_a = Store.objects.create(nome='Firenze', comune='Firenze', provincia='FI', email_store='fi@store.it')
        self.negozio_b = Store.objects.create(nome='Roma', comune='Roma', provincia='RM', email_store='rm@store.it')
        self.store_a = User.objects.create_user(
            email='a@x.it', password='x', cognome='A', nome='A', livello_accesso='store', store=self.negozio_a)
        self.store_b = User.objects.create_user(
            email='b@x.it', password='x', cognome='B', nome='B', livello_accesso='store', store=self.negozio_b)
        self.persona_a = User.objects.create_user(
            email='pa@x.it', password='x', cognome='Rossi', nome='Anna', store=self.negozio_a)
        self.persona_b = User.objects.create_user(
            email='pb@x.it', password='x', cognome='Verdi', nome='Bruno', store=self.negozio_b)
        attivita = AttivitaCatalogo.objects.create(nome='Corso vendita', tipologia='ld')
        host = Host.objects.create(descrizione='Trainer', posizione='interno')
        # Evento ospitato dal negozio A, con un solo posto.
        self.evento = Evento.objects.create(
            data=date.today() + timedelta(days=30), ora_inizio=time(9), ora_fine=time(13),
            attivita=attivita, host=host, location_store=self.negozio_a, max_partecipanti=1)

    def _iscrivi(self, store_user, persona):
        c = APIClient()
        c.force_authenticate(store_user)
        return c.post('/api/iscrizioni/', {'evento': self.evento.id, 'user': persona.id, 'stato': 'iscritto'})

    def test_store_di_altro_negozio_puo_iscrivere(self):
        self.assertEqual(self._iscrivi(self.store_b, self.persona_b).status_code, 201)

    def test_posti_esauriti_bloccano_iscrizione(self):
        self.assertEqual(self._iscrivi(self.store_b, self.persona_b).status_code, 201)
        r = self._iscrivi(self.store_a, self.persona_a)
        self.assertEqual(r.status_code, 400)
        self.assertIn('Posti esauriti', str(r.data))

    def test_senza_limite_posti(self):
        self.evento.max_partecipanti = 0
        self.evento.save()
        self.assertEqual(self._iscrivi(self.store_b, self.persona_b).status_code, 201)
        self.assertEqual(self._iscrivi(self.store_a, self.persona_a).status_code, 201)
