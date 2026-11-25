from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import AttivitaCatalogo

User = get_user_model()


class CatalogoCompletoTest(TestCase):
    def test_catalogo_restituisce_tutte_le_attivita(self):
        for i in range(60):
            AttivitaCatalogo.objects.create(nome=f'Attività {i:02d}', tipologia='altro')
        c = APIClient()
        c.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A',
                                                      livello_accesso='admin'))
        attive = AttivitaCatalogo.objects.filter(is_active=True).count()
        self.assertGreater(attive, 50)
        self.assertEqual(len(c.get('/api/attivita/').json()), attive)


class RichiestaDisattivazioneHOTest(TestCase):
    def setUp(self):
        self.att = AttivitaCatalogo.objects.create(nome='Corso da togliere', tipologia='ld')
        self.ho, self.admin, self.area = APIClient(), APIClient(), APIClient()
        self.ho.force_authenticate(User.objects.create_user(email='h@x.it', password='x', cognome='H', nome='H', livello_accesso='ho'))
        self.admin.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A', livello_accesso='admin'))
        self.area.force_authenticate(User.objects.create_user(email='r@x.it', password='x', cognome='R', nome='R', livello_accesso='area'))
        self.url = f'/api/attivita/{self.att.id}/richiedi-disattivazione/'

    def _in_attesa(self):
        return next(a for a in self.admin.get('/api/attivita/').json() if a['id'] == self.att.id)['disattivazione_in_attesa']

    def test_ho_chiede_e_admin_approva(self):
        self.assertEqual(self.area.post(self.url).status_code, 403)
        self.assertEqual(self.admin.post(self.url).status_code, 403)
        self.assertEqual(self.ho.post(self.url).status_code, 201)
        self.assertEqual(self.ho.post(self.url).status_code, 400)  # già in attesa
        self.att.refresh_from_db()
        self.assertTrue(self.att.is_active and self._in_attesa())
        self.assertEqual(self.ho.get('/api/richieste-disattivazione-attivita/').status_code, 403)
        richieste = self.admin.get('/api/richieste-disattivazione-attivita/').json()
        self.assertEqual([(r['attivita_nome'], r['richiedente_nome']) for r in richieste], [('Corso da togliere', 'H H')])
        url = f"/api/richieste-disattivazione-attivita/{richieste[0]['id']}/"
        self.assertEqual(self.ho.post(url, {'azione': 'approva'}, format='json').status_code, 403)
        self.assertEqual(self.admin.post(url, {'azione': 'approva'}, format='json').status_code, 200)
        self.att.refresh_from_db()
        self.assertFalse(self.att.is_active)
        self.assertEqual(self.admin.get('/api/richieste-disattivazione-attivita/').json(), [])

    def test_admin_rifiuta_e_l_attivita_resta(self):
        self.ho.post(self.url)
        richiesta = self.admin.get('/api/richieste-disattivazione-attivita/').json()[0]
        self.admin.post(f"/api/richieste-disattivazione-attivita/{richiesta['id']}/", {'azione': 'rifiuta'}, format='json')
        self.att.refresh_from_db()
        self.assertTrue(self.att.is_active)
        self.assertFalse(self._in_attesa())
        self.assertEqual(self.ho.post(self.url).status_code, 201)  # si può chiedere di nuovo


class DisattivazioneAttivitaTest(TestCase):
    def test_elimina_disattiva_solo_admin_e_conserva_lo_storico(self):
        from datetime import date, time
        from .models import Evento, Host
        att = AttivitaCatalogo.objects.create(nome='Da disattivare', tipologia='ld')
        evento = Evento.objects.create(data=date(2026, 1, 10), ora_inizio=time(9), ora_fine=time(10), attivita=att,
                                       host=Host.objects.get_or_create(descrizione='T', defaults={'posizione': 'interno'})[0])
        ho, admin = APIClient(), APIClient()
        ho.force_authenticate(User.objects.create_user(email='h@x.it', password='x', cognome='H', nome='H', livello_accesso='ho'))
        admin.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A', livello_accesso='admin'))
        self.assertEqual(ho.delete(f'/api/attivita/{att.id}/').status_code, 403)
        self.assertEqual(admin.delete(f'/api/attivita/{att.id}/').status_code, 204)
        att.refresh_from_db()
        self.assertFalse(att.is_active)
        self.assertTrue(Evento.objects.filter(pk=evento.pk).exists())
        ids = lambda url: [a['id'] for a in admin.get(url).json()]
        self.assertNotIn(att.id, ids('/api/attivita/'))
        self.assertIn(att.id, ids('/api/attivita/?tutte=1'))
        self.assertEqual(ids('/api/attivita/?disattivate=1'), [att.id])
        self.assertEqual(ho.patch(f'/api/attivita/{att.id}/', {'is_active': True}, format='json').status_code, 403)
        self.assertEqual(admin.patch(f'/api/attivita/{att.id}/', {'is_active': True}, format='json').status_code, 200)


class PresenzeCompleteTest(TestCase):
    def test_presenze_complete_quando_tutti_presenti_o_assenti(self):
        from datetime import date, time
        from participants.models import Iscrizione
        from .models import Evento, Host
        evento = Evento.objects.create(
            data=date(2026, 1, 10), ora_inizio=time(9), ora_fine=time(10),
            attivita=AttivitaCatalogo.objects.create(nome='Corso', tipologia='ld'),
            host=Host.objects.get_or_create(descrizione='T', defaults={'posizione': 'interno'})[0])
        c = APIClient()
        c.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A',
                                                      livello_accesso='admin'))
        def stato():
            dati = c.get('/api/eventi/', {'data_da': '2026-01-01', 'data_a': '2026-01-31'}).json()
            dati = dati['results'] if isinstance(dati, dict) else dati
            return next(e for e in dati if e['id'] == evento.id)['presenze_complete']
        self.assertFalse(stato())  # nessun iscritto
        u1 = User.objects.create_user(email='u1@x.it', password='x', cognome='U', nome='1')
        u2 = User.objects.create_user(email='u2@x.it', password='x', cognome='U', nome='2')
        i1 = Iscrizione.objects.create(evento=evento, user=u1, stato='partecipato')
        Iscrizione.objects.create(evento=evento, user=u2, stato='iscritto')
        self.assertFalse(stato())
        Iscrizione.objects.filter(user=u2).update(stato='assente')
        self.assertTrue(stato())
        i1.delete()
        self.assertTrue(stato())


class PausaPranzoTest(TestCase):
    def _ore(self, inizio, fine):
        from datetime import date, time
        from .models import Evento, Host
        evento = Evento.objects.create(
            data=date(2026, 1, 10), ora_inizio=time(*inizio), ora_fine=time(*fine),
            attivita=AttivitaCatalogo.objects.create(nome=f'C{inizio}{fine}', tipologia='ld'),
            host=Host.objects.get_or_create(descrizione='T', defaults={'posizione': 'interno'})[0])
        return float(evento.ore_totali)

    def test_pausa_solo_se_copre_13_14(self):
        self.assertEqual(self._ore((9, 0), (11, 0)), 2.0)    # mattina: nessuna pausa
        self.assertEqual(self._ore((14, 0), (15, 0)), 1.0)   # pomeriggio: nessuna pausa
        self.assertEqual(self._ore((9, 0), (13, 0)), 4.0)
        self.assertEqual(self._ore((9, 0), (18, 0)), 8.0)    # giornata intera: meno un'ora
