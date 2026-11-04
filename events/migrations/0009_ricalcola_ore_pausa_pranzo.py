"""Nuova regola delle ore: l'ora di pausa pranzo si toglie solo se l'aula copre tutta la
fascia 13:00-14:00 (prima si toglieva sempre). Allinea le aule già esistenti:

- aule importate dallo storico ('Dato Storico'): l'import aggiungeva sempre un'ora alla fine
  per compensare la pausa; dove la pausa non c'è, l'ora di fine torna indietro di un'ora e
  le ore restano quelle del file;
- aule EHS: le ore diventano la durata del corso (l'ora di fine si sposta se attraversa il pranzo);
- tutte le altre: le ore si ricalcolano con la nuova regola (es. 9-11 = 2 ore, non più 1).
"""
from datetime import date, datetime, time, timedelta

from django.db import migrations

PAUSA = (time(13, 0), time(14, 0))


def _ore(inizio, fine):
    minuti = (datetime.combine(date.min, fine) - datetime.combine(date.min, inizio)).seconds // 60
    if inizio <= PAUSA[0] and fine >= PAUSA[1]:
        minuti -= 60
    return round(max(0, minuti) / 60, 2)


def _sposta(ora, minuti):
    return (datetime.combine(date.min, ora) + timedelta(minutes=minuti)).time()


def ricalcola(apps, schema_editor):
    Evento = apps.get_model('events', 'Evento')
    EHSSessione = apps.get_model('ehs', 'EHSSessione')
    durate_ehs = dict(EHSSessione.objects.filter(calendario_evento__isnull=False)
                      .values_list('calendario_evento_id', 'durata_ore'))

    for ev in Evento.objects.select_related('host'):
        vecchie = float(ev.ore_totali or 0)
        fine = ev.ora_fine
        if ev.id in durate_ehs:
            durata = float(durate_ehs[ev.id])
            fine = _sposta(ev.ora_inizio, int(durata * 60))
            con_pausa = _sposta(fine, 60)
            if ev.ora_inizio <= PAUSA[0] and fine >= PAUSA[1] and con_pausa > fine:
                fine = con_pausa
        elif ev.host and ev.host.descrizione == 'Dato Storico' and _ore(ev.ora_inizio, fine) != vecchie:
            anticipata = _sposta(fine, -60)
            if anticipata > ev.ora_inizio and _ore(ev.ora_inizio, anticipata) == vecchie:
                fine = anticipata
        nuove = _ore(ev.ora_inizio, fine)
        if fine != ev.ora_fine or nuove != vecchie:
            Evento.objects.filter(pk=ev.pk).update(ora_fine=fine, ore_totali=nuove)


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0008_evento_ehs_luogo_evento_is_ehs'),
        ('ehs', '0011_minimo_partecipanti_fornitori_secondari'),
    ]

    operations = [
        migrations.RunPython(ricalcola, migrations.RunPython.noop),
    ]
