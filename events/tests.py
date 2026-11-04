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
