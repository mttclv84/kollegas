from rest_framework import serializers
from .models import Host, AttivitaCatalogo, Evento


class HostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Host
        fields = ['id', 'descrizione', 'posizione', 'nota', 'is_active', 'created_at']
        read_only_fields = ['created_at']


class AttivitaCatalogoSerializer(serializers.ModelSerializer):
    ruoli_destinatari_nomi = serializers.SerializerMethodField()

    class Meta:
        model = AttivitaCatalogo
        fields = ['id', 'nome', 'tipologia', 'dettaglio', 'ruoli_destinatari', 'ruoli_destinatari_nomi', 'is_active', 'created_at']
        read_only_fields = ['created_at']

    def get_ruoli_destinatari_nomi(self, obj):
        return list(obj.ruoli_destinatari.values_list('nome', flat=True))


class EventoListSerializer(serializers.ModelSerializer):
    attivita_nome = serializers.CharField(source='attivita.nome', read_only=True)
    attivita_tipologia = serializers.CharField(source='attivita.tipologia', read_only=True)
    host_nome = serializers.CharField(source='host.descrizione', read_only=True)
    host_tipo = serializers.CharField(source='host.posizione', read_only=True)
    location_display = serializers.ReadOnlyField()
    iscritti_count = serializers.SerializerMethodField()
    posti_disponibili = serializers.ReadOnlyField()
    ehs_corso_nome = serializers.SerializerMethodField()
    ehs_negozio_codice = serializers.SerializerMethodField()

    class Meta:
        model = Evento
        fields = [
            'id', 'data', 'ora_inizio', 'ora_fine', 'ore_totali',
            'attivita', 'attivita_nome', 'attivita_tipologia',
            'host', 'host_nome', 'host_tipo',
            'location_store', 'location_esterna', 'location_display',
            'max_partecipanti', 'modalita_partecipazione',
            'iscritti_count', 'posti_disponibili',
            'is_ehs', 'ehs_corso_nome', 'ehs_negozio_codice',
        ]

    def get_iscritti_count(self, obj):
        return obj.iscrizioni.count()

    def get_ehs_corso_nome(self, obj):
        # Sul calendario principale mostriamo solo il nome del corso EHS
        # (prime due parole, per non appesantire il badge) e il numero store.
        sessione = getattr(obj, 'ehs_sessione', None)
        return sessione.corso.nome if sessione else None

    def get_ehs_negozio_codice(self, obj):
        sessione = getattr(obj, 'ehs_sessione', None)
        if not sessione:
            return None
        return sessione.negozio.codice_store or sessione.negozio.nome


class EventoDetailSerializer(serializers.ModelSerializer):
    attivita_nome = serializers.CharField(source='attivita.nome', read_only=True)
    host_nome = serializers.CharField(source='host.descrizione', read_only=True)
    location_display = serializers.ReadOnlyField()
    iscritti_count = serializers.SerializerMethodField()
    posti_disponibili = serializers.ReadOnlyField()
    created_by_nome = serializers.CharField(source='created_by.nome_completo', read_only=True)

    class Meta:
        model = Evento
        fields = [
            'id', 'data', 'ora_inizio', 'ora_fine', 'ore_totali',
            'attivita', 'attivita_nome',
            'host', 'host_nome',
            'location_store', 'location_esterna', 'location_display',
            'max_partecipanti', 'modalita_partecipazione', 'nota',
            'iscritti_count', 'posti_disponibili',
            'created_by', 'created_by_nome', 'created_at', 'updated_at',
        ]
        read_only_fields = ['ore_totali', 'created_by', 'created_at', 'updated_at']

    def get_iscritti_count(self, obj):
        return obj.iscrizioni.count()

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)
