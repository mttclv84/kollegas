from django.db import migrations

# Corsi della matrice obblighi EHS (ore dalla tabella ruoli/mansioni, validità dalle
# regole del file formazione dei negozi). SCALE esiste già (0002) e non viene toccato.
CORSI = [
    # codice, nome, ore, scadenza_giorni, ore_aggiornamento
    ('DIRIGENTI', 'Dirigenti', 12, 1825, 6),
    ('PREPOSTI', 'Preposti', 12, 730, 6),
    ('TRANSPALLET', 'Transpallet', 4, None, None),
    ('COMPATTATORE', 'Compattatore', 2, None, None),
    ('LAVORA_CALDO', 'Lavora a caldo', 0.25, None, None),
    ('PINS', 'PiNS', 0.25, None, None),
    ('ENERGY_CHAMPION', 'Energy Champion', 0.25, None, None),
]

MANSIONI = ['EHS OPS in Store Lead', 'Stockroom', 'Cashoffice', 'Visual']

EHS_OPS = 'EHS OPS in Store Lead'
# codice corso -> (ruoli obbligatori, ruoli facoltativi, mansioni obbligatorie)
MATRICE = {
    'DIRIGENTI': (['Store Manager', 'Assistant Manager', 'P&C Store Business Partner'],
                  ['Department Manager', 'Visual Manager'], []),
    'PREPOSTI': (['P&C Coordinator', 'Department Manager', 'Team Manager', 'Visual Manager'],
                 ['GWU RA-TM'], [EHS_OPS]),
    'TRANSPALLET': (['P&C Coordinator', 'Department Manager', 'Team Manager', 'Visual Manager'],
                    [], [EHS_OPS, 'Stockroom']),
    'COMPATTATORE': (['Assistant Manager', 'P&C Coordinator', 'Department Manager', 'Team Manager', 'Visual Manager'],
                     [], [EHS_OPS, 'Stockroom']),
    'LAVORA_CALDO': (['Store Manager', 'P&C Store Business Partner', 'Department Manager', 'Visual Manager'],
                     [], [EHS_OPS]),
    'PINS': (['Store Manager', 'P&C Store Business Partner', 'Department Manager', 'Visual Manager'],
             [], [EHS_OPS]),
    'ENERGY_CHAMPION': (['Store Manager'], [], [EHS_OPS]),
    'SCALE': (['Visual Manager', 'Team Visual Manager'], [], ['Visual']),
}


def seed(apps, schema_editor):
    EHSCorso = apps.get_model('ehs', 'EHSCorso')
    EHSMansione = apps.get_model('ehs', 'EHSMansione')
    EHSObbligo = apps.get_model('ehs', 'EHSObbligo')
    EHSFormazione = apps.get_model('ehs', 'EHSFormazione')
    EHSPartecipante = apps.get_model('ehs', 'EHSPartecipante')
    Role = apps.get_model('users', 'Role')

    corsi = {}
    for codice, nome, ore, giorni, ore_agg in CORSI:
        # Un corso con lo stesso nome creato a mano dall'Admin viene riusato, non duplicato.
        corso = (EHSCorso.objects.filter(codice=codice).first()
                 or EHSCorso.objects.filter(nome__iexact=nome).first())
        if corso is None:
            corso = EHSCorso.objects.create(codice=codice, nome=nome, durata_ore=ore,
                                            scadenza_giorni=giorni, ore_aggiornamento=ore_agg)
        corsi[codice] = corso
    scale = EHSCorso.objects.filter(codice='SCALE').first()
    if scale:
        corsi['SCALE'] = scale

    mansioni = {nome: EHSMansione.objects.get_or_create(nome=nome)[0] for nome in MANSIONI}
    ruoli = {r.nome: r for r in Role.objects.all()}

    for codice, (obbligatori, facoltativi, mansioni_obbl) in MATRICE.items():
        corso = corsi.get(codice)
        if corso is None:
            continue
        for nome in obbligatori + facoltativi:
            if nome in ruoli:
                EHSObbligo.objects.get_or_create(corso=corso, ruolo=ruoli[nome],
                                                 defaults={'facoltativo': nome in facoltativi})
        for nome in mansioni_obbl:
            EHSObbligo.objects.get_or_create(corso=corso, mansione=mansioni[nome])

    # Le aule EHS già chiuse entrano nel registro formazioni.
    for p in (EHSPartecipante.objects.filter(completato=True, presente=True)
              .select_related('sessione')):
        data = (p.completato_il or p.sessione.data_chiusura or p.sessione.data_confermata)
        if data is None:
            continue
        EHSFormazione.objects.get_or_create(
            utente_id=p.utente_id, corso_id=p.sessione.corso_id, data=data.date(),
            defaults={'ore': p.sessione.durata_ore, 'scadenza': p.scadenza_formazione,
                      'fonte': 'aula', 'partecipante': p},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('ehs', '0008_formazione_obbligatoria'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
