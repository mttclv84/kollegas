from django.test import TestCase
from rest_framework.test import APIClient

from users.models import User


class AssistenzaTest(TestCase):
    def _client(self, livello, email):
        c = APIClient()
        u = User.objects.create_user(email=email, password='x', cognome=email.split('@')[0], nome='N', livello_accesso=livello)
        c.force_authenticate(u)
        return c

    def test_invio_risposta_e_stato(self):
        area, store, admin = self._client('area', 'area@a.it'), self._client('store', 'store@a.it'), self._client('admin', 'adm@a.it')
        url = '/api/assistenza/'
        self.assertEqual(area.post(url, {'tipo': 'idea', 'testo': 'Un grafico per area'}, format='json').status_code, 201)
        self.assertEqual(area.post(url, {'tipo': 'aiuto', 'testo': 'Non trovo il Dettaglio'}, format='json').status_code, 400)
        r = store.post(url, {'tipo': 'aiuto', 'sezione': 'Calendario', 'testo': 'Come iscrivo una persona?'}, format='json')
        self.assertEqual((r.status_code, r.data['sezione'], r.data['stato']), (201, 'Calendario', 'nuova'))
        self.assertEqual(area.post(url, {'tipo': 'suggerimento', 'testo': '   '}, format='json').status_code, 400)

        self.assertEqual([x['tipo'] for x in area.get(url).json()], ['idea'])  # solo le proprie
        self.assertEqual(len(admin.get(url).json()), 2)
        self.assertEqual(len(admin.get(url, {'tipo': 'aiuto'}).json()), 1)
        self.assertEqual(admin.get('/api/assistenza/contatori/').json()['da_vedere'], 2)

        dettaglio = f"/api/assistenza/{r.data['id']}/"
        self.assertEqual(store.patch(dettaglio, {'stato': 'completata'}, format='json').status_code, 403)
        risposta = admin.patch(dettaglio, {'risposta': 'Da Calendario apri la formazione.', 'stato': 'in_lavorazione'}, format='json')
        self.assertEqual((risposta.data['stato'], risposta.data['risposto_da_nome'] != ''), ('in_lavorazione', True))
        self.assertEqual(store.get('/api/assistenza/contatori/').json()['da_vedere'], 1)
        store.post('/api/assistenza/contatori/')
        self.assertEqual(store.get('/api/assistenza/contatori/').json()['da_vedere'], 0)
        self.assertEqual(store.get(url).json()[0]['risposta'], 'Da Calendario apri la formazione.')
        admin.patch(dettaglio, {'stato': 'completata'}, format='json')
        self.assertEqual(admin.get('/api/assistenza/contatori/').json()['da_vedere'], 1)  # resta l'idea nuova
