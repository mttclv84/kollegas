from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import AttivitaCatalogo

User = get_user_model()


class CatalogoCompletoTest(TestCase):
    def test_catalogo_restituisce_tutte_le_attivita(self):
        for i in range(60):
            AttivitaCatalogo.objects.create(nome=f'Attività {i:02d}', tipologia='altro')
        c = APIClient()
        c.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A',
                                                      livello_accesso='admin'))
        attive = AttivitaCatalogo.objects.filter(is_active=True).count()
        self.assertGreater(attive, 50)
        self.assertEqual(len(c.get('/api/attivita/').json()), attive)


class RichiestaDisattivazioneHOTest(TestCase):
    def setUp(self):
        self.att = AttivitaCatalogo.objects.create(nome='Corso da togliere', tipologia='ld')
        self.ho, self.admin, self.area = APIClient(), APIClient(), APIClient()
        self.ho.force_authenticate(User.objects.create_user(email='h@x.it', password='x', cognome='H', nome='H', livello_accesso='ho'))
        self.admin.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A', livello_accesso='admin'))
        self.area.force_authenticate(User.objects.create_user(email='r@x.it', password='x', cognome='R', nome='R', livello_accesso='area'))
        self.url = f'/api/attivita/{self.att.id}/richiedi-disattivazione/'

    def _in_attesa(self):
        return next(a for a in self.admin.get('/api/attivita/').json() if a['id'] == self.att.id)['disattivazione_in_attesa']

    def test_ho_chiede_e_admin_approva(self):
        self.assertEqual(self.area.post(self.url).status_code, 403)
        self.assertEqual(self.admin.post(self.url).status_code, 403)
        self.assertEqual(self.ho.post(self.url).status_code, 201)
        self.assertEqual(self.ho.post(self.url).status_code, 400)  # già in attesa
        self.att.refresh_from_db()
        self.assertTrue(self.att.is_active and self._in_attesa())
        self.assertEqual(self.ho.get('/api/richieste-disattivazione-attivita/').status_code, 403)
        richieste = self.admin.get('/api/richieste-disattivazione-attivita/').json()
        self.assertEqual([(r['attivita_nome'], r['richiedente_nome']) for r in richieste], [('Corso da togliere', 'H H')])
        url = f"/api/richieste-disattivazione-attivita/{richieste[0]['id']}/"
        self.assertEqual(self.ho.post(url, {'azione': 'approva'}, format='json').status_code, 403)
        self.assertEqual(self.admin.post(url, {'azione': 'approva'}, format='json').status_code, 200)
        self.att.refresh_from_db()
        self.assertFalse(self.att.is_active)
        self.assertEqual(self.admin.get('/api/richieste-disattivazione-attivita/').json(), [])

    def test_admin_rifiuta_e_l_attivita_resta(self):
        self.ho.post(self.url)
        richiesta = self.admin.get('/api/richieste-disattivazione-attivita/').json()[0]
        self.admin.post(f"/api/richieste-disattivazione-attivita/{richiesta['id']}/", {'azione': 'rifiuta'}, format='json')
        self.att.refresh_from_db()
        self.assertTrue(self.att.is_active)
        self.assertFalse(self._in_attesa())
        self.assertEqual(self.ho.post(self.url).status_code, 201)  # si può chiedere di nuovo


class DisattivazioneAttivitaTest(TestCase):
    def test_elimina_disattiva_solo_admin_e_conserva_lo_storico(self):
        from datetime import date, time
        from .models import Evento, Host
        att = AttivitaCatalogo.objects.create(nome='Da disattivare', tipologia='ld')
        evento = Evento.objects.create(data=date(2026, 1, 10), ora_inizio=time(9), ora_fine=time(10), attivita=att,
                                       host=Host.objects.get_or_create(descrizione='T', defaults={'posizione': 'interno'})[0])
        ho, admin = APIClient(), APIClient()
        ho.force_authenticate(User.objects.create_user(email='h@x.it', password='x', cognome='H', nome='H', livello_accesso='ho'))
        admin.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A', livello_accesso='admin'))
        self.assertEqual(ho.delete(f'/api/attivita/{att.id}/').status_code, 403)
        self.assertEqual(admin.delete(f'/api/attivita/{att.id}/').status_code, 204)
        att.refresh_from_db()
        self.assertFalse(att.is_active)
        self.assertTrue(Evento.objects.filter(pk=evento.pk).exists())
        ids = lambda url: [a['id'] for a in admin.get(url).json()]
        self.assertNotIn(att.id, ids('/api/attivita/'))
        self.assertIn(att.id, ids('/api/attivita/?tutte=1'))
        self.assertEqual(ids('/api/attivita/?disattivate=1'), [att.id])
        self.assertEqual(ho.patch(f'/api/attivita/{att.id}/', {'is_active': True}, format='json').status_code, 403)
        self.assertEqual(admin.patch(f'/api/attivita/{att.id}/', {'is_active': True}, format='json').status_code, 200)


