from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from events.models import Evento

from .models import (
    EHSCorso, EHSFormazione, EHSMansione, EHSObbligo, EHSOffertaCorso, EHSPartecipante, EHSSessione,
    EHSSessioneDocumento, EHSSessioneLog,
)
from .services import cancellazione_consentita, minimo_partecipanti

User = get_user_model()


class EHSFornitoreSerializer(serializers.ModelSerializer):
    """Anagrafica dei fornitori EHS (utenti livello 'fornitore'): NOME AZIENDA,
    NOME DI RIFERIMENTO, email, indirizzo, telefono — livello fisso, non esposto
    come editabile qui (impostato lato view alla creazione)."""
    nome_completo = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'fornitore_ragione_sociale', 'cognome', 'nome', 'nome_completo',
            'email', 'telefono', 'indirizzo', 'is_active',
        ]


class EHSOffertaCorsoSerializer(serializers.ModelSerializer):
    fornitore_nome = serializers.SerializerMethodField()
    negozi_nomi = serializers.SerializerMethodField()

    class Meta:
        model = EHSOffertaCorso
        fields = ['id', 'fornitore', 'fornitore_nome', 'tutti_negozi', 'negozi', 'negozi_nomi', 'secondario']
        read_only_fields = ['secondario']

    def get_fornitore_nome(self, obj):
        return obj.fornitore.fornitore_ragione_sociale or obj.fornitore.nome_completo

    def get_negozi_nomi(self, obj):
        return [n.nome for n in obj.negozi.all()]


class EHSCorsoSerializer(serializers.ModelSerializer):
    """Corso con i suoi abbinamenti fornitore (offerte), ciascuno valido per tutti i
    negozi o per un elenco di negozi. Senza fornitori il corso non è richiedibile.
    In scrittura `offerte` sostituisce interamente gli abbinamenti esistenti."""
    offerte = EHSOffertaCorsoSerializer(many=True, required=False)
    fornitori_nomi = serializers.SerializerMethodField()

    class Meta:
        model = EHSCorso
        fields = [
            'id', 'codice', 'nome', 'durata_ore', 'descrizione', 'attivo', 'scadenza_giorni',
            'ore_aggiornamento', 'offerte', 'fornitori_nomi',
        ]
        # Il codice è generato automaticamente alla creazione (EHS + 4 cifre random) e
        # non è mai modificabile da input client, né in creazione né in modifica.
        extra_kwargs = {'codice': {'read_only': True}}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['offerte'] = sorted(data['offerte'], key=lambda o: (o['secondario'], o['id']))
        return data

    def get_fornitori_nomi(self, obj):
        return [o.fornitore.fornitore_ragione_sociale or o.fornitore.nome_completo for o in obj.offerte.all()]

    def validate_offerte(self, value):
        # Un corso senza fornitori è ammesso (es. moduli e-learning da registrare a mano):
        # semplicemente non compare tra i corsi richiedibili in 'Nuova Richiesta'.
        fornitori = [o['fornitore'] for o in value]
        if len({f.pk for f in fornitori}) != len(fornitori):
            raise serializers.ValidationError('Lo stesso fornitore è abbinato più volte.')
        for o in value:
            f = o['fornitore']
            if f.livello_accesso != 'fornitore':
                raise serializers.ValidationError('Il fornitore selezionato non è un utente di livello Fornitore EHS.')
            if not o.get('tutti_negozi', True) and not o.get('negozi'):
                raise serializers.ValidationError(
                    f'Seleziona almeno un negozio per {f.fornitore_ragione_sociale or f.nome_completo} '
                    f'oppure abilitalo per tutti i negozi.'
                )
        return value

    def _salva_offerte(self, corso, offerte):
        # Il primo fornitore dell'elenco è il principale, gli altri sono secondari.
        corso.offerte.all().delete()
        for i, o in enumerate(offerte):
            negozi = o.pop('negozi', [])
            offerta = EHSOffertaCorso.objects.create(corso=corso, secondario=i > 0, **o)
            if not offerta.tutti_negozi:
                offerta.negozi.set(negozi)

    def create(self, validated_data):
        offerte = validated_data.pop('offerte', [])
        with transaction.atomic():
            corso = super().create(validated_data)
            self._salva_offerte(corso, offerte)
        return corso

    def update(self, instance, validated_data):
        offerte = validated_data.pop('offerte', None)
        with transaction.atomic():
            corso = super().update(instance, validated_data)
            if offerte is not None:
                self._salva_offerte(corso, offerte)
        return corso


