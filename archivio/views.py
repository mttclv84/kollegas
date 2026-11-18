import mimetypes

from django.core.files.storage import default_storage
from django.http import FileResponse, Http404

# Solo questi percorsi sono pubblici via /media/ (usati in <img src>): registri,
# attestati e documenti utente si aprono solo dagli endpoint autenticati.
PREFISSI_PUBBLICI = ('foto_utenti/',)


def servi_media(request, nome):
    if not nome.startswith(PREFISSI_PUBBLICI):
        raise Http404
    try:
        f = default_storage.open(nome)
    except FileNotFoundError:
        raise Http404
    tipo = mimetypes.guess_type(nome)[0] or 'application/octet-stream'
    return FileResponse(f, content_type=tipo)