class PresenzeCompleteTest(TestCase):
    def test_presenze_complete_quando_tutti_presenti_o_assenti(self):
        from datetime import date, time
        from participants.models import Iscrizione
        from .models import Evento, Host
        evento = Evento.objects.create(
            data=date(2026, 1, 10), ora_inizio=time(9), ora_fine=time(10),
            attivita=AttivitaCatalogo.objects.create(nome='Corso', tipologia='ld'),
            host=Host.objects.get_or_create(descrizione='T', defaults={'posizione': 'interno'})[0])
        c = APIClient()
        c.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A',
                                                      livello_accesso='admin'))
        def stato():
            dati = c.get('/api/eventi/', {'data_da': '2026-01-01', 'data_a': '2026-01-31'}).json()
            dati = dati['results'] if isinstance(dati, dict) else dati
            return next(e for e in dati if e['id'] == evento.id)['presenze_complete']
        self.assertFalse(stato())  # nessun iscritto
        u1 = User.objects.create_user(email='u1@x.it', password='x', cognome='U', nome='1')
        u2 = User.objects.create_user(email='u2@x.it', password='x', cognome='U', nome='2')
        i1 = Iscrizione.objects.create(evento=evento, user=u1, stato='partecipato')
        Iscrizione.objects.create(evento=evento, user=u2, stato='iscritto')
        self.assertFalse(stato())
        Iscrizione.objects.filter(user=u2).update(stato='assente')
        self.assertTrue(stato())
        i1.delete()
        self.assertTrue(stato())


class PausaPranzoTest(TestCase):
    def _ore(self, inizio, fine):
        from datetime import date, time
        from .models import Evento, Host
        evento = Evento.objects.create(
            data=date(2026, 1, 10), ora_inizio=time(*inizio), ora_fine=time(*fine),
            attivita=AttivitaCatalogo.objects.create(nome=f'C{inizio}{fine}', tipologia='ld'),
            host=Host.objects.get_or_create(descrizione='T', defaults={'posizione': 'interno'})[0])
        return float(evento.ore_totali)

    def test_pausa_solo_se_copre_13_14(self):
        self.assertEqual(self._ore((9, 0), (11, 0)), 2.0)    # mattina: nessuna pausa
        self.assertEqual(self._ore((14, 0), (15, 0)), 1.0)   # pomeriggio: nessuna pausa
        self.assertEqual(self._ore((9, 0), (13, 0)), 4.0)
        self.assertEqual(self._ore((9, 0), (18, 0)), 8.0)    # giornata intera: meno un'ora


