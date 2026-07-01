from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User, Role, PercorsoCrescita, AuditLog, RichiestaCreazioneProfilo, RichiestaEliminazioneProfilo


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
        data = super().validate(attrs)
        data['user'] = {
            'id': self.user.id,
            'email': self.user.email,
            'nome_completo': self.user.nome_completo,
            'cognome': self.user.cognome,
            'nome': self.user.nome,
            'livello_accesso': self.user.livello_accesso,
            'store_id': self.user.store_id,
            'store_nome': str(self.user.store) if self.user.store else None,
            'foto': self.user.foto.url if self.user.foto else None,
        }
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
    raw_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'cognome', 'nome', 'email', 'sesso', 'livello_accesso',
            'store', 'store_nome', 'codice_matricola', 'ruolo', 'ruolo_nome',
            'foto', 'commento_mapping', 'long_absence', 'is_active',
            'created_at', 'updated_at', 'password', 'raw_password',
        ]
        read_only_fields = ['created_at', 'updated_at']

    DEFAULT_PASSWORD = 'Primark01!'

    def get_raw_password(self, obj):
        request = self.context.get('request')
        if request and request.user.livello_accesso in ('admin', 'ho'):
            return obj.raw_password or None
        return None

    def create(self, validated_data):
        password = validated_data.pop('password', None) or self.DEFAULT_PASSWORD
        user = User(**validated_data)
        user.set_password(password)
        user.raw_password = password
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
            instance.raw_password = password
        instance.save()
        return instance


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

    class Meta:
        model = RichiestaEliminazioneProfilo
        fields = [
            'id', 'target_user', 'richiedente', 'richiedente_nome', 'richiedente_store',
            'snap_nome', 'stato', 'visto_ho', 'visto_store',
            'processed_by', 'processed_at', 'created_at',
        ]
        read_only_fields = ['richiedente', 'snap_nome', 'stato', 'processed_by', 'processed_at', 'created_at']


class AuditLogSerializer(serializers.ModelSerializer):
    actor_nome = serializers.CharField(source='actor.nome_completo', read_only=True)

    class Meta:
        model = AuditLog
        fields = ['id', 'actor', 'actor_nome', 'azione', 'target_tipo', 'target_id', 'target_repr', 'dettaglio', 'created_at']


