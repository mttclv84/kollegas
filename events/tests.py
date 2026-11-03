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
        self.assertEqual(len(c.get('/api/attivita/').json()), 60)
