from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase

from .models import FileArchiviato


class DatabaseStorageTest(TestCase):
    def test_salva_legge_elimina(self):
        presenti = FileArchiviato.objects.count()  # es. gli screenshot iniziali della guida
        nome = default_storage.save('ehs/prova/registro.pdf', ContentFile(b'%PDF-1 contenuto'))
        self.assertTrue(default_storage.exists(nome))
        self.assertEqual(default_storage.open(nome).read(), b'%PDF-1 contenuto')
        self.assertEqual(default_storage.size(nome), 16)
        # stesso nome: non sovrascrive, ne genera uno nuovo
        altro = default_storage.save('ehs/prova/registro.pdf', ContentFile(b'altro'))
        self.assertNotEqual(nome, altro)
        default_storage.delete(nome)
        self.assertFalse(default_storage.exists(nome))
        self.assertEqual(FileArchiviato.objects.count(), presenti + 1)
        with self.assertRaises(FileNotFoundError):
            default_storage.open(nome)

    def test_media_pubblico_solo_per_le_foto(self):
        foto = default_storage.save('foto_utenti/a.jpg', ContentFile(b'jpg'))
        doc = default_storage.save('ehs/registri_compilati/r.pdf', ContentFile(b'pdf'))
        self.assertEqual(self.client.get('/media/' + foto).status_code, 200)
        self.assertEqual(self.client.get('/media/' + doc).status_code, 404)