class EdizioneMultiGiornataTest(TestCase):
    """Formazione su più giornate: un salvataggio, una iscrizione, una sola partecipazione."""

    def setUp(self):
        from .models import Host
        self.att = AttivitaCatalogo.objects.create(nome='GWU TM-DM Leadership', tipologia='ld')
        self.host = Host.objects.create(descrizione='Trainer', posizione='interno')
        self.altro_host = Host.objects.create(descrizione='Altro', posizione='interno')
        self.admin = APIClient()
        self.admin.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A',
                                                               livello_accesso='admin'))

    def _crea(self, giornate, data='2027-03-01'):
        return self.admin.post('/api/eventi/', {
            'data': data, 'ora_inizio': '09:00', 'ora_fine': '17:00', 'attivita': self.att.id, 'host': self.host.id,
            'location_esterna': 'Milano', 'max_partecipanti': 10, 'giornate': giornate}, format='json')

    def _edizione(self):
        from .models import Evento
        r = self._crea([{'data': '2027-03-02', 'ora_inizio': '09:00', 'ora_fine': '13:00'},
                        {'data': '2027-03-05', 'ora_inizio': '14:00', 'ora_fine': '18:00'}])
        self.assertEqual(r.status_code, 201, r.content)
        return list(Evento.objects.filter(edizione__isnull=False).order_by('data'))

    def test_un_salvataggio_crea_tutte_le_giornate(self):
        giornate = self._edizione()
        self.assertEqual(len(giornate), 3)
        self.assertEqual(len({g.edizione_id for g in giornate}), 1)
        self.assertEqual([float(g.ore_totali) for g in giornate], [7.0, 4.0, 4.0])
        self.assertEqual({(g.host_id, g.location_esterna, g.max_partecipanti) for g in giornate},
                         {(self.host.id, 'Milano', 10)})
        elenco = self.admin.get('/api/eventi/', {'data_da': '2027-03-01', 'data_a': '2027-03-31'}).json()
        elenco = elenco['results'] if isinstance(elenco, dict) else elenco
        self.assertEqual([(e['giornata'], e['giornate_totali']) for e in elenco], [(1, 3), (2, 3), (3, 3)])
        dettaglio = self.admin.get(f'/api/eventi/{giornate[1].id}/').json()
        self.assertEqual([g['id'] for g in dettaglio['giornate']], [g.id for g in giornate])

    def test_giornate_non_valide(self):
        from .models import Evento
        self.assertEqual(self._crea([{'data': '2027-03-01', 'ora_inizio': '09:00', 'ora_fine': '13:00'}]).status_code, 400)
        self.assertEqual(self._crea([{'data': '2027-03-02', 'ora_inizio': '13:00', 'ora_fine': '09:00'}]).status_code, 400)
        self.assertEqual(self._crea([{'data': '2027-03-02'}]).status_code, 400)
        self.assertFalse(Evento.objects.exists())

    def test_iscrizione_e_cancellazione_valgono_per_tutte_le_giornate(self):
        from participants.models import Iscrizione
        giornate = self._edizione()
        persona = User.objects.create_user(email='p@x.it', password='x', cognome='P', nome='P')
        r = self.admin.post('/api/iscrizioni/', {'evento': giornate[0].id, 'user': persona.id, 'stato': 'iscritto'},
                            format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Iscrizione.objects.filter(user=persona).count(), 3)
        seconda = Iscrizione.objects.get(user=persona, evento=giornate[1])
        self.assertEqual(self.admin.delete(f'/api/iscrizioni/{seconda.id}/').status_code, 204)
        self.assertFalse(Iscrizione.objects.filter(user=persona).exists())

    def test_modifiche_comuni_e_annullamento(self):
        from .models import Edizione, Evento
        giornate = self._edizione()
        r = self.admin.patch(f'/api/eventi/{giornate[0].id}/', {'host': self.altro_host.id, 'data': '2027-02-28'},
                             format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(Evento.objects.values_list('host_id', flat=True)), {self.altro_host.id})
        self.assertEqual(sorted(str(d) for d in Evento.objects.values_list('data', flat=True)),
                         ['2027-02-28', '2027-03-02', '2027-03-05'])
        self.assertEqual(self.admin.delete(f'/api/eventi/{giornate[2].id}/?motivazione=annullato').status_code, 204)
        self.assertFalse(Evento.objects.exists())
        self.assertFalse(Edizione.objects.exists())

    def test_statistiche_e_parziali(self):
        from participants.models import Iscrizione
        from users.views import _compute_stats
        giornate = self._edizione()
        tutto = User.objects.create_user(email='t@x.it', password='x', cognome='T', nome='T', sesso='M')
        parziale = User.objects.create_user(email='q@x.it', password='x', cognome='Q', nome='Q', sesso='F')
        for g in giornate:
            Iscrizione.objects.create(evento=g, user=tutto, stato='partecipato')
            Iscrizione.objects.create(evento=g, user=parziale, stato='assente' if g == giornate[2] else 'partecipato')
        _, totale = _compute_stats({})
        self.assertEqual((totale['num_edizioni'], totale['maschi'], totale['femmine']), (1, 1, 0))
        self.assertEqual(totale['ore_erogate'], 15.0 + 11.0)  # ore solo dei giorni frequentati
        esiti = {i['user']: i['esito_edizione']
                 for i in self.admin.get('/api/iscrizioni/', {'evento': giornate[0].id}).json()}
        self.assertEqual(esiti, {tutto.id: 'partecipato', parziale.id: 'parziale'})

    def test_completamento_conta_solo_chi_ha_fatto_tutte_le_giornate(self):
        from participants.models import Iscrizione
        from stores.models import Store
        from users.models import Role
        giornate = self._edizione()
        negozio = Store.objects.create(nome='Roma', comune='Roma', provincia='RM', email_store='rm@x.it')
        dm = Role.objects.create(nome='Department Manager')
        completo = User.objects.create_user(email='c@x.it', password='x', cognome='C', nome='C', store=negozio, ruolo=dm)
        parziale = User.objects.create_user(email='z@x.it', password='x', cognome='Z', nome='Z', store=negozio, ruolo=dm)
        for g in giornate:
            Iscrizione.objects.create(evento=g, user=completo, stato='partecipato')
            Iscrizione.objects.create(evento=g, user=parziale, stato='partecipato' if g == giornate[0] else 'assente')
        corsi = self.admin.get(f'/api/stores/{negozio.id}/completamento/', {'programma': 'gwu-tm-dm'}).json()['corsi']
        self.assertEqual([(c['nome_breve'], c['completato'], c['parziali'], c['totale']) for c in corsi],
                         [('GWU TM-DM Leadership', 1, 1, 2)])
        zoom = self.admin.get(f'/api/stores/{negozio.id}/completamento/zoom/', {'programma': 'gwu-tm-dm'}).json()
        self.assertEqual({u['cognome']: (u['fatti'], u['parziali']) for u in zoom['utenti']},
                         {'C': ([self.att.id], []), 'Z': ([], [self.att.id])})


