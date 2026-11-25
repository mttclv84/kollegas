from rest_framework import serializers
from .models import Host, AttivitaCatalogo, Evento, RichiestaDisattivazioneAttivita


def giornate_edizione(serializer, evento):
    """Id delle giornate dell'edizione in ordine di data (una query per edizione, poi in cache)."""
    if not evento.edizione_id:
        return None
    cache = serializer.context.setdefault('_giornate_edizione', {}) if hasattr(serializer, 'context') else {}
    if evento.edizione_id not in cache:
        cache[evento.edizione_id] = list(Evento.objects.filter(edizione_id=evento.edizione_id)
                                         .order_by('data', 'ora_inizio', 'id').values_list('id', flat=True))
    return cache[evento.edizione_id]


class HostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Host
        fields = ['id', 'descrizione', 'posizione', 'nota', 'is_active', 'created_at']
        read_only_fields = ['created_at']


class AttivitaCatalogoSerializer(serializers.ModelSerializer):
    ruoli_destinatari_nomi = serializers.SerializerMethodField()
    disattivazione_in_attesa = serializers.SerializerMethodField()

    class Meta:
        model = AttivitaCatalogo
        fields = ['id', 'nome', 'tipologia', 'dettaglio', 'ruoli_destinatari', 'ruoli_destinatari_nomi', 'is_active',
                  'created_at', 'disattivazione_in_attesa']
        read_only_fields = ['created_at']

    def get_ruoli_destinatari_nomi(self, obj):
        return list(obj.ruoli_destinatari.values_list('nome', flat=True))

    def get_disattivazione_in_attesa(self, obj):
        annotato = getattr(obj, 'disattivazione_in_attesa', None)
        if annotato is not None:
            return annotato
        return obj.richieste_disattivazione.filter(stato='pending').exists()


class RichiestaDisattivazioneAttivitaSerializer(serializers.ModelSerializer):
    attivita_nome = serializers.CharField(source='attivita.nome', read_only=True)
    richiedente_nome = serializers.CharField(source='richiedente.nome_completo', read_only=True, default='')

    class Meta:
        model = RichiestaDisattivazioneAttivita
        fields = ['id', 'attivita', 'attivita_nome', 'richiedente_nome', 'stato', 'created_at']


class EventoListSerializer(serializers.ModelSerializer):
    attivita_nome = serializers.CharField(source='attivita.nome', read_only=True)
    attivita_tipologia = serializers.CharField(source='attivita.tipologia', read_only=True)
    host_nome = serializers.CharField(source='host.descrizione', read_only=True)
    host_tipo = serializers.CharField(source='host.posizione', read_only=True)
    location_display = serializers.ReadOnlyField()
    iscritti_count = serializers.SerializerMethodField()
    posti_disponibili = serializers.ReadOnlyField()
    presenze_complete = serializers.SerializerMethodField()
    ehs_corso_nome = serializers.SerializerMethodField()
    ehs_negozio_codice = serializers.SerializerMethodField()
    giornata = serializers.SerializerMethodField()
    giornate_totali = serializers.SerializerMethodField()

    class Meta:
        model = Evento
        fields = [
            'id', 'data', 'ora_inizio', 'ora_fine', 'ore_totali',
            'attivita', 'attivita_nome', 'attivita_tipologia',
            'host', 'host_nome', 'host_tipo',
            'location_store', 'location_esterna', 'location_display',
            'max_partecipanti', 'modalita_partecipazione',
            'iscritti_count', 'posti_disponibili', 'presenze_complete',
            'is_ehs', 'ehs_corso_nome', 'ehs_negozio_codice',
            'edizione', 'giornata', 'giornate_totali',
        ]

    def get_iscritti_count(self, obj):
        return obj.iscrizioni.count()

    def get_giornata(self, obj):
        ids = giornate_edizione(self, obj)
        return ids.index(obj.id) + 1 if ids else None

    def get_giornate_totali(self, obj):
        ids = giornate_edizione(self, obj)
        return len(ids) if ids else None

    def get_presenze_complete(self, obj):
        """True quando ogni iscritto è segnato presente o assente: sul calendario il
        pallino dell'attività diventa un rettangolino nero. Usa le iscrizioni già
        precaricate dalla lista (nessuna query in più)."""
        iscrizioni = list(obj.iscrizioni.all())
        return bool(iscrizioni) and all(i.stato in ('partecipato', 'assente') for i in iscrizioni)

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
    ehs_corso_id = serializers.SerializerMethodField()
    ehs_partecipanti_min = serializers.SerializerMethodField()
    giornate = serializers.SerializerMethodField()

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
            'is_ehs', 'ehs_corso_id', 'ehs_partecipanti_min',
            'edizione', 'giornate',
        ]
        read_only_fields = ['ore_totali', 'created_by', 'created_at', 'updated_at', 'edizione']

    def get_giornate(self, obj):
        if not obj.edizione_id:
            return []
        return [{'id': g.id, 'data': g.data, 'ora_inizio': g.ora_inizio, 'ora_fine': g.ora_fine}
                for g in Evento.objects.filter(edizione_id=obj.edizione_id).order_by('data', 'ora_inizio', 'id')]

    def get_ehs_partecipanti_min(self, obj):
        # Minimo effettivo dell'aula EHS (0 = online, nessun minimo).
        sessione = getattr(obj, 'ehs_sessione', None)
        if not sessione:
            return None
        from ehs.services import minimo_partecipanti
        return minimo_partecipanti(sessione)

    def get_ehs_corso_id(self, obj):
        sessione = getattr(obj, 'ehs_sessione', None)
        return sessione.corso_id if sessione else None

    def get_iscritti_count(self, obj):
        return obj.iscrizioni.count()

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)
