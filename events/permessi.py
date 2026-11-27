"""Chi può modificare o annullare una formazione."""

MESSAGGIO_NON_TUA = ('Puoi modificare o annullare solo le formazioni create da te. '
                     "Per questa rivolgiti a chi l'ha creata o all'Admin.")


def puo_gestire_evento(user, evento):
    """Admin e Admin EHS: tutte. HO: solo quelle create da sé (le formazioni senza autore,
    es. importate dal vecchio portale, restano all'Admin). Gli altri profili: nessuna."""
    livello = getattr(user, 'livello_accesso', None)
    if livello in ('admin', 'admin_ehs'):
        return True
    if livello == 'ho':
        return evento.created_by_id is not None and evento.created_by_id == user.id
    return False
