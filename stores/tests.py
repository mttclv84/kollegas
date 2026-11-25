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
        # Iscritta (non ancora svolto) a un altro corso: compare la data dell'aula.
        corso2 = AttivitaCatalogo.objects.create(nome='GWU RA-TM / Report&Sistemi | OBBLIGATORIO', tipologia='ld')
        ev2 = Evento.objects.create(data=date(2026, 12, 3), ora_inizio=time(9), ora_fine=time(13), attivita=corso2,
                                    host=Host.objects.first())
        Iscrizione.objects.create(evento=ev2, user=anna, stato='iscritto')
        r = c.get(f'/api/stores/{negozio.id}/completamento/zoom/').json()
        self.assertEqual(r['utenti'][0]['iscritti'], {str(corso2.id): '2026-12-03'})


class ProgrammiCompletamentoTest(TestCase):
    """DM Leadership: target i Department Manager, le due aule contano anche come percorso unico."""

    def setUp(self):
        from datetime import date, time
        from events.models import AttivitaCatalogo, Evento, Host
        from participants.models import Iscrizione
        from users.models import Role
        from .models import Area

        self.negozio = Store.objects.create(nome='Firenze', comune='Firenze', provincia='FI', email_store='fi@x.it')
        Area.objects.create(numero=1).stores.add(self.negozio)
        dm = Role.objects.create(nome='Department Manager')
        anna = User.objects.create_user(email='a@x.it', password='x', cognome='Rossi', nome='Anna', store=self.negozio, ruolo=dm)
        bruno = User.objects.create_user(email='b@x.it', password='x', cognome='Verdi', nome='Bruno', store=self.negozio, ruolo=dm)
        tm = User.objects.create_user(email='t@x.it', password='x', cognome='Neri', nome='Tea', store=self.negozio,
                                      ruolo=Role.objects.create(nome='Team Manager'))
        host = Host.objects.create(descrizione='T', posizione='interno')
        aule = []
        for n, giorno in (('1/2', date(2026, 3, 1)), ('2/2', date(2026, 12, 20))):
            attivita = AttivitaCatalogo.objects.create(nome=f'DM Leadership - Aula {n}', tipologia='ld')
            aule.append(Evento.objects.create(data=giorno, ora_inizio=time(9), ora_fine=time(17), attivita=attivita, host=host))
        self.aula2 = aule[1].attivita
        for utente, evento, stato in ((anna, aule[0], 'partecipato'), (anna, aule[1], 'partecipato'),
                                      (bruno, aule[0], 'partecipato'), (bruno, aule[1], 'iscritto'),
                                      (tm, aule[0], 'partecipato')):
            Iscrizione.objects.create(evento=evento, user=utente, stato=stato)
        self.anna = anna
        self.c = APIClient()
        self.c.force_authenticate(User.objects.create_user(email='ad@x.it', password='x', cognome='A', nome='D',
                                                           livello_accesso='admin'))

    def _riassunto(self, corsi):
        return [(c['nome_breve'], c['completato'], c['in_procinto'], c['totale']) for c in corsi]

    def test_negozio_italia_e_area(self):
        atteso = [('Aula 1/2', 2, 0, 2), ('Aula 2/2', 1, 1, 2), ('Percorso completo', 1, 1, 2)]
        params = {'programma': 'dm-leadership'}
        negozio = self.c.get(f'/api/stores/{self.negozio.id}/completamento/', params).json()
        self.assertEqual(self._riassunto(negozio['corsi']), atteso)
        self.assertEqual(negozio['corsi'][2]['ruoli'][0]['etichetta'], 'DM')
        italia = self.c.get('/api/completamento/italia/', params).json()
        self.assertEqual(self._riassunto(italia['italia']), atteso)
        self.assertEqual(self._riassunto(italia['aree'][0]['corsi']), atteso)
        area = self.c.get('/api/completamento/area/1/', params).json()
        self.assertEqual(self._riassunto(area['stores'][0]['corsi']), atteso)
        self.assertEqual(area['stores'][0]['total_untrained'], 1)  # solo Bruno, per l'aula 2/2

    def test_zoom_e_programma_sconosciuto(self):
        r = self.c.get(f'/api/stores/{self.negozio.id}/completamento/zoom/', {'programma': 'dm-leadership'}).json()
        self.assertEqual([u['cognome'] for u in r['utenti']], ['Rossi', 'Verdi'])
        self.assertIn('percorso', r['utenti'][0]['fatti'])
        self.assertNotIn('percorso', r['utenti'][1]['fatti'])
        self.assertEqual(r['utenti'][1]['iscritti'], {str(self.aula2.id): '2026-12-20'})
        self.assertEqual(self.c.get('/api/completamento/italia/', {'programma': 'altro'}).status_code, 404)