class AccorpaAuleTest(TestCase):
    def test_accorpa_le_aule_in_edizioni(self):
        from datetime import date, time
        from io import StringIO
        from django.core.management import call_command
        from participants.models import Iscrizione
        from .models import Evento, Host
        host = Host.objects.create(descrizione='T', posizione='interno')
        aula1 = AttivitaCatalogo.objects.create(nome='DM Leadership - Aula 1/2', tipologia='ld')
        aula2 = AttivitaCatalogo.objects.create(nome='DM Leadership - Aula 2/2', tipologia='ld')

        def ev(att, giorno):
            return Evento.objects.create(data=giorno, ora_inizio=time(9), ora_fine=time(17), attivita=att, host=host)

        g1, g1b = ev(aula1, date(2024, 5, 29)), ev(aula1, date(2024, 5, 29))
        g2, g2b = ev(aula2, date(2024, 5, 30)), ev(aula2, date(2024, 5, 30))
        sola = ev(aula1, date(2024, 9, 1))
        persone = [User.objects.create_user(email=f'u{i}@x.it', password='x', cognome='U', nome=str(i)) for i in range(4)]
        # Due edizioni nello stesso giorno: l'abbinamento segue le persone in comune.
        for p, giorno1, giorno2 in ((persone[0], g1, g2b), (persone[1], g1b, g2)):
            Iscrizione.objects.create(evento=giorno1, user=p, stato='partecipato')
            Iscrizione.objects.create(evento=giorno2, user=p, stato='partecipato')
        Iscrizione.objects.create(evento=g1, user=persone[2], stato='partecipato')  # solo il primo giorno
        Iscrizione.objects.create(evento=sola, user=persone[3], stato='partecipato')

        call_command('accorpa_aule', stdout=StringIO())
        self.assertFalse(Evento.objects.filter(edizione__isnull=False).exists())  # prova: nulla salvato
        out = StringIO()
        call_command('accorpa_aule', applica=True, stdout=out)
        for e in (g1, g1b, g2, g2b, sola):
            e.refresh_from_db()
        nuova = AttivitaCatalogo.objects.get(nome='DM Leadership')
        self.assertEqual((g1.edizione_id, g1.attivita_id), (g2b.edizione_id, nuova.id))
        self.assertEqual(g1b.edizione_id, g2.edizione_id)
        self.assertNotEqual(g1.edizione_id, g1b.edizione_id)
        self.assertIsNone(sola.edizione_id)
        self.assertEqual(sola.attivita_id, aula1.id)  # senza abbinamento: resta dov'era
        aula1.refresh_from_db()
        aula2.refresh_from_db()
        self.assertTrue(aula1.is_active)
        self.assertFalse(aula2.is_active)
        self.assertIn('1 partecipazioni parziali', out.getvalue())
        self.assertIn('SENZA ABBINAMENTO', out.getvalue())
        out = StringIO()
        call_command('accorpa_aule', applica=True, stdout=out)  # rilanciato: non tocca nulla
        self.assertIn('già accorpato', out.getvalue())


