from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from participants.models import Iscrizione

from .models import EHSPartecipante, EHSSessione


@receiver(post_save, sender=Iscrizione)
def sync_ehs_partecipante(sender, instance, created, **kwargs):
    """Collega un'iscrizione standard Kollegas a un EHSPartecipante quando l'evento
    a cui si riferisce è l'evento 'leggero' sincronizzato di una sessione EHS (§5).
    L'iscrizione avviene sempre dentro la sezione EHS, riusando lo stesso componente
    standard (GestionePartecipanti) — il modello sottostante resta quello esistente."""
    if not created or not instance.evento.is_ehs:
        return
    try:
        sessione = instance.evento.ehs_sessione
    except EHSSessione.DoesNotExist:
        return
    EHSPartecipante.objects.get_or_create(sessione=sessione, utente=instance.user)


@receiver(post_delete, sender=Iscrizione)
def rimuovi_ehs_partecipante(sender, instance, **kwargs):
    """Specchio della sync in creazione: se qualcuno viene rimosso dall'iscrizione
    standard prima che l'aula si sia svolta, rimuove anche il partecipante EHS
    corrispondente. Non tocca lo storico dopo SVOLTA/COMPLETATA: registri e attestati
    già emessi restano intatti anche se l'iscrizione viene cancellata altrove."""
    if not instance.evento.is_ehs:
        return
    try:
        sessione = instance.evento.ehs_sessione
    except EHSSessione.DoesNotExist:
        return
    if sessione.stato in ('SVOLTA', 'COMPLETATA'):
        return
    EHSPartecipante.objects.filter(sessione=sessione, utente=instance.user).delete()
