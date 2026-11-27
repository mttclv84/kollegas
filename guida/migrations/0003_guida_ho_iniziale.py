"""Primo contenuto della guida per il profilo HO (poi l'Admin la modifica dall'app)."""
from pathlib import Path

from django.db import migrations

CARTELLA = Path(__file__).resolve().parent.parent / 'contenuti_iniziali'

ARGOMENTI = [
    ('Primo accesso e password', 'primo_accesso.png', """1. Entra con la tua email e la password temporanea ricevuta.
2. Scegli una password personale (almeno 8 caratteri) e clicca **Salva password**.

La password temporanea vale fino al 24 dicembre 2026. L'occhio accanto al campo mostra per 1 secondo cosa hai scritto.

**Password dimenticata?** Nella pagina di login clicca **Richiedi reset password**: l'Admin ti invia una password temporanea. Per cambiarla in seguito usa l'icona 🔑 in basso nel menu."""),
    ('Il menu', 'ho_menu.png', """Con il profilo HO gestisci la formazione di tutti i negozi. I gruppi **EHS**, **Report** e **Gestione** si aprono cliccando sul titolo.

- **EHS**: calendario delle aule, fornitori e Panel Formazione EHS, in sola visione.
- **Calendario** ed **Elenco Attività**: le formazioni, da creare e gestire.
- **Report**: % Completamento, Dettaglio e Mapping.
- **Gestione**: account, catalogo attività e host.
- **Eccezioni Calendario**, **Richieste di Modifica**, **Assistenza** e **Stats**.

Il pallino rosso accanto a una voce indica qualcosa da gestire."""),
    ('Creare una formazione', 'ho_nuova_formazione.png', """1. In **Calendario** clicca il giorno della formazione.
2. Scegli orario, **Attività** e **Host**; indica la location (uno store o una location esterna), i posti massimi e la modalità.
3. Clicca **Salva**.

**Più giornate**: con **+ Aggiungi giornata** inserisci le altre date. È una sola edizione: chi è iscritto lo è a tutte le giornate e risulta Partecipato solo se presente a tutte, altrimenti **Parziale**.

Cliccando una formazione già creata puoi modificarla o eliminarla."""),
    ('Iscritti e presenze', 'ho_partecipanti.png', """Dal Calendario clicca la formazione e poi **Gestione Partecipanti**.

- A destra, **Da assegnare**: cerca la persona e clicca **+ Assegna**.
- A sinistra, **Iscritti**: dopo la formazione segna ✓ presente o ✕ assente.
- Clicca **Salva** per confermare; **⬇ PDF** scarica il foglio presenze.

Le persone con **⚠ LA** sono in Long Absence e non contano nelle percentuali."""),
    ('Catalogo Attività', 'ho_catalogo.png', """L'elenco delle attività che si possono programmare in Calendario.

- **+ Nuova Attività** ne crea una; ✏️ la modifica (nome, tipologia, ruoli destinatari).
- 🚫 **Richiedi disattivazione**: la richiesta arriva all'Admin, che la approva o la rifiuta. Le attività non si cancellano mai: lo storico resta nelle Stats.

In **Gestione Host** trovi i formatori da indicare nelle formazioni."""),
    ('Gestione Account', 'ho_account.png', """L'anagrafica di tutte le persone. Filtra per workplace e ruolo, oppure spunta **Solo Long Absence**.

- **+ Nuovo Utente** crea una persona; ✏️ ne modifica i dati, compresi ruolo, negozio e Long Absence.
- **Richieste di Creazione Profilo**: i profili chiesti dagli store; controlla i dati e clicca **✓ Approva**.

I profili Admin e Admin EHS non sono modificabili dall'HO."""),
    ('Richieste di Modifica', 'ho_richieste.png', """Qui arrivano le richieste degli store di togliere una persona da una formazione, con la motivazione.

Aprila e scegli **Approva** (la persona viene tolta dagli iscritti) oppure **Rifiuta**. Con **Filtra per stato** rivedi anche quelle già gestite."""),
    ('Report: Completamento, Dettaglio e Mapping', 'ho_dettaglio.png', """- **% Completamento**: avanzamento dei percorsi GWU RA-TM e GWU TM-DM per Italia, area e negozio, con la lista delle persone.
- **Dettaglio**: tutte le partecipazioni, con filtri per date, ruolo, tipo attività e store ed **⬇ Export Excel**.
- **Mapping**: i collaboratori di ogni store per ruolo, con il commento 💬 modificabile.

**Development** mostra i percorsi di crescita, **Stats** edizioni, partecipanti e ore."""),
    ('Sezione EHS', 'ho_ehs.png', """Per l'HO la sezione EHS è **in sola visione**: aule, iscrizioni e registri li gestiscono Admin, Admin EHS e fornitori.

- **EHS Calendar & Richieste**: il calendario delle aule; clicca un'aula per dettagli e partecipanti.
- **Fornitori EHS**: l'elenco dei fornitori.
- **Panel Formazione EHS**: chi è in regola. 🟢 valida, 🟡 in scadenza, 🔴 da fare o scaduta, 🔵 iscritto."""),
    ('Eccezioni Calendario e domande frequenti', None, """**Eccezioni Calendario**: inserisci festività o date particolari (es. Natale); compaiono nel Calendario con un puntino rosso.

- **Una persona non compare tra i Da assegnare**: controlla in Gestione Account che il profilo sia attivo e abbia negozio e ruolo.
- **La percentuale non torna**: le persone ⚠ LA sono escluse e un corso su più giornate conta solo se fatto per intero.
- **Serve altro?** Scrivi da **Assistenza**: la richiesta arriva all'Admin."""),
]


def crea(apps, schema_editor):
    from django.core.files import File
    from django.core.files.storage import default_storage
    Argomento = apps.get_model('guida', 'ArgomentoGuida')
    if Argomento.objects.filter(profilo='ho').exists():
        return
    for ordine, (titolo, file, testo) in enumerate(ARGOMENTI, start=1):
        immagine = None
        if file and (CARTELLA / file).exists():
            with open(CARTELLA / file, 'rb') as f:
                immagine = default_storage.save(f'guida/{file}', File(f))
        Argomento.objects.create(profilo='ho', titolo=titolo, contenuto=testo, immagine=immagine, ordine=ordine)


class Migration(migrations.Migration):

    dependencies = [
        ('guida', '0002_guida_area_iniziale'),
    ]

    operations = [
        migrations.RunPython(crea, migrations.RunPython.noop),
    ]
