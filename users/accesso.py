import secrets

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

# Livelli che al momento non possono entrare in piattaforma. Per riaprire l'accesso
# basta togliere il livello da questo insieme.
LIVELLI_SENZA_ACCESSO = {'base'}
MESSAGGIO_SENZA_ACCESSO = 'Il tuo profilo al momento non ha accesso a Kollegas.'
MESSAGGIO_PASSWORD_SCADUTA = 'La password temporanea è scaduta. Usa "Richiedi reset password".'
MESSAGGIO_TENTATIVI = 'Troppi tentativi errati. Riprova tra 15 minuti.'
MESSAGGIO_CAMBIO_PASSWORD = 'Devi scegliere una nuova password per continuare.'
CODICE_CAMBIO_PASSWORD = 'cambio_password_richiesto'

# Nella sezione EHS questi livelli vedono tutto ma non modificano nulla.
LIVELLI_SOLA_VISIONE_EHS = {'ho', 'area'}
MESSAGGIO_SOLA_VISIONE_EHS = 'Il tuo profilo può solo visualizzare la sezione EHS.'


def sola_visione_ehs(user):
    return getattr(user, 'livello_accesso', None) in LIVELLI_SOLA_VISIONE_EHS


def ha_accesso(user):
    return (user is not None and user.is_active and user.livello_accesso not in LIVELLI_SENZA_ACCESSO
            and not user.password_scaduta)


def messaggio_senza_accesso(user):
    if user.livello_accesso in LIVELLI_SENZA_ACCESSO:
        return MESSAGGIO_SENZA_ACCESSO
    return MESSAGGIO_PASSWORD_SCADUTA


def genera_password_temporanea():
    """Password individuale leggibile (niente caratteri ambigui come 0/O o 1/l)."""
    alfabeto = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    return '-'.join(''.join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3))


def password_comune():
    """Password di primo accesso, dalla variabile d'ambiente KOLLEGAS_PASSWORD_COMUNE.
    Se manca, il nuovo profilo riceve una password casuale e l'Admin usa il reset."""
    return settings.KOLLEGAS_PASSWORD_COMUNE or genera_password_temporanea()


def password_non_ammessa(password):
    """Le password condivise non possono diventare la password personale di nessuno."""
    comune = settings.KOLLEGAS_PASSWORD_COMUNE
    return password.lower().startswith('primark') or (bool(comune) and password == comune)


def revoca_sessioni(user):
    """Invalida i refresh token dell'utente: gli access token li ferma password_cambiata_il."""
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


class AccessoJWTAuthentication(JWTAuthentication):
    """Come JWTAuthentication, ma ferma i token dei profili senza accesso, quelli emessi
    prima dell'ultimo cambio password e chi deve ancora scegliere la propria password."""

    def authenticate(self, request):
        esito = super().authenticate(request)
        if esito and esito[0].deve_cambiare_password and not self._consentito(request):
            raise PermissionDenied({'detail': MESSAGGIO_CAMBIO_PASSWORD, 'codice': CODICE_CAMBIO_PASSWORD})
        return esito

    @staticmethod
    def _consentito(request):
        return request.path.startswith('/api/auth/') or (request.path == '/api/me/' and request.method == 'GET')

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not ha_accesso(user):
            raise AuthenticationFailed(messaggio_senza_accesso(user), code='accesso_negato')
        cambiata = user.password_cambiata_il
        if cambiata and validated_token.get('iat', 0) < int(cambiata.timestamp()):
            raise AuthenticationFailed('Sessione scaduta: accedi di nuovo.', code='sessione_revocata')
        return user