class EHSPartecipanteSerializer(serializers.ModelSerializer):
    utente_nome = serializers.CharField(source='utente.nome_completo', read_only=True)
    utente_email = serializers.CharField(source='utente.email', read_only=True)
    utente_store_nome = serializers.SerializerMethodField()

    class Meta:
        model = EHSPartecipante
        fields = [
            'id', 'utente', 'utente_nome', 'utente_email', 'utente_store_nome', 'iscritto_il',
            'presente', 'assente_motivo',
            'attestato_file', 'attestato_caricato_il',
            'completato', 'completato_il', 'scadenza_formazione',
        ]
        read_only_fields = [
            'iscritto_il', 'attestato_file', 'attestato_caricato_il',
            'completato', 'completato_il', 'scadenza_formazione',
        ]

    def get_utente_store_nome(self, obj):
        store = obj.utente.store
        if not store:
            return None
        return store.codice_store or store.nome


class EHSSessioneDocumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EHSSessioneDocumento
        fields = ['id', 'nome_originale', 'caricato_il']


class EHSSessioneLogSerializer(serializers.ModelSerializer):
    utente_nome = serializers.CharField(source='utente.nome_completo', read_only=True, default=None)

    class Meta:
        model = EHSSessioneLog
        fields = ['id', 'stato_precedente', 'stato_nuovo', 'utente', 'utente_nome', 'timestamp', 'nota']


class EHSSessioneListSerializer(serializers.ModelSerializer):
    corso_nome = serializers.CharField(source='corso.nome', read_only=True)
    negozio_nome = serializers.CharField(source='negozio.nome', read_only=True)
    fornitore_nome = serializers.SerializerMethodField()
    fornitore_richiesto_nome = serializers.SerializerMethodField()
    stato_display = serializers.CharField(source='get_stato_display', read_only=True)
    partecipanti_count = serializers.SerializerMethodField()

    class Meta:
        model = EHSSessione
        fields = [
            'id', 'corso', 'corso_nome', 'negozio', 'negozio_nome',
            'fornitore', 'fornitore_nome', 'stato', 'stato_display',
            'data_proposta', 'data_confermata', 'data_suggerita_store', 'durata_ore',
            'docente_nome', 'contatto_negozio_nome', 'partecipanti_previsti', 'partecipanti_count',
            'modalita', 'eccezionale', 'fornitore_secondario', 'fornitore_richiesto', 'fornitore_richiesto_nome',
            'partecipanti_min', 'partecipanti_max', 'minimo_effettivo', 'sotto_minimo',
            'attestati_caricati_il', 'creata_il',
        ]

    minimo_effettivo = serializers.SerializerMethodField()
    sotto_minimo = serializers.SerializerMethodField()

    def get_partecipanti_count(self, obj):
        return obj.partecipanti.count()

    def get_minimo_effettivo(self, obj):
        return minimo_partecipanti(obj)

    def get_sotto_minimo(self, obj):
        return obj.stato == 'CONFERMATA' and obj.partecipanti.count() < minimo_partecipanti(obj)

    def get_fornitore_nome(self, obj):
        return (obj.fornitore.fornitore_ragione_sociale or obj.fornitore.nome_completo) if obj.fornitore_id else None

    def get_fornitore_richiesto_nome(self, obj):
        f = obj.fornitore_richiesto
        return (f.fornitore_ragione_sociale or f.nome_completo) if f else None