class UnisciGiornateTest(TestCase):
    def test_unisce_giornate_separate_e_rinomina(self):
        from datetime import date, time
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from participants.models import Iscrizione
        from .models import Evento, Host
        host = Host.objects.create(descrizione='T', posizione='interno')
        refuso = AttivitaCatalogo.objects.create(nome='GWU TM-DM Leadership Proram', tipologia='ld', is_active=False)
        corso = AttivitaCatalogo.objects.create(nome='GWU TM-DM - Leadership', tipologia='ld')
        giorni = [Evento.objects.create(data=date(2025, 3, d), ora_inizio=time(9), ora_fine=time(17),
                                        attivita=refuso, host=host) for d in (11, 12)]
        persona = User.objects.create_user(email='p@x.it', password='x', cognome='P', nome='P')
        for g in giorni:
            Iscrizione.objects.create(evento=g, user=persona, stato='partecipato')
        argomenti = dict(origine=['GWU TM-DM Leadership Proram'], date=['2025-03-11', '2025-03-12'],
                         destinazione='GWU TM-DM - Leadership', rinomina='GWU TM-DM Leadership')

        call_command('unisci_giornate', stdout=StringIO(), **argomenti)
        corso.refresh_from_db()
        self.assertEqual(corso.nome, 'GWU TM-DM - Leadership')  # prova: nulla salvato
        out = StringIO()
        call_command('unisci_giornate', applica=True, stdout=out, **argomenti)
        corso.refresh_from_db()
        for g in giorni:
            g.refresh_from_db()
        self.assertEqual(corso.nome, 'GWU TM-DM Leadership')
        self.assertEqual({g.attivita_id for g in giorni}, {corso.id})
        self.assertEqual(len({g.edizione_id for g in giorni}), 1)
        self.assertIn('1 persone, 0 parziali', out.getvalue())
        # Giornate future divise tra due attività con nomi diversi: diventano un'edizione unica.
        aula1 = AttivitaCatalogo.objects.create(nome='GWU TM-DM - Leadership - Aula 1/2', tipologia='ld')
        aula2 = AttivitaCatalogo.objects.create(nome='GWU TM-DM Leadership Program aula 2/2', tipologia='ld')
        g13 = Evento.objects.create(data=date(2027, 1, 13), ora_inizio=time(9), ora_fine=time(17), attivita=aula1, host=host)
        g14 = Evento.objects.create(data=date(2027, 1, 14), ora_inizio=time(9), ora_fine=time(17), attivita=aula2, host=host)
        out = StringIO()
        call_command('unisci_giornate', origine=[aula1.nome, aula2.nome], date=['2027-01-13', '2027-01-14'],
                     destinazione='GWU TM-DM Leadership', applica=True, stdout=out)
        g13.refresh_from_db()
        g14.refresh_from_db()
        aula1.refresh_from_db()
        aula2.refresh_from_db()
        self.assertEqual((g13.edizione_id, g13.attivita_id, g14.attivita_id), (g14.edizione_id, corso.id, corso.id))
        self.assertFalse(aula1.is_active or aula2.is_active)
        self.assertIn('Disattivate (vuote)', out.getvalue())
        with self.assertRaises(CommandError):  # già unite: non si rifà
            call_command('unisci_giornate', stdout=StringIO(), **{**argomenti, 'origine': ['GWU TM-DM Leadership'],
                                                                   'destinazione': 'GWU TM-DM Leadership',
                                                                   'rinomina': None})


