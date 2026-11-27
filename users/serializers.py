from rest_framework import serializers
from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, Throttled
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .accesso import MESSAGGIO_TENTATIVI, ha_accesso, messaggio_senza_accesso, password_comune, revoca_sessioni
from .models import (
    User, Role, PercorsoCrescita, AuditLog, RichiestaCreazioneProfilo, RichiestaEliminazioneProfilo,
    RichiestaResetPassword,
)

TENTATIVI_MASSIMI = 10
MINUTI_BLOCCO = 15


def dati_utente_login(user):
    return {
        'id': user.id,
        'email': user.email,
        'nome_completo': user.nome_completo,
        'cognome': user.cognome,
        'nome': user.nome,
        'livello_accesso': user.livello_accesso,
        'store_id': user.store_id,
        'store_nome': str(user.store) if user.store else None,
        'foto': user.foto.url if user.foto else None,
        'sola_lettura': user.sola_lettura,
        'deve_cambiare_password': user.deve_cambiare_password,
        'password_scadenza': user.password_scadenza,
    }


def _registra_tentativo_fallito(user):
    User.objects.filter(pk=user.pk).update(tentativi_falliti=F('tentativi_falliti') + 1)
    user.refresh_from_db(fields=['tentativi_falliti'])
    if user.tentativi_falliti >= TENTATIVI_MASSIMI:
        User.objects.filter(pk=user.pk).update(
            tentativi_falliti=0, bloccato_fino=timezone.now() + timedelta(minutes=MINUTI_BLOCCO))


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['nome_completo'] = user.nome_completo
        token['livello_accesso'] = user.livello_accesso
        token['store_id'] = user.store_id
        return token

    def validate(self, attrs):
        account = User.objects.filter(email=attrs.get('email')).first()
        if account and account.bloccato_fino and account.bloccato_fino > timezone.now():
            raise Throttled(detail=MESSAGGIO_TENTATIVI)
        try:
            data = super().validate(attrs)
        except AuthenticationFailed:
            utente = getattr(self, 'user', None)
            # Credenziali corrette ma accesso non consentito: messaggio esplicito (403).
            if utente is not None and utente.is_active and not ha_accesso(utente):
                raise PermissionDenied(messaggio_senza_accesso(utente))
            if utente is None and account:
                _registra_tentativo_fallito(account)
            raise
        if self.user.tentativi_falliti or self.user.bloccato_fino:
            User.objects.filter(pk=self.user.pk).update(tentativi_falliti=0, bloccato_fino=None)
        data['user'] = dati_utente_login(self.user)
        AuditLog.objects.create(actor=self.user, azione='accesso', target_tipo='Accesso',
                                target_id=self.user.id, target_repr=self.user.nome_completo)
        return data


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['id', 'nome']


class UserListSerializer(serializers.ModelSerializer):
    store_nome = serializers.CharField(source='store.nome', read_only=True)
    ruolo_nome = serializers.CharField(source='ruolo.nome', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'cognome', 'nome', 'email', 'sesso', 'livello_accesso',
            'store', 'store_nome', 'codice_matricola', 'ruolo', 'ruolo_nome',
            'foto', 'commento_mapping', 'long_absence', 'is_active', 'created_at',
        ]


class UserDetailSerializer(serializers.ModelSerializer):
    store_nome = serializers.CharField(source='store.nome', read_only=True)
    ruolo_nome = serializers.CharField(source='ruolo.nome', read_only=True)
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            'id', 'cognome', 'nome', 'email', 'sesso', 'livello_accesso',
            'store', 'store_nome', 'codice_matricola', 'ruolo', 'ruolo_nome',
            'foto', 'commento_mapping', 'long_absence', 'is_active',
            'created_at', 'updated_at', 'password', 'deve_cambiare_password', 'password_scadenza',
        ]
        read_only_fields = ['created_at', 'updated_at', 'deve_cambiare_password', 'password_scadenza']

    def create(self, validated_data):
        password = validated_data.pop('password', None) or password_comune()
        user = User(**validated_data)
        user.imposta_password_temporanea(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if password:
            request = self.context.get('request')
            if not request or request.user.livello_accesso != 'admin':
                raise PermissionDenied('Solo l\'Admin può reimpostare una password.')
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.imposta_password_temporanea(password)
        instance.save()
        if password:
            revoca_sessioni(instance)
        return instance


class RichiestaResetPasswordSerializer(serializers.ModelSerializer):
    utente_nome = serializers.CharField(source='user.nome_completo', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    livello_accesso = serializers.CharField(source='user.livello_accesso', read_only=True)
    store_nome = serializers.CharField(source='user.store.nome', read_only=True, default='')

    class Meta:
        model = RichiestaResetPassword
        fields = ['id', 'user', 'utente_nome', 'email', 'livello_accesso', 'store_nome', 'stato', 'created_at']


class PercorsoCrescitaSerializer(serializers.ModelSerializer):
    created_by_nome = serializers.CharField(source='created_by.nome_completo', read_only=True)

    class Meta:
        model = PercorsoCrescita
        fields = ['id', 'user', 'data', 'tipo_evento', 'ruolo_nome', 'store_nome', 'descrizione', 'created_by', 'created_by_nome', 'created_at']
        read_only_fields = ['created_at', 'created_by']

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class RichiestaCreazionoProfiloSerializer(serializers.ModelSerializer):
    richiedente_nome = serializers.CharField(source='richiedente.nome_completo', read_only=True)
    richiedente_store = serializers.CharField(source='richiedente.store.nome', read_only=True)
    store_nome = serializers.CharField(source='store.nome', read_only=True)
    ruolo_nome = serializers.CharField(source='ruolo.nome', read_only=True)

    class Meta:
        model = RichiestaCreazioneProfilo
        fields = [
            'id', 'richiedente', 'richiedente_nome', 'richiedente_store',
            'cognome', 'nome', 'email', 'sesso', 'livello_accesso',
            'store', 'store_nome', 'codice_matricola', 'ruolo', 'ruolo_nome',
            'commento_mapping', 'stato', 'visto_ho', 'visto_store',
            'processed_by', 'processed_at', 'created_at',
        ]
        read_only_fields = ['richiedente', 'stato', 'processed_by', 'processed_at', 'created_at']


class RichiestaEliminazioneProfiloSerializer(serializers.ModelSerializer):
    richiedente_nome = serializers.CharField(source='richiedente.nome_completo', read_only=True)
    richiedente_store = serializers.CharField(source='richiedente.store.nome', read_only=True)
    target_livello = serializers.CharField(source='target_user.livello_accesso', read_only=True, default='')

    class Meta:
        model = RichiestaEliminazioneProfilo
        fields = [
            'id', 'target_user', 'target_livello', 'richiedente', 'richiedente_nome', 'richiedente_store',
            'snap_nome', 'stato', 'visto_ho', 'visto_store',
            'processed_by', 'processed_at', 'created_at',
        ]
        read_only_fields = ['richiedente', 'snap_nome', 'stato', 'processed_by', 'processed_at', 'created_at']


class AuditLogSerializer(serializers.ModelSerializer):
    actor_nome = serializers.CharField(source='actor.nome_completo', read_only=True)
    actor_livello = serializers.CharField(source='actor.get_livello_accesso_display', read_only=True)

    class Meta:
        model = AuditLog
        fields = ['id', 'actor', 'actor_nome', 'actor_livello', 'azione', 'target_tipo', 'target_id', 'target_repr', 'dettaglio', 'created_at']


