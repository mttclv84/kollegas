import posixpath

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class DatabaseStorage(Storage):
    """Storage Django che salva i file nella tabella FileArchiviato invece che sul
    disco locale (effimero su Render). I FileField esistenti non cambiano: cambia
    solo dove finisce il contenuto."""

    def _modello(self):
        from .models import FileArchiviato
        return FileArchiviato

    def _open(self, name, mode='rb'):
        try:
            f = self._modello().objects.get(nome=name)
        except self._modello().DoesNotExist:
            raise FileNotFoundError(name)
        contenuto = ContentFile(bytes(f.contenuto))
        contenuto.name = name
        return contenuto

    def _save(self, name, content):
        if hasattr(content, 'seek'):
            content.seek(0)
        dati = content.read()
        if isinstance(dati, str):
            dati = dati.encode('utf-8')
        self._modello().objects.create(nome=name, contenuto=dati, dimensione=len(dati))
        return name

    def exists(self, name):
        return self._modello().objects.filter(nome=name).exists()

    def delete(self, name):
        if name:
            self._modello().objects.filter(nome=name).delete()

    def size(self, name):
        f = self._modello().objects.filter(nome=name).values_list('dimensione', flat=True).first()
        if f is None:
            raise FileNotFoundError(name)
        return f

    def url(self, name):
        # Servito da archivio.views.servi_media (solo i percorsi pubblici, es. foto).
        return '/media/' + name.lstrip('/')

    def listdir(self, path):
        prefisso = path.rstrip('/') + '/' if path else ''
        dirs, files = set(), []
        for nome in self._modello().objects.filter(nome__startswith=prefisso).values_list('nome', flat=True):
            resto = nome[len(prefisso):]
            if '/' in resto:
                dirs.add(resto.split('/', 1)[0])
            else:
                files.append(resto)
        return sorted(dirs), sorted(files)

    def get_available_name(self, name, max_length=None):
        # Come FileSystemStorage: aggiunge un suffisso se il nome è già usato.
        # Il nome alternativo di Django usa os.path.join: su Windows ricompare "\", quindi si normalizza anche l'uscita.
        nome = super().get_available_name(posixpath.normpath(name.replace(chr(92), '/')), max_length=max_length)
        return nome.replace(chr(92), '/')
