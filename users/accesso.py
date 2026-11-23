from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

# Livelli che al momento non possono entrare in piattaforma. Per riaprire l'accesso
# basta togliere il livello da questo insieme.
LIVELLI_SENZA_ACCESSO = {'base'}
MESSAGGIO_SENZA_ACCESSO = 'Il tuo profilo al momento non ha accesso a Kollegas.'

# Nella sezione EHS questi livelli vedono tutto ma non modificano nulla.
LIVELLI_SOLA_VISIONE_EHS = {'ho'}
MESSAGGIO_SOLA_VISIONE_EHS = 'Il tuo profilo può solo visualizzare la sezione EHS.'


def sola_visione_ehs(user):
    return getattr(user, 'livello_accesso', None) in LIVELLI_SOLA_VISIONE_EHS


def ha_accesso(user):
    return user is not None and user.is_active and user.livello_accesso not in LIVELLI_SENZA_ACCESSO


class AccessoJWTAuthentication(JWTAuthentication):
    """Come JWTAuthentication, ma invalida anche i token già emessi ai livelli senza accesso."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not ha_accesso(user):
            raise AuthenticationFailed(MESSAGGIO_SENZA_ACCESSO, code='accesso_negato')
        return user
