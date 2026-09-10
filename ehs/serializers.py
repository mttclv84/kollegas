from rest_framework import serializers

from events.models import Evento

from .models import EHSCorso, EHSPartecipante, EHSSessione, EHSSessioneLog


class EHSCorsoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EHSCorso
        fields = ['id', 'codice', 'nome', 'durata_ore', 'descrizione', 'attivo', 'scadenza_giorni']


class EHSPartecipanteSerializer(serializers.ModelSerializer):
    utente_nome = serializers.CharField(source='utente.nome_completo', read_only=True)
    utente_email = serializers.CharField(source='utente.email', read_only=True)

    class Meta:
        model = EHSPartecipante
        fields = [
            'id', 'utente', 'utente_nome', 'utente_email', 'iscritto_il',
            'presente', 'assente_motivo',
            'attestato_file', 'attestato_caricato_il',
            'completato', 'completato_il', 'scadenza_formazione',
        ]
        read_only_fields = [
            'iscritto_il', 'attestato_file', 'attestato_caricato_il',
            'completato', 'completato_il', 'scadenza_formazione',
        ]


class EHSSessioneLogSerializer(serializers.ModelSerializer):
    utente_nome = serializers.CharField(source='utente.nome_completo', read_only=True, default=None)

    class Meta:
        model = EHSSessioneLog
        fields = ['id', 'stato_precedente', 'stato_nuovo', 'utente', 'utente_nome', 'timestamp', 'nota']


class EHSSessioneListSerializer(serializers.ModelSerializer):
    corso_nome = serializers.CharField(source='corso.nome', read_only=True)
    negozio_nome = serializers.CharField(source='negozio.nome', read_only=True)
    fornitore_nome = serializers.CharField(source='fornitore.nome_completo', read_only=True, default=None)
    stato_display = serializers.CharField(source='get_stato_display', read_only=True)
    partecipanti_count = serializers.SerializerMethodField()

    class Meta:
        model = EHSSessione
        fields = [
            'id', 'corso', 'corso_nome', 'negozio', 'negozio_nome',
            'fornitore', 'fornitore_nome', 'stato', 'stato_display',
            'data_proposta', 'data_confermata', 'durata_ore',
            'docente_nome', 'contatto_negozio_nome', 'partecipanti_count',
            'creata_il',
        ]

    def get_partecipanti_count(self, obj):
        return obj.partecipanti.count()


class EHSSessioneDetailSerializer(EHSSessioneListSerializer):
    creata_da_nome = serializers.CharField(source='creata_da.nome_completo', read_only=True)
    partecipanti = EHSPartecipanteSerializer(many=True, read_only=True)
    log = EHSSessioneLogSerializer(many=True, read_only=True)

    class Meta(EHSSessioneListSerializer.Meta):
        fields = EHSSessioneListSerializer.Meta.fields + [
            'creata_da', 'creata_da_nome',
            'docente_telefono', 'contatto_negozio_telefono',
            'registro_file', 'registro_compilato_file',
            'calendario_evento', 'data_chiusura', 'chiusa_da', 'note',
            'partecipanti', 'log',
        ]


class EHSCalendarioEventoSerializer(serializers.ModelSerializer):
    """Evento del calendario principale (EHS e non, §5.6) per la vista calendario EHS:
    include il riferimento alla sessione EHS collegata, quando presente, così il
    frontend sa cosa aprire al click. Campi allineati a EventoListSerializer (events
    app) per poter riusare direttamente il componente EventoBadge esistente."""
    attivita_nome = serializers.CharField(source='attivita.nome', read_only=True)
    attivita_tipologia = serializers.CharField(source='attivita.tipologia', read_only=True)
    location_display = serializers.ReadOnlyField()
    iscritti_count = serializers.SerializerMethodField()
    posti_disponibili = serializers.ReadOnlyField()
    ehs_sessione_id = serializers.SerializerMethodField()
    ehs_sessione_stato = serializers.SerializerMethodField()

    class Meta:
        model = Evento
        fields = [
            'id', 'data', 'ora_inizio', 'ora_fine', 'attivita_nome', 'attivita_tipologia',
            'location_display', 'max_partecipanti', 'iscritti_count', 'posti_disponibili',
            'is_ehs', 'ehs_luogo', 'ehs_sessione_id', 'ehs_sessione_stato',
        ]

    def get_iscritti_count(self, obj):
        return obj.iscrizioni.count()

    def get_ehs_sessione_id(self, obj):
        sessione = getattr(obj, 'ehs_sessione', None)
        return sessione.id if sessione else None

    def get_ehs_sessione_stato(self, obj):
        sessione = getattr(obj, 'ehs_sessione', None)
        return sessione.stato if sessione else None
