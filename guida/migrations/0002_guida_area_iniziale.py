"""Primo contenuto della guida per il profilo Area (poi l'Admin la modifica dall'app)."""
from pathlib import Path

from django.db import migrations

CARTELLA = Path(__file__).resolve().parent.parent / 'contenuti_iniziali'

ARGOMENTI = [
    ('Primo accesso e password', 'primo_accesso.png', """1. Entra con la tua email e la password temporanea ricevuta.
2. Scegli una password personale (almeno 8 caratteri) e clicca **Salva password**.

La password temporanea vale fino al 24 dicembre 2026. L'occhio accanto al campo mostra per 1 secondo cosa hai scritto.

**Password dimenticata?** Nella pagina di login clicca **Richiedi reset password**: l'Admin ti invia una password temporanea. Per cambiarla in seguito usa l'icona 🔑 in basso nel menu."""),
    ('Il menu', 'menu.png', """Con il profilo Area consulti tutti i negozi senza modificare nulla. I gruppi **EHS** e **Report** si aprono cliccando sul titolo.

- **EHS Calendar & Richieste**: le aule di formazione EHS.
- **Panel Formazione EHS**: chi è in regola con la formazione obbligatoria EHS.
- **Calendario**: tutte le formazioni, giorno per giorno.
- **% Completamento**: avanzamento dei percorsi GWU RA-TM e GWU TM-DM.
- **Dettaglio**: tutte le partecipazioni, con export Excel.
- **Mapping**, **Development** e **Stats**: struttura dei negozi, percorsi di crescita e numeri della formazione."""),
    ('Calendario e partecipanti', 'calendario.png', """Clicca una formazione per vederne i dettagli, poi **Gestione Partecipanti** per l'elenco degli iscritti (solo lettura).

- **g1/2, g2/2**: formazione su più giornate; chi non le fa tutte risulta **Parziale** e non conta come formato.
- **⚠ LA**: persona in Long Absence, esclusa dalle percentuali.
- I riquadri grigi sono formazioni EHS: si consultano nella sezione EHS."""),
    ('% Completamento', 'completamento.png', """1. Scegli il percorso: **GWU RA-TM** oppure **GWU TM-DM**.
2. Leggi i totali Italia e le schede delle aree.
3. Con la 🔍 di un'area apri il dettaglio dell'area.

Verde = 80% o più, arancione = 50–79%, rosso = sotto il 50%. Le persone ⚠ LA non contano nelle percentuali."""),
    ("Dettaglio di un'area: Negozi e Persone", 'area_persone.png', """Nel dettaglio di un'area scegli la vista:

- **Negozi**: la percentuale per corso e ruolo di ogni negozio; il pallino rosso indica il negozio con più persone da formare.
- **Persone**: ogni avente diritto con negozio e ruolo; ✓ corso fatto, – da fare.

Con il menu a tendina scegli un solo negozio; le righe si vedono 10 per pagina."""),
    ('Dettaglio', 'dettaglio.png', """L'elenco di tutte le partecipazioni. Filtra per date, ruolo, tipo attività e store; **⬇ Export Excel** scarica le righe filtrate.

Lo stato è Iscritto (azzurro), Partecipato (verde) o Assente (rosso)."""),
    ('Mapping, Development e Stats', None, """- **Mapping**: scegli lo store e vedi i collaboratori per ruolo; 💬 apre il commento (solo lettura).
- **Development**: il percorso di crescita di una persona. Sezione in costruzione: per provarla cerca ALAIMO.
- **Stats**: edizioni, partecipanti e ore, con filtri per tipo, attività e periodo ed export Excel."""),
    ('Sezione EHS', 'ehs.png', """- **EHS Calendar & Richieste**: il calendario delle aule EHS e la scheda **Aule** con l'elenco; clicca un'aula per dettagli e partecipanti.
- **Panel Formazione EHS**: chi è in regola con la formazione obbligatoria. 🟢 valida, 🟡 in scadenza, 🔴 da fare o scaduta, 🔵 iscritto."""),
    ('Cosa non puoi fare e domande frequenti', None, """Il profilo Area consulta ma non modifica: iscrizioni, presenze, formazioni, aule EHS e account li gestiscono Admin e HO.

- **Password temporanea scaduta**: usa **Richiedi reset password** nella pagina di login.
- **Non trovo una persona nel Dettaglio**: il suo profilo è disattivato; resta solo nelle Stats.
- **La percentuale non torna**: le persone ⚠ LA sono escluse e un corso su più giornate conta solo se fatto per intero."""),
]


def crea(apps, schema_editor):
    from django.core.files import File
    from django.core.files.storage import default_storage
    Argomento = apps.get_model('guida', 'ArgomentoGuida')
    if Argomento.objects.filter(profilo='area').exists():
        return
    for ordine, (titolo, file, testo) in enumerate(ARGOMENTI, start=1):
        immagine = None
        if file and (CARTELLA / file).exists():
            with open(CARTELLA / file, 'rb') as f:
                immagine = default_storage.save(f'guida/{file}', File(f))
        Argomento.objects.create(profilo='area', titolo=titolo, contenuto=testo, immagine=immagine, ordine=ordine)


class Migration(migrations.Migration):

    dependencies = [
        ('guida', '0001_initial'),
        ('archivio', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crea, migrations.RunPython.noop),
    ]
