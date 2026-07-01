from django.db import models


class Store(models.Model):
    nome = models.CharField(max_length=200)
    comune = models.CharField(max_length=100)
    provincia = models.CharField(max_length=5)
    indirizzo = models.CharField(max_length=300, blank=True)
    codice_store = models.CharField(max_length=20, blank=True)
    email_store = models.EmailField(unique=True)
    portale_password = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Store'
        verbose_name_plural = 'Store'
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} ({self.comune})'


class StoreCluster(models.Model):
    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name='cluster')
    store_managers = models.PositiveSmallIntegerField(default=1)
    assistant_managers = models.PositiveSmallIntegerField(default=1)
    department_managers = models.PositiveSmallIntegerField(default=1)
    team_managers = models.PositiveSmallIntegerField(default=1)
    visual_managers = models.PositiveSmallIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cluster Store'
        verbose_name_plural = 'Cluster Store'

    def __str__(self):
        return f'Cluster {self.store.nome}'


class Area(models.Model):
    numero = models.IntegerField(unique=True)
    area_manager_retail = models.CharField(max_length=200, blank=True)
    area_bp = models.CharField(max_length=200, blank=True)
    stores = models.ManyToManyField(Store, blank=True, related_name='aree')

    class Meta:
        verbose_name = 'Area'
        verbose_name_plural = 'Aree'
        ordering = ['numero']

    def __str__(self):
        return f'Area {self.numero}'