class SpostaEventiTest(TestCase):
    def test_sposta_tutte_le_edizioni_e_disattiva_l_origine(self):
        from datetime import date, time
        from io import StringIO
        from django.core.management import call_command
        from participants.models import Iscrizione
        from .models import Edizione, Evento, Host
        host = Host.objects.create(descrizione='T', posizione='interno')
        dm = AttivitaCatalogo.objects.create(nome='DM Leadership', tipologia='ld')
        tmdm = AttivitaCatalogo.objects.create(nome='GWU TM-DM Leadership', tipologia='ld')
        edizione = Edizione.objects.create()
        giorni = [Evento.objects.create(data=date(2024, 4, d), ora_inizio=time(9), ora_fine=time(17), attivita=dm,
                                        host=host, edizione=edizione) for d in (17, 18)]
        persona = User.objects.create_user(email='p@x.it', password='x', cognome='P', nome='P')
        for g in giorni:
            Iscrizione.objects.create(evento=g, user=persona, stato='partecipato')
        call_command('sposta_eventi', origine='DM Leadership', destinazione='GWU TM-DM Leadership', stdout=StringIO())
        self.assertEqual(dm.eventi.count(), 2)  # prova: nulla salvato
        out = StringIO()
        call_command('sposta_eventi', origine='DM Leadership', destinazione='GWU TM-DM Leadership', applica=True, stdout=out)
        dm.refresh_from_db()
        self.assertEqual((dm.eventi.count(), tmdm.eventi.count(), dm.is_active), (0, 2, False))
        self.assertEqual(set(Evento.objects.values_list('edizione_id', flat=True)), {edizione.id})
        self.assertIn('1 edizioni', out.getvalue())
        self.assertIn('1 persone', out.getvalue())


class FiltroTipologiaDettaglioTest(TestCase):
    def test_dettaglio_filtra_per_tipo_di_attivita(self):
        from datetime import date, time
        from participants.models import Iscrizione
        from .models import Evento, Host
        host = Host.objects.create(descrizione='T', posizione='interno')
        persona = User.objects.create_user(email='p@x.it', password='x', cognome='P', nome='P')
        for nome, tipo in (('Corso', 'ld'), ('Colloquio', 'recruiting')):
            ev = Evento.objects.create(data=date(2026, 1, 10), ora_inizio=time(9), ora_fine=time(10), host=host,
                                       attivita=AttivitaCatalogo.objects.create(nome=nome, tipologia=tipo))
            Iscrizione.objects.create(evento=ev, user=persona, stato='partecipato')
        c = APIClient()
        c.force_authenticate(User.objects.create_user(email='a@x.it', password='x', cognome='A', nome='A', livello_accesso='admin'))
        self.assertEqual([r['attivita_nome'] for r in c.get('/api/report/', {'tipologia': 'recruiting'}).json()], ['Colloquio'])
        self.assertEqual(len(c.get('/api/report/').json()), 2)
        self.assertEqual(c.get('/api/report/excel/', {'tipologia': 'ld'}).status_code, 200)


class CompletaParzialiTest(TestCase):
    def test_i_parziali_di_oggi_diventano_completati(self):
        from datetime import date, time
        from io import StringIO
        from django.core.management import call_command
        from participants.models import Iscrizione
        from .edizioni import PARTECIPATO, esiti_partecipazione
        from .models import Edizione, Evento, Host
        host = Host.objects.create(descrizione='T', posizione='interno')
        att = AttivitaCatalogo.objects.create(nome='GWU TM-DM Leadership', tipologia='ld')
        edizione = Edizione.objects.create()
        g1, g2 = [Evento.objects.create(data=date(2024, 4, d), ora_inizio=time(9), ora_fine=time(17), attivita=att,
                                        host=host, edizione=edizione) for d in (17, 18)]
        assente = User.objects.create_user(email='a@x.it', password='x', cognome='Assente', nome='Un giorno')
        mancante = User.objects.create_user(email='m@x.it', password='x', cognome='Senza', nome='Seconda giornata')
        completo = User.objects.create_user(email='c@x.it', password='x', cognome='Completo', nome='C')
        for u, s1, s2 in ((assente, 'partecipato', 'assente'), (completo, 'partecipato', 'partecipato')):
            Iscrizione.objects.create(evento=g1, user=u, stato=s1)
            Iscrizione.objects.create(evento=g2, user=u, stato=s2)
        Iscrizione.objects.create(evento=g1, user=mancante, stato='partecipato')

        call_command('completa_parziali', stdout=StringIO())
        self.assertEqual(Iscrizione.objects.get(evento=g2, user=assente).stato, 'assente')  # prova
        out = StringIO()
        call_command('completa_parziali', applica=True, stdout=out)
        esiti = esiti_partecipazione(Iscrizione.objects.all())
        self.assertTrue(all(e == PARTECIPATO for e, _ in esiti.values()))
        self.assertIn('2 parziali diventano completati: 1 giornate segnate presenti, 1 giornate aggiunte', out.getvalue())