class EHSSessioneDetailSerializer(EHSSessioneListSerializer):
    creata_da_nome = serializers.CharField(source='creata_da.nome_completo', read_only=True)
    partecipanti = EHSPartecipanteSerializer(many=True, read_only=True)
    documenti = EHSSessioneDocumentoSerializer(many=True, read_only=True)
    log = EHSSessioneLogSerializer(many=True, read_only=True)
    cancellazione_consentita = serializers.SerializerMethodField()

    class Meta(EHSSessioneListSerializer.Meta):
        fields = EHSSessioneListSerializer.Meta.fields + [
            'creata_da', 'creata_da_nome',
            'docente_telefono', 'contatto_negozio_telefono',
            'registro_file', 'link_online', 'motivazione_eccezione',
            'calendario_evento', 'data_chiusura', 'chiusa_da', 'note',
            'partecipanti', 'documenti', 'log', 'cancellazione_consentita',
        ]

    def get_cancellazione_consentita(self, obj):
        """Regola dei 7 giorni valutata per l'utente corrente (passato nel context)."""
        request = self.context.get('request')
        if not request:
            return True
        return cancellazione_consentita(obj, request.user)


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
    ehs_corso_nome = serializers.SerializerMethodField()
    ehs_negozio_codice = serializers.SerializerMethodField()
    ehs_negozio_id = serializers.SerializerMethodField()

    class Meta:
        model = Evento
        fields = [
            'id', 'data', 'ora_inizio', 'ora_fine', 'attivita_nome', 'attivita_tipologia',
            'location_display', 'max_partecipanti', 'iscritti_count', 'posti_disponibili',
            'is_ehs', 'ehs_luogo', 'ehs_sessione_id', 'ehs_sessione_stato',
            'ehs_corso_nome', 'ehs_negozio_codice', 'ehs_negozio_id',
        ]

    def get_iscritti_count(self, obj):
        return obj.iscrizioni.count()

    def get_ehs_sessione_id(self, obj):
        sessione = getattr(obj, 'ehs_sessione', None)
        return sessione.id if sessione else None

    def get_ehs_sessione_stato(self, obj):
        sessione = getattr(obj, 'ehs_sessione', None)
        return sessione.stato if sessione else None

    def get_ehs_corso_nome(self, obj):
        sessione = getattr(obj, 'ehs_sessione', None)
        return sessione.corso.nome if sessione else None

    def get_ehs_negozio_codice(self, obj):
        sessione = getattr(obj, 'ehs_sessione', None)
        if not sessione:
            return None
        return sessione.negozio.codice_store or sessione.negozio.nome

    def get_ehs_negozio_id(self, obj):
        sessione = getattr(obj, 'ehs_sessione', None)
        return sessione.negozio_id if sessione else None


# --- Formazione obbligatoria ----------------------------------------------------

class EHSMansioneSerializer(serializers.ModelSerializer):
    class Meta:
        model = EHSMansione
        fields = ['id', 'nome', 'attivo']


class EHSObbligoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EHSObbligo
        fields = ['id', 'corso', 'ruolo', 'mansione', 'facoltativo']


class EHSFormazioneSerializer(serializers.ModelSerializer):
    corso_nome = serializers.CharField(source='corso.nome', read_only=True)
    fonte_display = serializers.CharField(source='get_fonte_display', read_only=True)

    class Meta:
        model = EHSFormazione
        fields = [
            'id', 'utente', 'corso', 'corso_nome', 'data', 'ore', 'aggiornamento', 'scadenza',
            'fonte', 'fonte_display', 'note',
        ]
        read_only_fields = ['scadenza', 'fonte']

    def validate(self, attrs):
        if EHSFormazione.objects.filter(
            utente=attrs['utente'], corso=attrs['corso'], data=attrs['data'],
        ).exists():
            raise serializers.ValidationError({'detail': 'Formazione già registrata per questa persona e data.'})
        return attrs


class EHSPersonaSerializer(serializers.ModelSerializer):
    """Persona soggetta alla matrice obblighi, con mansioni e registro formazioni."""
    nome_completo = serializers.ReadOnlyField()
    ruolo_nome = serializers.CharField(source='ruolo.nome', read_only=True, default=None)
    mansioni = serializers.SerializerMethodField()
    formazioni = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'nome_completo', 'codice_matricola', 'ruolo', 'ruolo_nome', 'mansioni', 'formazioni']

    def get_mansioni(self, obj):
        return [m.id for m in obj.ehs_mansioni.all()]

    def get_formazioni(self, obj):
        return EHSFormazioneSerializer(obj.ehs_formazioni.all(), many=True).data
