import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Store

User = get_user_model()


class PasswordPortaleTest(TestCase):
    def setUp(self):
        self.store = Store.objects.create(nome='Caserta 280', comune='Caserta', provincia='CE',
                                          codice_store='280', email_store='manager280@x.it',
                                          portale_password='segreta')

    def _get(self, livello, url):
        utente, _ = User.objects.get_or_create(
            email=f'{livello}@x.it', defaults={'cognome': livello, 'nome': 'x', 'livello_accesso': livello})
        c = APIClient()
        c.force_authenticate(utente)
        return c.get(url).json()

    def test_password_visibile_solo_ad_admin_e_ho(self):
        for livello in ('base', 'store', 'fornitore', 'area', 'admin_ehs'):
            lista = self._get(livello, '/api/stores/')['results']
            self.assertNotIn('portale_password', lista[0], livello)
            self.assertNotIn('portale_password', self._get(livello, f'/api/stores/{self.store.id}/'), livello)
        self.assertEqual(self._get('admin', '/api/stores/')['results'][0]['portale_password'], 'segreta')
        self.assertEqual(self._get('ho', f'/api/stores/{self.store.id}/')['portale_password'], 'segreta')

    def test_imposta_password_store(self):
        call_command('imposta_password_store', password='Nuova01!', stdout=io.StringIO())
        self.store.refresh_from_db()
        self.assertEqual(self.store.portale_password, 'segreta')  # prova: nulla salvato
        call_command('imposta_password_store', password='Nuova01!', applica=True, stdout=io.StringIO())
        self.store.refresh_from_db()
        account = User.objects.get(email='manager280@x.it')
        self.assertEqual(self.store.portale_password, 'Nuova01!')
        self.assertTrue(account.check_password('Nuova01!'))
        self.assertEqual(account.livello_accesso, 'store')


class CompletamentoZoomTest(TestCase):
    def test_zoom_corsi_fatti_per_persona(self):
        from datetime import date, time
        from events.models import AttivitaCatalogo, Evento, Host
        from participants.models import Iscrizione
        from users.models import Role

        negozio = Store.objects.create(nome='Firenze', comune='Firenze', provincia='FI', email_store='fi@x.it')
        altro = Store.objects.create(nome='Roma', comune='Roma', provincia='RM', email_store='rm@x.it')
        tm = Role.objects.create(nome='Team Manager')
        anna = User.objects.create_user(email='anna@x.it', password='x', cognome='Rossi', nome='Anna',
                                        store=negozio, ruolo=tm)
        User.objects.create_user(email='bruno@x.it', password='x', cognome='Verdi', nome='Bruno',
                                 store=negozio, ruolo=Role.objects.create(nome='Cassiere'))
        corso = AttivitaCatalogo.objects.create(nome='GWU RA-TM / Valutazione e Feedback | OBBLIGATORIO', tipologia='ld')
        evento = Evento.objects.create(data=date(2026, 1, 10), ora_inizio=time(9), ora_fine=time(13), attivita=corso,
                                       host=Host.objects.create(descrizione='T', posizione='interno'))
        Iscrizione.objects.create(evento=evento, user=anna, stato='partecipato')

        c = APIClient()
        c.force_authenticate(User.objects.create_user(email='s@x.it', password='x', cognome='S', nome='S',
                                                      livello_accesso='store', store=negozio))
        r = c.get(f'/api/stores/{negozio.id}/completamento/zoom/').json()
        self.assertEqual([u['cognome'] for u in r['utenti']], ['Rossi'])  # solo GWU RA-TM e TM
        self.assertEqual(r['corsi'][0]['nome_breve'], 'Valutazione e Feedback')
        self.assertEqual(r['utenti'][0]['fatti'], [corso.id])
        self.assertEqual(c.get(f'/api/stores/{altro.id}/completamento/zoom/').status_code, 403)