class AreaSolaVisionePartecipantiTest(TestCase):
    def test_area_vede_gli_iscritti_ma_non_li_modifica(self):
        from datetime import date, time
        from participants.models import Iscrizione
        from .models import Evento, Host
        evento = Evento.objects.create(data=date(2027, 2, 10), ora_inizio=time(9), ora_fine=time(13),
                                       attivita=AttivitaCatalogo.objects.create(nome='Corso', tipologia='ld'),
                                       host=Host.objects.create(descrizione='T', posizione='interno'))
        persona = User.objects.create_user(email='p@x.it', password='x', cognome='P', nome='P')
        altra = User.objects.create_user(email='q@x.it', password='x', cognome='Q', nome='Q')
        iscrizione = Iscrizione.objects.create(evento=evento, user=persona, stato='assente')
        area = APIClient()
        area.force_authenticate(User.objects.create_user(email='ar@x.it', password='x', cognome='A', nome='R',
                                                         livello_accesso='area'))
        self.assertEqual([i['user'] for i in area.get('/api/iscrizioni/', {'evento': evento.id}).json()], [persona.id])
        self.assertEqual(area.post('/api/iscrizioni/', {'evento': evento.id, 'user': altra.id, 'stato': 'iscritto'},
                                   format='json').status_code, 403)
        self.assertEqual(area.patch(f'/api/iscrizioni/{iscrizione.id}/', {'stato': 'partecipato'}, format='json').status_code, 403)
        self.assertEqual(area.delete(f'/api/iscrizioni/{iscrizione.id}/').status_code, 403)
        self.assertEqual(area.delete('/api/iscrizioni/assenti/').status_code, 403)
        iscrizione.refresh_from_db()
        self.assertEqual(iscrizione.stato, 'assente')
        self.assertEqual(Iscrizione.objects.count(), 1)


class DettaglioDisattivatiTest(TestCase):
    def test_dettaglio_separa_attivi_e_disattivati(self):
        from datetime import date, time
        from participants.models import Iscrizione
        from users.views import _compute_stats
        from .models import Evento, Host
        ev = Evento.objects.create(data=date(2026, 1, 10), ora_inizio=time(9), ora_fine=time(13),
                                   attivita=AttivitaCatalogo.objects.create(nome='Corso', tipologia='ld'),
                                   host=Host.objects.create(descrizione='T', posizione='interno'))
        attiva = User.objects.create_user(email='a@y.it', password='x', cognome='Attiva', nome='A')
        spenta = User.objects.create_user(email='s@y.it', password='x', cognome='Spenta', nome='S', is_active=False)
        for u in (attiva, spenta):
            Iscrizione.objects.create(evento=ev, user=u, stato='partecipato')
        admin, ho = APIClient(), APIClient()
        admin.force_authenticate(User.objects.create_user(email='ad@y.it', password='x', cognome='A', nome='D', livello_accesso='admin'))
        ho.force_authenticate(User.objects.create_user(email='ho@y.it', password='x', cognome='H', nome='O', livello_accesso='ho'))
        nomi = lambda c, **p: [r['user_cognome'] for r in c.get('/api/report/', p).json()]
        self.assertEqual(nomi(admin), ['Attiva'])
        self.assertEqual(nomi(admin, disattivati=1), ['Spenta'])
        self.assertEqual(nomi(ho), ['Attiva'])
        self.assertEqual(ho.get('/api/report/', {'disattivati': 1}).status_code, 403)
        self.assertEqual(admin.get('/api/report/excel/', {'disattivati': 1}).status_code, 200)
        _, totale = _compute_stats({})
        self.assertEqual(totale['maschi'] + totale['femmine'], 2)  # le Stats contano anche i disattivati


