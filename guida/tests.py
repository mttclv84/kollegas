from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import User

from .models import ArgomentoGuida

def png():
    """Immagine PNG minima valida, per provare il caricamento dello screenshot."""
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new('RGB', (2, 2), 'white').save(buf, 'PNG')
    return buf.getvalue()


class GuidaTest(TestCase):
    def _client(self, livello):
        c = APIClient()
        c.force_authenticate(User.objects.create_user(email=f'{livello}@g.it', password='x', cognome='X', nome='Y',
                                                      livello_accesso=livello))
        return c

    def test_contenuto_iniziale_per_area(self):
        titoli = [a['titolo'] for a in self._client('area').get('/api/guida/').json()]
        self.assertEqual(titoli[0], 'Primo accesso e password')
        self.assertEqual(len(titoli), 9)
        self.assertEqual(self._client('store').get('/api/guida/').json(), [])
        ho = self._client('ho').get('/api/guida/').json()
        self.assertEqual((len(ho), ho[2]['titolo']), (10, 'Creare una formazione'))
        self.assertTrue(all(x['immagine_percorso'] for x in ho[:9]))  # l'ultimo argomento è senza screenshot
        testi = {x['titolo']: x['contenuto'] for x in ho}
        self.assertIn('solo le formazioni create da te', testi['Creare una formazione'])
        self.assertIn('profilo **Base**', testi['Gestione Account'])
        self.assertIn('**creata da te**', testi['Richieste di Modifica'])
        self.assertIn("solo l'Admin può eliminarli", testi['Report: Completamento, Dettaglio e Mapping'])
        self.assertIn('Non vedo il pulsante Elimina', testi['Eccezioni Calendario e domande frequenti'])

    def test_solo_admin_modifica_e_gli_altri_vedono_gli_attivi(self):
        admin, area = self._client('admin'), self._client('area')
        self.assertEqual(area.post('/api/guida/', {'profilo': 'area', 'titolo': 'X'}, format='json').status_code, 403)
        r = admin.post('/api/guida/', {'profilo': 'area', 'titolo': 'Nuovo argomento', 'contenuto': 'Testo',
                                       'immagine': SimpleUploadedFile('s.png', png(), content_type='image/png')},
                       format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        nuovo = ArgomentoGuida.objects.get(pk=r.data['id'])
        self.assertEqual(nuovo.ordine, 10)  # in coda ai 9 iniziali
        self.assertTrue(r.data['immagine_percorso'].startswith('guida/'))
        self.assertEqual(self.client.get(f"/media/{r.data['immagine_percorso']}").status_code, 200)  # pubblica
        self.assertIn('Nuovo argomento', [a['titolo'] for a in area.get('/api/guida/').json()])
        self.assertEqual(admin.patch(f'/api/guida/{nuovo.id}/', {'attivo': False}, format='json').status_code, 200)
        self.assertNotIn('Nuovo argomento', [a['titolo'] for a in area.get('/api/guida/').json()])
        self.assertIn('Nuovo argomento', [a['titolo'] for a in admin.get('/api/guida/', {'profilo': 'area'}).json()])
        self.assertEqual(area.delete(f'/api/guida/{nuovo.id}/').status_code, 403)
        self.assertEqual(admin.delete(f'/api/guida/{nuovo.id}/').status_code, 204)
