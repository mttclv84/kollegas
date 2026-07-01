from rest_framework import serializers
from .models import Store, StoreCluster, Area


class StoreClusterSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreCluster
        fields = ['store_managers', 'assistant_managers', 'department_managers', 'team_managers', 'visual_managers', 'updated_at']
        read_only_fields = ['updated_at']


class StoreSerializer(serializers.ModelSerializer):
    cluster = StoreClusterSerializer(read_only=True)
    collaboratori_count = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = ['id', 'codice_store', 'nome', 'comune', 'provincia', 'indirizzo', 'email_store', 'portale_password', 'is_active', 'cluster', 'collaboratori_count', 'created_at']
        read_only_fields = ['created_at']

    def get_collaboratori_count(self, obj):
        return obj.collaboratori.filter(is_active=True).count()


class StoreListSerializer(serializers.ModelSerializer):
    collaboratori_count = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = ['id', 'codice_store', 'nome', 'comune', 'provincia', 'email_store', 'portale_password', 'is_active', 'collaboratori_count']

    def get_collaboratori_count(self, obj):
        return obj.collaboratori.filter(is_active=True).count()


class AreaSerializer(serializers.ModelSerializer):
    store_ids = serializers.PrimaryKeyRelatedField(
        queryset=Store.objects.filter(is_active=True), many=True, source='stores', required=False
    )
    store_details = serializers.SerializerMethodField()

    class Meta:
        model = Area
        fields = ['id', 'numero', 'area_manager_retail', 'area_bp', 'store_ids', 'store_details']

    def get_store_details(self, obj):
        return [{'id': s.id, 'nome': s.nome, 'codice_store': s.codice_store} for s in obj.stores.order_by('codice_store')]

    def update(self, instance, validated_data):
        stores = validated_data.pop('stores', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if stores is not None:
            instance.stores.set(stores)
        return instance
