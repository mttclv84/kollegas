from rest_framework import serializers

from .models import RichiestaAssistenza


class RichiestaAssistenzaSerializer(serializers.ModelSerializer):
    utente_nome = serializers.CharField(source='utente.nome_completo', read_only=True)
    utente_email = serializers.CharField(source='utente.email', read_only=True)
    utente_profilo = serializers.CharField(source='utente.get_livello_accesso_display', read_only=True)
    utente_negozio = serializers.CharField(source='utente.store.nome', read_only=True, default='')
    risposto_da_nome = serializers.CharField(source='risposto_da.nome_completo', read_only=True, default='')

    class Meta:
        model = RichiestaAssistenza
        fields = ['id', 'tipo', 'sezione', 'testo', 'stato', 'risposta', 'risposta_il', 'risposto_da_nome',
                  'risposta_letta', 'creata_il', 'utente_nome', 'utente_email', 'utente_profilo', 'utente_negozio']
        read_only_fields = ['stato', 'risposta', 'risposta_il', 'risposta_letta', 'creata_il']

    def validate(self, attrs):
        if not (attrs.get('testo') or '').strip():
            raise serializers.ValidationError({'testo': 'Scrivi il testo della richiesta.'})
        if attrs.get('tipo') == 'aiuto' and not (attrs.get('sezione') or '').strip():
            raise serializers.ValidationError({'sezione': 'Scegli la sezione per cui ti serve aiuto.'})
        if attrs.get('tipo') != 'aiuto':
            attrs['sezione'] = ''
        return attrs


class GestioneRichiestaSerializer(serializers.ModelSerializer):
    """L'Admin risponde e cambia lo stato."""

    class Meta:
        model = RichiestaAssistenza
        fields = ['risposta', 'stato']
