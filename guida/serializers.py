from rest_framework import serializers

from .models import ArgomentoGuida


class ArgomentoGuidaSerializer(serializers.ModelSerializer):
    # Percorso relativo del file (es. "guida/menu.png"): il frontend lo apre da /media/.
    immagine_percorso = serializers.SerializerMethodField()
    rimuovi_immagine = serializers.BooleanField(write_only=True, required=False, default=False)
    # Negli invii con file (multipart) un booleano assente varrebbe False: di default l'argomento è visibile.
    attivo = serializers.BooleanField(required=False, default=True)
    aggiornato_da_nome = serializers.CharField(source='aggiornato_da.nome_completo', read_only=True, default='')

    class Meta:
        model = ArgomentoGuida
        fields = ['id', 'profilo', 'titolo', 'contenuto', 'immagine', 'immagine_percorso', 'rimuovi_immagine',
                  'ordine', 'attivo', 'aggiornato_il', 'aggiornato_da_nome']
        read_only_fields = ['aggiornato_il']
        extra_kwargs = {'immagine': {'write_only': True, 'required': False}}

    def get_immagine_percorso(self, obj):
        return obj.immagine.name if obj.immagine else None

    def _salva(self, istanza, dati):
        if dati.pop('rimuovi_immagine', False) and not dati.get('immagine') and istanza.immagine:
            istanza.immagine.delete(save=False)
            istanza.immagine = None
        for campo, valore in dati.items():
            setattr(istanza, campo, valore)
        istanza.aggiornato_da = self.context['request'].user
        istanza.save()
        return istanza

    def create(self, validated_data):
        if 'ordine' not in validated_data:
            ultimo = ArgomentoGuida.objects.filter(profilo=validated_data.get('profilo')).order_by('-ordine').first()
            validated_data['ordine'] = (ultimo.ordine + 1) if ultimo else 1
        return self._salva(ArgomentoGuida(), validated_data)

    def update(self, instance, validated_data):
        return self._salva(instance, validated_data)
