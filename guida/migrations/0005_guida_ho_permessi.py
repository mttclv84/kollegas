"""Guida HO allineata ai permessi del 27/11/2026: formazioni e richieste di modifica solo proprie,
account solo Base, percorsi Development eliminabili solo dall'Admin.
Sostituisce solo i passaggi interessati, così eventuali altre modifiche dell'Admin restano."""
from django.db import migrations

SOSTITUZIONI = {
    'Creare una formazione': [(
        "Cliccando una formazione già creata puoi modificarla o eliminarla.",
        "Puoi annullare (con motivazione) solo le formazioni create da te: quelle degli altri le annulla chi le ha "
        "create o l'Admin. Iscritti e presenze invece li gestisci su tutte le formazioni.",
    )],
    'Gestione Account': [(
        """- **+ Nuovo Utente** crea una persona; ✏️ ne modifica i dati, compresi ruolo, negozio e Long Absence.
- **Richieste di Creazione Profilo**: i profili chiesti dagli store; controlla i dati e clicca **✓ Approva**.

I profili Admin e Admin EHS non sono modificabili dall'HO.""",
        """- **+ Nuovo Utente** crea una persona con profilo **Base**.
- ✏️ modifica i dati di un profilo Base, compresi ruolo, negozio e Long Absence; 🗑️ lo disattiva.
- **Richieste di Creazione e di Eliminazione Profilo**: quelle degli store sui profili Base; controlla i dati e clicca **✓ Approva** o **✕ Rifiuta**.

Tutti gli altri profili (Area Manager, Store, HO, Admin, fornitori) li crea e li modifica solo l'Admin: per loro le richieste mostrano "La gestisce l'Admin".""",
    )],
    'Richieste di Modifica': [(
        "Qui arrivano le richieste degli store di togliere una persona da una formazione, con la motivazione.",
        "Qui arrivano le richieste degli store di togliere una persona da una formazione **creata da te**, con la "
        "motivazione. Quelle sulle formazioni degli altri le gestisce chi le ha create o l'Admin.",
    )],
    'Report: Completamento, Dettaglio e Mapping': [(
        "**Development** mostra i percorsi di crescita,",
        "**Development** mostra i percorsi di crescita (solo l'Admin può eliminarli),",
    )],
    'Eccezioni Calendario e domande frequenti': [(
        "- **Serve altro?**",
        "- **Non vedo il pulsante Elimina su una formazione**: l'ha creata un altro HO o l'Admin; chiedi a loro.\n"
        "- **Non riesco a modificare un account**: l'HO modifica solo i profili Base, gli altri li gestisce l'Admin.\n"
        "- **Serve altro?**",
    )],
}


def aggiorna(apps, schema_editor):
    Argomento = apps.get_model('guida', 'ArgomentoGuida')
    for titolo, coppie in SOSTITUZIONI.items():
        for a in Argomento.objects.filter(profilo='ho', titolo=titolo):
            testo = a.contenuto
            for vecchio, nuovo in coppie:
                testo = testo.replace(vecchio, nuovo)
            if testo != a.contenuto:
                a.contenuto = testo
                a.save(update_fields=['contenuto'])


class Migration(migrations.Migration):

    dependencies = [
        ('guida', '0004_rinomina_ehs_calendar_aule'),
    ]

    operations = [
        migrations.RunPython(aggiorna, migrations.RunPython.noop),
    ]
