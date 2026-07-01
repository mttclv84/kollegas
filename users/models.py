from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class Role(models.Model):
    nome = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = 'Ruolo'
        verbose_name_plural = 'Ruoli'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email obbligatoria')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('livello_accesso', 'admin')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    LIVELLO_CHOICES = [
        ('admin', 'Admin'),
        ('ho', 'Head Office'),
        ('area', 'Area Manager'),
        ('store', 'Store'),
        ('base', 'Base'),
    ]

    SESSO_CHOICES = [
        ('M', 'Maschio'),
        ('F', 'Femmina'),
        ('NS', 'Non specificato'),
    ]

    cognome = models.CharField(max_length=100)
    nome = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    sesso = models.CharField(max_length=2, choices=SESSO_CHOICES, default='NS')
    livello_accesso = models.CharField(max_length=10, choices=LIVELLO_CHOICES, default='base')
    store = models.ForeignKey(
        'stores.Store', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='collaboratori'
    )
    codice_matricola = models.CharField(max_length=50, blank=True)
    ruolo = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='utenti'
    )
    foto = models.ImageField(upload_to='foto_utenti/', null=True, blank=True)
    commento_mapping = models.TextField(blank=True)
    long_absence = models.BooleanField(default=False)
    raw_password = models.CharField(max_length=128, blank=True, default='')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['cognome', 'nome']

    class Meta:
        verbose_name = 'Utente'
        verbose_name_plural = 'Utenti'
        ordering = ['cognome', 'nome']

    def __str__(self):
        return f'{self.cognome} {self.nome} ({self.email})'

    @property
    def nome_completo(self):
        return f'{self.cognome} {self.nome}'

    @property
    def is_admin(self):
        return self.livello_accesso == 'admin'

    @property
    def is_ho(self):
        return self.livello_accesso == 'ho'

    @property
    def is_area(self):
        return self.livello_accesso == 'area'

    @property
    def is_store(self):
        return self.livello_accesso == 'store'


class PercorsoCrescita(models.Model):
    TIPO_CHOICES = [
        ('promozione', 'Promozione'),
        ('trasferimento', 'Trasferimento'),
        ('cambio_ruolo', 'Cambio Ruolo'),
        ('nota', 'Nota'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='percorso_crescita')
    data = models.DateField()
    tipo_evento = models.CharField(max_length=20, choices=TIPO_CHOICES)
    ruolo_nome = models.CharField(max_length=100, blank=True)
    store_nome = models.CharField(max_length=200, blank=True)
    descrizione = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='percorsi_creati'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Percorso Crescita'
        verbose_name_plural = 'Percorsi Crescita'
        ordering = ['data']


class AuditLog(models.Model):
    AZIONE_CHOICES = [
        ('crea', 'Creazione'),
        ('modifica', 'Modifica'),
        ('elimina', 'Eliminazione'),
        ('disattiva', 'Disattivazione'),
        ('riattiva', 'Riattivazione'),
    ]

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='azioni_log')
    azione = models.CharField(max_length=20, choices=AZIONE_CHOICES)
    target_tipo = models.CharField(max_length=50)
    target_id = models.IntegerField(null=True, blank=True)
    target_repr = models.CharField(max_length=300)
    dettaglio = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Log'
        ordering = ['-created_at']


class RichiestaCreazioneProfilo(models.Model):
    STATO_CHOICES = [
        ('pending', 'In attesa'),
        ('approvata', 'Approvata'),
        ('rifiutata', 'Rifiutata'),
    ]
    richiedente = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='richieste_creazione'
    )
    cognome = models.CharField(max_length=100)
    nome = models.CharField(max_length=100)
    email = models.EmailField()
    sesso = models.CharField(max_length=2, default='NS')
    livello_accesso = models.CharField(max_length=10, default='base')
    store = models.ForeignKey(
        'stores.Store', null=True, blank=True, on_delete=models.SET_NULL
    )
    codice_matricola = models.CharField(max_length=50, blank=True)
    ruolo = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.SET_NULL
    )
    commento_mapping = models.TextField(blank=True)
    stato = models.CharField(max_length=20, choices=STATO_CHOICES, default='pending')
    visto_ho = models.BooleanField(default=False)
    visto_store = models.BooleanField(default=False)
    processed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='richieste_creazione_processate'
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Richiesta Creazione Profilo'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.cognome} {self.nome} ({self.stato})'


class NotificaTrasferimento(models.Model):
    utente_trasferito = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifiche_trasferimento'
    )
    store_origine = models.ForeignKey(
        'stores.Store', on_delete=models.SET_NULL, null=True,
        related_name='trasferimenti_inviati'
    )
    store_destinazione = models.ForeignKey(
        'stores.Store', on_delete=models.SET_NULL, null=True,
        related_name='trasferimenti_ricevuti'
    )
    snap_nome_utente = models.CharField(max_length=200)
    snap_nome_store_origine = models.CharField(max_length=200)
    letta = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class RichiestaEliminazioneProfilo(models.Model):
    STATO_CHOICES = [
        ('pending', 'In attesa'),
        ('approvata', 'Approvata'),
        ('rifiutata', 'Rifiutata'),
    ]
    target_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='richieste_eliminazione_ricevute'
    )
    richiedente = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='richieste_eliminazione_inviate'
    )
    snap_nome = models.CharField(max_length=200)
    stato = models.CharField(max_length=20, choices=STATO_CHOICES, default='pending')
    processed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='richieste_eliminazione_processate'
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    visto_ho = models.BooleanField(default=False)
    visto_store = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Richiesta Eliminazione Profilo'
        ordering = ['-created_at']

    def __str__(self):
        return f'Eliminazione #{self.id} — {self.snap_nome} ({self.stato})'


class UserDocument(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='documents')
    nome_file = models.CharField(max_length=255)
    file = models.FileField(upload_to='user_docs/%Y/%m/')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='docs_uploaded')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
