from rest_framework import serializers
from .models import Iscrizione, RichiestaCancellazione


class IscrizioneSerializer(serializers.ModelSerializer):
    user_cognome = serializers.CharField(source='user.cognome', read_only=True)
    user_nome = serializers.CharField(source='user.nome', read_only=True)
    user_sesso = serializers.CharField(source='user.sesso', read_only=True)
    store_nome = serializers.CharField(source='user.store.nome', read_only=True)
    store_id = serializers.IntegerField(source='user.store_id', read_only=True)
    ruolo_nome = serializers.CharField(source='user.ruolo.nome', read_only=True)
    attivita_nome = serializers.CharField(source='evento.attivita.nome', read_only=True)
    evento_data = serializers.DateField(source='evento.data', read_only=True)
    evento_ore = serializers.DecimalField(source='evento.ore_totali', max_digits=4, decimal_places=2, read_only=True)
    location_display = serializers.CharField(source='evento.location_display', read_only=True)
    attivita_tipologia = serializers.CharField(source='evento.attivita.tipologia', read_only=True)
    richiesta_pendente_id = serializers.SerializerMethodField()

    class Meta:
        model = Iscrizione
        fields = [
            'id', 'evento', 'user',
            'user_cognome', 'user_nome', 'user_sesso', 'ruolo_nome',
            'store_id', 'store_nome',
            'stato',
            'attivita_nome', 'evento_data', 'evento_ore', 'location_display', 'attivita_tipologia',
            'richiesta_pendente_id',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_richiesta_pendente_id(self, obj):
        pending = getattr(obj, 'pending_richieste', None)
        if pending is not None:
            return pending[0].id if pending else None
        r = obj.richieste_cancellazione.filter(stato='pending').first()
        return r.id if r else None


class RichiestaCancellazioneSerializer(serializers.ModelSerializer):
    richiedente_nome = serializers.CharField(source='richiedente.nome_completo', read_only=True)
    richiedente_store = serializers.CharField(source='richiedente.store.nome', read_only=True)
    processed_by_nome = serializers.CharField(source='processed_by.nome_completo', read_only=True)
    partecipante_nome = serializers.SerializerMethodField()
    attivita_nome = serializers.SerializerMethodField()
    evento_data = serializers.SerializerMethodField()
    evento_id = serializers.SerializerMethodField()

    class Meta:
        model = RichiestaCancellazione
        fields = [
            'id', 'iscrizione', 'richiedente', 'richiedente_nome', 'richiedente_store',
            'motivazione', 'stato', 'created_at',
            'processed_by', 'processed_by_nome', 'processed_at',
            'notifica_letta',
            'snap_attivita_nome', 'snap_evento_data', 'snap_partecipante_nome', 'snap_store_nome',
            'partecipante_nome', 'attivita_nome', 'evento_data', 'evento_id',
        ]
        read_only_fields = [
            'richiedente', 'stato', 'created_at', 'processed_by', 'processed_at',
            'notifica_letta', 'snap_attivita_nome', 'snap_evento_data',
            'snap_partecipante_nome', 'snap_store_nome',
        ]

    def get_partecipante_nome(self, obj):
        if obj.iscrizione_id:
            try:
                return f'{obj.iscrizione.user.cognome} {obj.iscrizione.user.nome}'
            except Exception:
                pass
        return obj.snap_partecipante_nome

    def get_attivita_nome(self, obj):
        if obj.iscrizione_id:
            try:
                return obj.iscrizione.evento.attivita.nome
            except Exception:
                pass
        return obj.snap_attivita_nome

    def get_evento_data(self, obj):
        if obj.iscrizione_id:
            try:
                return str(obj.iscrizione.evento.data)
            except Exception:
                pass
        return str(obj.snap_evento_data) if obj.snap_evento_data else None

    def get_evento_id(self, obj):
        if obj.iscrizione_id:
            try:
                return obj.iscrizione.evento_id
            except Exception:
                pass
        return None