class CompletaParzialiOpzioniTest(TestCase):
    def test_anche_disattivati_ed_esclusioni(self):
        from datetime import date, time
        from io import StringIO
        from django.core.management import call_command
        from participants.models import Iscrizione
        from .models import Edizione, Evento, Host
        host = Host.objects.create(descrizione='T', posizione='interno')
        att = AttivitaCatalogo.objects.create(nome='Corso', tipologia='ld')
        ed = Edizione.objects.create()
        g1, g2 = [Evento.objects.create(data=date(2024, 4, d), ora_inizio=time(9), ora_fine=time(17), attivita=att,
                                        host=host, edizione=ed) for d in (17, 18)]
        spento = User.objects.create_user(email='s@x.it', password='x', cognome='Spento', nome='S', is_active=False)
        escluso = User.objects.create_user(email='e@x.it', password='x', cognome='Escluso', nome='E', is_active=False)
        for u in (spento, escluso):
            Iscrizione.objects.create(evento=g1, user=u, stato='partecipato')
        out = StringIO()
        call_command('completa_parziali', applica=True, stdout=out)
        self.assertIn('0 parziali', out.getvalue())  # di norma i disattivati non si toccano
        call_command('completa_parziali', applica=True, anche_disattivati=True, escludi=[escluso.id], stdout=StringIO())
        self.assertTrue(Iscrizione.objects.filter(evento=g2, user=spento, stato='partecipato').exists())
        self.assertFalse(Iscrizione.objects.filter(evento=g2, user=escluso).exists())


class FormazioniDiAltriHOTest(TestCase):
    """Un HO modifica e annulla solo le formazioni create da sé; l'Admin tutte."""

    def setUp(self):
        from .models import Host
        self.att = AttivitaCatalogo.objects.create(nome='Customer Service', tipologia='ld')
        self.host = Host.objects.create(descrizione='Trainer', posizione='interno')
        self.clienti = {}
        for chi, livello in (('ho1', 'ho'), ('ho2', 'ho'), ('admin', 'admin')):
            c = APIClient()
            c.force_authenticate(User.objects.create_user(email=f'{chi}@x.it', password='x', cognome=chi.upper(),
                                                          nome='N', livello_accesso=livello))
            self.clienti[chi] = c

    def _crea(self, chi):
        r = self.clienti[chi].post('/api/eventi/', {
            'data': '2027-03-01', 'ora_inizio': '09:00', 'ora_fine': '13:00', 'attivita': self.att.id,
            'host': self.host.id, 'location_esterna': 'Milano'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def _puo(self, chi, pk):
        elenco = self.clienti[chi].get('/api/eventi/', {'data_da': '2027-03-01', 'data_a': '2027-03-01'}).json()
        righe = elenco['results'] if isinstance(elenco, dict) else elenco
        return next(e for e in righe if e['id'] == pk)['puo_modificare']

    def test_solo_chi_ha_creato_o_admin(self):
        from .models import Evento
        pk = self._crea('ho1')
        self.assertEqual((self._puo('ho1', pk), self._puo('ho2', pk), self._puo('admin', pk)), (True, False, True))
        url = f'/api/eventi/{pk}/'
        self.assertEqual(self.clienti['ho2'].patch(url, {'nota': 'x'}, format='json').status_code, 403)
        self.assertEqual(self.clienti['ho2'].delete(url, {'motivazione': 'no'}, format='json').status_code, 403)
        self.assertEqual(self.clienti['ho1'].patch(url, {'nota': 'ok'}, format='json').status_code, 200)
        # Formazione senza autore (es. importata): solo l'Admin.
        Evento.objects.filter(pk=pk).update(created_by=None)
        self.assertEqual(self.clienti['ho1'].delete(url, {'motivazione': 'no'}, format='json').status_code, 403)
        self.assertEqual(self.clienti['admin'].delete(url, {'motivazione': 'annullata'}, format='json').status_code, 204)
