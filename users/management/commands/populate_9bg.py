"""
python manage.py populate_9bg
Popola la 9 Box Grid con i dati del documento "9BG TOTALI.pdf" (anno 2025).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from users.models import NoveBoxGrid, User
from stores.models import Store

ANNO = 2025

# box_number → (performance, potenziale_complessivo)
# perf: col1(non soddisfa)=2, col2(soddisfa)=3, col3(supera)=4
# pot:  row1(basso)=2,        row2(medio)=3,     row3(alto)=4
BOX_MAP = {
    1: (2, 2), 2: (3, 2), 3: (4, 2),
    4: (2, 3), 5: (3, 3), 6: (4, 3),
    7: (2, 4), 8: (3, 4), 9: (4, 4),
}

MOB = {'I': 'nazionale', 'N': 'nord', 'CS': 'centro_sud', '': ''}

# Manual overrides for name mismatches between PDF and DB
# key: (codice_store, pdf_name_lower) → (cognome_fragment, nome_fragment) to search
MANUAL_MAP = {
    ('275', 'domenida labalestra'):  ('Labalestra', 'Domenica'),
    ('281', 'claudia roberta'):      ('Roberto',    'Claudia'),
    ('275', 'christian valente'):    ('Valente',    'Cristian'),
    ('274', 'mariavittoria chessari'): ('Chessari', 'Maria Vittoria'),
    ('275', 'muhammed raees'):       ('Raees',      'Muhammad'),
    ('275', 'nayei ttito'):          ('ttito',      'Nayeli'),
    ('275', 'davida marano'):        ('Marano',     'Davide'),
    ('280', 'valentina d urso'):     ('D Urso',     'Cristiana'),
    ('278', 'nicole liberi'):        ('Liberi',     'Nicol'),
    ('272', 'cerasella popa'):       ('Cerassella', 'Popa'),
    ('278', 'matteo salazar'):       ('salazar',    'Matteo'),
}

# Tuples: (codice_store, name_in_pdf, box, mob_code, motivato, nuovo, gwu, vm)
# name_in_pdf format: "Nome Cognome" as shown in PDF

SM = [
    # ── STORE MANAGER ─────────────────────────────────────────────
    ('273', 'Giuseppe Tutone',      8, 'I',  True,  False, False, False),
    ('272', 'Jessica Marconi',      4, '',   None,  False, False, False),
    ('274', 'Federico Frezza',      4, 'N',  None,  False, False, False),
    ('275', 'Stefano Cerasaro',     4, 'I',  True,  False, False, False),
    ('276', 'Gaetano Orto',         4, '',   None,  False, False, False),
    ('278', 'Giovanni Di Dio',      4, 'I',  True,  False, False, False),
    ('279', 'Raffaele De Piano',    4, 'N',  True,  False, False, False),
    ('280', 'Michela Petrosino',    4, 'N',  None,  False, False, False),
    ('281', 'Matteo Fattori',       4, 'N',  True,  False, False, False),
    ('282', 'Mimmo Sgura',          4, 'I',  True,  False, False, False),
    ('283', 'Vincenzo Gulino',      4, 'I',  True,  False, False, False),
    ('284', 'Giorgia Vitelli',      4, 'I',  True,  False, False, False),
    ('285', 'Fabrizio Criscuolo',   4, '',   None,  False, False, False),
    ('286', 'Alfonso De Feo',       5, 'I',  True,  False, False, False),
    ('287', 'Domenico Liuni',       5, 'N',  True,  False, False, False),
    ('288', 'Beatrice Silmo',       5, '',   None,  False, False, False),
    ('291', 'Francesca Baronti',    5, 'I',  True,  False, False, False),
    ('271', 'Massimiliano Squeo',   6, 'I',  True,  False, False, False),
    ('270', 'Cesare Sorrentino',    6, 'I',  True,  False, False, False),
    ('277', 'Roberto Marchese',     6, 'I',  True,  False, False, False),
]

AM = [
    # ── ASSISTANT MANAGER ─────────────────────────────────────────
    # Box 7
    ('271', 'Diego Marchese',       7, 'CS', True,  False, False, False),
    ('277', 'Simonpietro Sgarbini', 7, 'N',  True,  True,  False, False),
    ('279', 'Valentina Alaimo',     7, 'N',  True,  True,  False, False),
    ('280', 'Alex El Sayed',        7, 'CS', True,  False, False, False),
    ('281', 'Gaetano Lo Verde',     7, 'I',  True,  False, False, False),
    ('284', 'Giuseppina Ianniello', 7, 'CS', True,  False, False, False),
    ('286', 'Andrei Chidesa',       7, 'CS', True,  False, False, False),
    # Box 8
    ('270', 'Mauro Ungaro',         8, 'N',  True,  False, False, False),
    ('272', 'Valentina Leder',      8, 'N',  True,  False, False, False),
    ('274', 'Sabrina Leandri',      8, 'N',  True,  True,  False, False),
    ('275', 'Michele Insalata',     8, 'N',  True,  False, False, False),
    ('275', 'Armando Gorilla',      8, '',   None,  False, False, False),
    ('278', 'Valentina Giammona',   8, 'N',  True,  False, False, False),
    # Box 9
    ('282', 'Daiana Campus',        9, 'CS', True,  False, True,  False),
    # Box 4
    ('273', 'Laura Franzoglio',     6, '',   None,  False, False, False),
    ('276', 'Tiziana Papalia',      6, 'N',  True,  False, False, False),
    ('283', 'Patrizia Pinca',       6, '',   None,  False, False, False),
    ('285', 'Xheksona Sinani',      6, 'N',  True,  True,  False, False),
    # Box 2
    ('271', 'Jane Marjory Kinsler', 2, '',   False, False, False, False),
    ('274', 'Antonio Gioia',        2, '',   False, False, False, False),
    ('291', 'Margherita Fenaroli',  2, 'I',  False, True,  False, False),
]

DM = [
    # ── DEPARTMENT MANAGER ────────────────────────────────────────
    # Box 7
    ('270', 'Ina Jaupi',            7, 'N',  True,  False, False, False),
    ('276', 'Denis Ferramosca',     7, 'I',  True,  False, False, False),
    ('278', 'Daniela Lacagnina',    7, 'I',  True,  True,  False, False),
    ('273', 'Silvia Cattaneo',      7, 'N',  True,  False, False, False),
    # Box 8
    ('270', 'Andrea Tarsi',         8, 'I',  True,  False, False, False),
    ('270', 'Sara Cecere',          8, 'I',  True,  False, False, False),
    ('270', 'Samuele Madonna',      8, 'N',  True,  False, False, False),
    ('270', 'Davide Truglio',       8, 'I',  True,  False, False, False),
    ('271', 'Martina Carvelli',     8, 'I',  True,  False, False, False),
    ('271', 'Beatrice Peli',        8, 'I',  True,  False, False, False),
    ('271', 'Benedetta Gemmo',      8, 'N',  True,  False, False, False),
    ('275', 'Micaela Del Vecchio',  8, 'N',  True,  False, False, False),
    ('275', 'Fatima El Ouazi',      8, 'N',  True,  True,  False, False),
    ('275', 'Alessia Simone',       8, 'I',  True,  False, False, False),
    ('276', 'Simon H Ntah',         8, 'N',  True,  False, False, False),
    ('276', 'Bruscar Towa',         8, 'N',  True,  False, False, False),
    ('277', 'Aurora Graziano',      8, 'CS', True,  False, False, False),
    ('277', 'Ludovica Vitaggio',    8, 'CS', True,  False, False, True),  # VM
    ('279', 'Ilaria Colangelo',     8, 'N',  True,  False, False, False),
    ('280', 'Laura Mattioli',       8, 'I',  True,  True,  False, False),
    ('281', 'Claudia Roberta',      8, 'N',  True,  False, False, False),
    ('282', 'Marialetizia Pagliaminuta', 8, 'I', True, True, False, False),
    ('282', 'Luca Giacobbe',        8, 'I',  True,  False, False, False),
    ('284', 'Daniele Gallo',        8, 'I',  True,  False, False, False),
    ('286', 'Monica Proietti',      8, 'CS', True,  False, False, False),
    ('291', 'Giulia Natacci',       8, 'N',  True,  False, False, False),
    # Box 9
    ('270', 'Paola Spallanzani',    9, 'I',  True,  False, False, False),
    ('273', 'Sara Geremia',         9, 'N',  True,  False, False, False),
    ('275', 'Gaia Galvano',         9, 'CS', True,  False, False, False),
    # Box 4
    ('272', 'Luisa Grassi',         4, 'I',  True,  False, False, False),
    ('273', 'Samantha Melegraro',   4, '',   None,  False, False, False),
    ('278', 'Thomas Serio',         4, '',   None,  False, False, False),
    ('270', 'Vania Bar Tarus',      4, '',   False, False, False, False),
    ('270', 'Ioana Chis',           4, '',   False, False, False, False),
    ('270', 'Fabiola Martone',      4, '',   False, False, False, False),
    ('271', 'Alessandra D Alema',   4, 'I',  True,  False, False, False),
    ('271', 'Celine Scalvini',      4, 'N',  True,  False, False, False),
    ('272', 'Giovanna Manzi',       4, 'N',  True,  False, False, False),
    ('272', 'Davide Spina',         4, '',   None,  False, False, False),
    ('272', 'Gianandrea Serra',     4, '',   None,  False, False, False),
    ('272', 'Stephanie Luijsterburg', 4, '', None,  False, False, False),
    ('273', 'Andrea Musumarra',     4, '',   None,  False, False, False),
    ('273', 'Ambra Mini',           4, '',   None,  False, False, False),
    ('274', 'Roberta Tomaso',       4, 'CS', True,  False, False, False),
    ('274', 'Giulia Mariolu',       4, '',   None,  False, False, False),
    ('274', 'Valeria Paesano',      4, '',   None,  False, False, False),
    ('274', 'Siria Finocchiaro',    4, '',   None,  False, False, False),
    # Box 5
    ('275', 'Domenida Labalestra',  5, 'N',  True,  True,  False, False),
    ('274', 'Giovanna Murgolo',     5, '',   None,  False, False, False),
    ('275', 'Antonio Lanna',        5, 'N',  True,  True,  False, False),
    ('275', 'Francesca Boi',        5, '',   None,  False, False, False),
    ('276', 'Nunzia Loquace',       5, 'I',  True,  False, False, False),
    ('276', 'Favjol Shehu',         5, '',   None,  False, False, False),
    ('277', 'Monia Graceffa',       5, 'CS', True,  False, False, False),
    ('277', 'Dario Valenzano',      5, 'CS', True,  False, False, False),
    ('277', 'Erica Brunetti',       5, '',   None,  False, False, False),
    ('278', 'Ilaria Fabbri',        5, 'N',  True,  False, False, False),
    ('279', 'Martina Gasparini',    5, 'N',  True,  True,  False, False),
    ('279', 'Giulia Ventura',       5, '',   None,  False, False, False),
    ('280', 'Gabriel Toso',         5, 'CS', True,  False, False, False),
    ('280', 'Domiziana Moretti',    5, '',   None,  False, False, False),
    ('280', 'Stefania Trancuccio',  5, '',   None,  False, False, False),
    ('281', 'Matteo Mura',          5, 'N',  True,  False, False, False),
    ('281', 'Jessica Viscusi',      5, 'CS', True,  False, False, False),
    ('281', 'Leonardo Giugliano',   5, 'I',  True,  False, False, False),
    ('282', 'Luca Platania',        5, 'I',  True,  False, False, False),
    ('282', 'Salvatore Pedone',     5, '',   None,  False, False, False),
    ('283', 'Giordano Chicarella',  5, 'CS', True,  True,  False, False),
    ('284', 'Martina Trifiro',      5, 'I',  True,  False, False, False),
    ('285', 'Diana Iordache',       5, '',   None,  False, False, False),
    ('285', 'Antonio De Benedetto', 5, 'CS', True,  False, False, False),
    ('286', 'Luisa Cesario',        5, 'CS', True,  False, False, False),
    ('287', 'Luana Benevento',      5, 'N',  True,  False, False, False),
    ('287', 'Roberto Romano',       5, '',   None,  False, False, False),
    ('288', 'Martina Barluzzi',     5, '',   None,  False, False, False),
    ('288', 'Carmine Bervicato',    5, '',   None,  False, False, False),
    # Box 6
    ('270', 'Erica Colamartino',    6, 'N',  True,  False, False, False),
    ('270', 'Monia D Errico',       6, 'I',  True,  False, False, False),
    ('275', 'Nicole Tintori',       6, 'CS', True,  False, False, False),
    ('275', 'Ilaria Ferramosca',    6, 'CS', True,  False, False, False),
    ('275', 'Domenico Ventriglia',  6, 'CS', True,  False, False, False),
    ('276', 'Francesca Novello',    6, 'I',  True,  False, False, False),
    ('280', 'Valentina La Puma',    6, 'N',  True,  False, False, False),
    ('281', 'Danilo Sicilia',       6, 'N',  True,  False, False, False),
    ('284', 'Salvatore Scarpaci',   6, 'CS', True,  True,  False, False),
    ('288', 'Jona Bacja',           6, 'CS', True,  False, False, False),
    # Box 1
    ('270', 'Michele Barcellona',   1, '',   False, False, False, False),
    ('271', 'Antonino Fusto',       1, '',   False, False, False, False),
    ('274', 'Kaoutar Bouidra',      1, '',   False, False, False, False),
    ('274', 'Barbara Sivieri',      1, '',   False, False, False, False),
    ('278', 'Tania Russo',          1, '',   False, False, False, False),
    ('282', 'Alberto Foti',         1, '',   False, False, False, False),
    ('284', 'Elisa Bonafe',         1, '',   False, False, False, False),
    ('286', 'Vito Ceglie',          1, 'CS', False, False, False, False),
    ('291', 'Filippo Giovanni Carrolo', 1, 'N', False, False, False, False),
]

TM = [
    # ── TEAM MANAGER ──────────────────────────────────────────────
    # Box 7
    ('270', 'Martina Fava',          7, 'CS', True,  False, False, False),
    ('271', 'Silvana Dessi',         7, 'CS', True,  False, False, False),
    ('272', 'Wissal Titi',           7, 'N',  True,  False, False, False),
    ('272', 'Matteo Brandimarte',    7, 'N',  True,  False, True,  False),  # GWU
    ('273', 'Carmine Volpe',         7, 'CS', True,  False, False, False),
    ('273', 'Angelica Palmisano',    7, 'N',  True,  False, False, False),
    ('274', 'Letizia Bianchi',       7, 'I',  True,  False, False, False),
    ('274', 'Yuri Olia',             7, 'CS', True,  False, False, False),
    ('274', 'Asya De Santis',        7, 'CS', True,  False, False, False),
    ('275', 'Christian Valente',     7, 'CS', True,  False, False, False),
    ('275', 'Federico Boscolo Bisto',7, 'N',  True,  False, False, False),
    ('276', 'Aurora Nourhen Zuin',   7, 'N',  True,  False, False, False),
    ('276', 'Marta Damiani',         7, 'I',  True,  False, False, False),
    ('276', 'Greta Silistrini',      7, 'I',  True,  False, False, False),
    # Box 8
    ('271', 'Simona Skendaj',        8, 'N',  True,  False, False, False),
    ('273', 'Christian Puggioli',    8, 'N',  True,  False, False, False),
    ('273', 'Leandro Iorio',         8, 'N',  True,  False, False, False),
    ('273', 'Iolanda Mignosi',       8, '',   None,  False, False, False),
    ('273', 'Arianna Briglia',       8, '',   None,  True,  False, False),
    ('273', 'Nicole Adilardi',       8, '',   None,  True,  False, False),
    ('274', 'Federica Di Martino',   8, 'CS', True,  False, False, False),
    ('274', 'Mariavittoria Chessari',8, 'N',  True,  False, False, False),
    ('274', 'Chiara D Angelo',       8, 'CS', True,  False, False, False),
    ('274', 'Giulia Gallisai',       8, 'CS', True,  False, False, False),
    ('274', 'Salvatore Buzzone',     8, 'CS', True,  False, False, False),
    ('274', 'Davide Bernardo',       8, 'CS', True,  False, False, False),
    ('274', 'Francesco Allocca',     8, 'CS', True,  False, False, False),
    ('274', 'Camilla Mozzone',       8, 'CS', True,  True,  False, False),
    ('274', 'Alessio Cafa',          8, 'CS', True,  True,  False, False),
    ('274', 'Christian Varriale',    8, 'CS', True,  True,  False, False),
    ('275', 'Giuseppe Taormina',     8, 'N',  True,  False, False, False),
    ('275', 'Martina Zanoni',        8, 'N',  True,  False, False, False),
    ('275', 'Alessandro Di Leo',     8, 'N',  True,  True,  False, False),
    ('275', 'Massimiliano Rosata',   8, 'N',  True,  True,  False, False),
    ('275', 'Marika Russo',          8, 'CS', True,  True,  False, False),
    ('275', 'Muhammed Raees',        8, 'N',  True,  False, False, False),
    ('275', 'Giovanni Bologna',      8, 'N',  True,  False, False, False),
    ('275', 'Nayei Ttito',           8, 'N',  True,  False, False, False),
    ('275', 'Matteo Piccolo',        8, 'N',  True,  True,  False, False),
    ('275', 'Azzurra Vindemmio',     8, 'N',  True,  True,  False, False),
    ('275', 'Davida Marano',         8, 'N',  True,  False, False, False),
    ('275', 'Omar Baktoui',          8, 'N',  True,  False, False, False),
    ('275', 'Neliie Katia Akakpo',   8, 'N',  True,  False, False, False),
    ('275', 'Assunta Albano',        8, 'N',  True,  False, False, False),
    ('276', 'Zineb El Mansouri',     8, 'N',  True,  False, False, False),
    ('276', 'Anna Torrisi',          8, 'I',  True,  False, False, False),
    ('276', 'Leonardo Marini',       8, '',   None,  False, False, False),
    ('276', 'Grazia Luciana Vittorio',8,'',   None,  False, False, False),
    ('276', 'Giorgia Spagone',       8, '',   None,  False, False, False),
    ('276', 'Andrea Ventura',        8, '',   None,  True,  False, False),
    ('276', 'Erika Cesti',           8, '',   None,  True,  False, False),
    ('277', 'Claudia F Desimini',    8, 'CS', True,  False, False, False),
    ('277', 'Rodolfo Marca',         8, 'N',  True,  False, False, False),
    ('277', 'Aurora Fortunato',      8, '',   None,  False, False, False),
    ('277', 'Andrea Solfato',        8, 'CS', True,  False, False, False),
    ('277', 'Marta Mallardi',        8, 'CS', True,  False, False, False),
    ('277', 'Sara Vattaneo',         8, 'CS', True,  True,  False, False),
    ('277', 'Claudia Vassallo',      8, 'CS', True,  False, False, False),
    ('277', 'Giuseppe Stamigni',     8, 'CS', True,  True,  False, False),
    ('277', 'Luca Gallo',            8, 'I',  True,  True,  False, False),
    ('277', 'Antonino Mele',         8, 'I',  True,  True,  False, False),
    ('278', 'Maximiliano De Napoli', 8, 'N',  True,  False, False, False),
    ('278', 'Luciana Palma',         8, 'I',  True,  False, False, False),
    ('278', 'Fabiana Salerno',       8, 'I',  True,  True,  False, False),
    ('278', 'Alessia Vela',          8, 'N',  True,  False, False, False),
    ('278', 'Michael Ciaccia',       8, '',   None,  True,  False, False),
    ('279', 'Alessia Asencios',      8, 'N',  True,  False, False, False),
    ('279', 'Jasmine Mandato',       8, 'CS', True,  True,  False, False),
    ('279', 'Chiara Ventorino',      8, '',   None,  False, False, False),
    ('279', 'Martina Evangelista',   8, 'CS', True,  True,  False, False),
    ('279', 'Chaima Romdhani',       8, 'N',  True,  False, False, False),
    ('279', 'Silvia Megali Salmeron',8, 'N',  True,  True,  False, False),
    ('279', 'Francesco Mimmo',       8, 'N',  True,  False, False, False),
    ('280', 'Giorgia Strano',        8, '',   None,  False, False, False),
    ('280', 'Alessandro Mameli',     8, 'N',  True,  False, False, False),
    ('280', 'Cosma Di Ponzio',       8, 'I',  True,  False, False, False),
    ('280', 'Francesco Di Giacomo',  8, 'CS', True,  False, False, False),
    ('280', 'Fabiana Caldarulo',     8, 'CS', True,  False, False, False),
    ('280', 'Giada Casu',            8, 'CS', True,  False, False, False),
    ('280', 'Alessandro Massa',      8, 'CS', True,  True,  False, False),
    ('280', 'Ilaria Martina',        8, 'CS', True,  True,  False, False),
    ('280', 'Valentina D Urso',      8, 'CS', True,  False, False, False),
    ('281', 'Fabio Scotti',          8, '',   None,  False, False, False),
    ('281', 'Michele Spadaro',       8, '',   None,  False, False, False),
    ('281', 'Luca Giovanni Manieri', 8, 'N',  True,  False, False, False),
    ('281', 'Felice Nasta',          8, 'CS', True,  False, False, False),
    ('281', 'Carlotta Di Domenico',  8, 'CS', True,  False, False, False),
    ('281', 'Giorgia Croci',         8, 'N',  True,  False, False, False),
    ('281', 'Valentina Vasco',       8, 'CS', True,  False, False, False),
    ('282', 'Joel Ases Ruiz',        8, '',   None,  False, False, False),
    ('282', 'Luca Karim Ktir',       8, '',   None,  False, False, False),
    ('282', 'Noemi Caputo',          8, '',   None,  False, False, False),
    ('282', 'Ilaria Secondiani',     8, 'CS', True,  False, False, False),
    ('282', 'Gabriele Fortino',      8, 'I',  True,  False, False, False),
    ('282', 'Giorgia Di Stefano',    8, 'CS', True,  False, False, False),
    ('283', 'Cristina Nicotra',      8, 'N',  True,  False, False, False),
    ('283', 'Vanessa Riviello',      8, 'CS', True,  False, False, False),
    ('283', 'Fabiola Pistillo',      8, 'CS', True,  False, False, False),
    ('284', 'Martina Catania',       8, 'CS', True,  False, False, False),
    ('284', 'Roberta Risa',          8, 'CS', True,  False, False, False),
    ('284', 'Valeria Camassa',       8, 'CS', True,  False, False, False),
    ('285', 'Claudia Piano',         8, 'N',  True,  False, False, False),
    ('286', 'Leonardo Cignitti',     8, 'CS', True,  False, False, False),
    # Box 9
    ('275', 'Oriana Altobelli',      9, 'I',  True,  False, False, False),
    ('287', 'Alfonso Vittore',       9, 'CS', True,  False, False, False),
    ('287', 'Caterina Moretti',      9, 'I',  True,  False, False, False),
    ('288', 'Lorenza Confermo',      9, 'CS', True,  False, False, False),
    ('288', 'Fiorenza Capaccio',     9, 'CS', True,  False, False, False),
    ('288', 'Francesca Sarnelli',    9, 'I',  True,  False, False, False),
    ('291', 'Rachele Zedde',         9, 'N',  True,  False, False, False),
    # Box 4
    ('270', 'Alexandra Spiridon',    4, '',   None,  False, False, False),
    ('271', 'Jessica Pucci',         4, 'CS', None,  False, False, False),
    ('271', 'Federica Falchi',       4, '',   None,  False, False, False),
    ('272', 'Jacopo Michelucci',     4, '',   None,  False, False, False),
    ('273', 'Danny Castellano',      4, '',   None,  False, False, False),
    ('273', 'Orazio Rovere',         4, 'N',  None,  False, False, False),
    ('275', 'Tommaso Marchiori',     4, 'N',  None,  False, False, False),
    ('276', 'Terence Clark',         4, '',   None,  False, False, False),
    ('278', 'Vanessa Cazzetta',      4, '',   None,  False, False, False),
    ('278', 'Nicole Liberi',         4, '',   None,  True,  False, False),
    ('278', 'Elia Hoxha',            4, '',   None,  False, False, False),
    # Box 5
    ('270', 'Lorenzo Mitta',         5, 'N',  None,  False, False, False),
    ('270', 'Alice Fabris',          5, 'N',  None,  False, False, False),
    ('270', 'Greta Lopes',           5, '',   None,  False, False, False),
    ('270', 'Martina Casalino',      5, 'I',  None,  False, False, False),
    ('270', 'Mario Agustin Garcia',  5, 'I',  None,  False, False, False),
    ('270', 'Eleonora Boscolo',      5, '',   None,  False, False, False),
    ('270', 'Adele Fontana',         5, 'N',  None,  False, False, False),
    ('271', 'Roberta Balena',        5, 'N',  None,  False, False, False),
    ('271', 'Antonio Spezzano',      5, 'CS', None,  False, False, False),
    ('271', 'Elena Tofan',           5, 'CS', None,  False, False, False),
    ('271', 'Michele Santonati',     5, 'CS', None,  False, False, False),
    ('271', 'Federico Farina',       5, 'I',  None,  False, False, False),
    ('271', 'Giuseppe Massimo',      5, 'CS', None,  False, False, False),
    ('271', 'Andrea Belvedere',      5, 'CS', None,  False, False, False),
    ('271', 'Martina De Lucia',      5, 'I',  None,  False, False, False),
    ('271', 'Giuseppe Banco',        5, 'I',  None,  False, False, False),
    ('271', 'Edoardo Cinquegrano',   5, 'CS', None,  False, False, False),
    ('272', 'Cerasella Popa',        5, 'N',  None,  False, False, False),
    ('272', 'Zaina Zaman',           5, 'N',  None,  False, False, False),
    ('272', 'Gianella Mendez',       5, 'N',  None,  False, False, False),
    ('272', 'Ilaria Cocciolo',       5, 'N',  None,  False, False, False),
    ('272', 'Agata Putrino',         5, 'N',  None,  False, False, False),
    ('272', 'Daniele De Nisi',       5, 'N',  None,  True,  False, False),
    ('273', 'Martina Tatti',         5, 'N',  None,  False, False, False),
    ('273', 'Jalila Fikri',          5, 'N',  None,  False, False, False),
    ('277', 'Eleonora Cinquegrana',  5, '',   None,  False, False, False),
    ('277', 'Giuseppe Seguenzia',    5, 'CS', None,  False, False, False),
    ('277', 'Ioana Gravil',          5, 'CS', None,  True,  False, False),
    ('277', 'Emmanuela Abbate',      5, 'CS', None,  False, False, False),
    ('277', 'Giuseppe Maisano',      5, 'CS', None,  True,  False, False),
    ('278', 'Matteo Salazar',        5, 'N',  None,  False, False, False),
    ('278', 'Cristina Malosti',      5, '',   None,  False, False, False),
    ('278', 'Valentina Pizzetti',    5, 'N',  None,  False, False, False),
    ('278', 'Luigi Rusciano',        5, '',   None,  True,  False, False),
    ('278', 'Mario Marchetti',       5, 'CS', None,  False, False, False),
    ('279', 'Vincenza Maiello',      5, '',   None,  False, False, False),
    ('279', 'Emanuela Lanzone',      5, '',   None,  False, False, False),
    # Box 6
    ('270', 'Cristian Romei',        6, 'CS', True,  False, False, False),
    ('270', 'Marta Lorusso',         6, '',   None,  False, False, False),
    ('275', 'Francesca Ranalli',     6, 'CS', True,  False, False, False),
    ('276', 'Rosanna Argiento',      6, 'N',  True,  False, False, False),
    ('276', 'Luiza Mariana Gales',   6, 'I',  True,  False, False, False),
    ('277', 'Pietro Impala',         6, '',   None,  False, False, False),
    ('278', 'Federica Migliorini',   6, 'N',  True,  False, False, False),
    ('280', 'Rita Squeo',            6, 'CS', True,  False, False, False),
    ('285', 'Morena De Maria',       6, 'CS', True,  False, False, False),
    ('288', 'Alison Pistorio',       6, 'N',  True,  False, False, False),
    # Box 1
    ('270', 'Sara Allegritti',       1, '',   None,  False, False, False),
    ('270', 'Martina Oliarca',       1, '',   None,  False, False, False),
    ('270', 'Gloria Candido',        1, '',   None,  False, False, False),
    ('271', 'Alina Georgiana Papuc', 1, 'N',  None,  False, False, False),
    ('271', 'Mirko Onia',            1, 'N',  None,  False, False, False),
    ('271', 'Salvatore Caruana',     1, 'CS', None,  False, False, False),
    ('272', 'Clara Panto',           1, 'N',  None,  False, False, False),
    ('273', 'Corina Trandafir',      1, '',   None,  False, False, False),
    ('274', 'Rossella Manselli',     1, '',   None,  False, False, False),
    ('276', 'Dimitri Roberto Demartis',1,'',  None,  False, False, False),
    ('276', 'Melissa Stevanato',     1, '',   None,  False, False, False),
    ('277', 'Alessandra Bischetti',  1, '',   None,  False, False, False),
    ('277', 'Selene Ludovici',       1, '',   None,  False, False, False),
    ('270', 'Vanessa Cappone',       1, '',   None,  False, False, False),
    ('291', 'Giulia Manna',          1, 'N',  None,  False, False, False),
    # Box 2
    ('277', 'Mattia Panebianco',     2, 'CS', False, False, False, False),
    ('277', 'Federica Divano',       2, 'CS', False, False, False, False),
    ('277', 'Luca Bianchini',        2, 'N',  False, False, False, False),
    ('278', 'Elizabet Lino',         2, 'N',  None,  False, False, False),
    ('279', 'Alessandro Esposito',   2, 'CS', None,  False, False, False),
    ('279', 'Emanuele Fiorina',      2, '',   None,  False, False, False),
    ('280', 'Martina Degrati',       2, 'CS', None,  False, False, False),
    ('280', 'Carlotta Zinna',        2, '',   None,  False, False, False),
    ('281', 'Annalisa Ianni',        2, 'N',  None,  False, False, False),
    ('281', 'Sara Zaffaroni',        2, 'I',  None,  False, False, False),
    ('279', 'Salvatore Emanuele',    2, '',   None,  False, False, False),
    ('279', 'Frederic Testi',        2, '',   None,  False, False, False),
    ('279', 'Melania Palladino',     2, '',   None,  False, False, False),
    ('280', 'Alessio Tatone',        2, 'CS', None,  False, False, False),
    ('280', 'Elisa Crivellari',      2, '',   None,  False, False, False),
    ('280', 'Antonella Paudice',     2, '',   None,  False, False, False),
    ('281', 'Nicole Severgnini',     2, '',   None,  False, False, False),
    ('281', 'Martina Palumbo',       2, 'N',  None,  True,  False, False),
    ('281', 'Alexandra Frattila',    2, '',   None,  False, False, False),
    ('282', 'Diletta Manini',        2, '',   None,  False, False, False),
    ('282', 'Grazia Lapenna',        2, 'I',  None,  False, False, False),
    ('283', 'Filippa D Angelo',      2, '',   None,  False, False, False),
    ('282', 'Daniela Antonacci',     2, 'CS', None,  False, False, False),
    ('282', 'Alessio Santanelli',    2, 'CS', None,  False, False, False),
    ('282', 'Michele Massarelli',    2, 'CS', None,  False, False, False),
    ('282', 'Pasquale Paradiso',     2, 'CS', None,  False, False, False),
    ('282', 'Giosue Musella',        2, '',   None,  False, False, False),
    ('282', 'Marco Troiano',         2, '',   None,  False, False, False),
    ('282', 'Cristina De Nicolo',    2, '',   None,  False, False, False),
    ('282', 'Francesco Loria',       2, '',   None,  False, False, False),
    ('283', 'Alicia Ianiri',         2, 'CS', None,  False, False, False),
    ('283', 'Anais Tello',           2, 'N',  None,  False, False, False),
    ('283', 'Simona Crispino',       2, '',   None,  False, False, False),
    ('283', 'Alfredo Montuori',      2, '',   None,  False, False, False),
    ('283', 'Paola Sinatra',         2, '',   None,  False, False, False),
    ('284', 'Abdellah Bellami',      2, '',   None,  False, False, False),
    ('284', 'Maria Vittoria Romanelli',2,'',  None,  False, False, False),
    ('284', 'Cristian Cupani',       2, '',   None,  False, False, False),
    ('284', 'Silvia Serra',          2, '',   None,  False, False, False),
    ('284', 'Cosimo Toriello',       2, '',   None,  False, False, False),
    ('284', 'Teresa Carbone',        2, '',   None,  False, False, False),
    ('284', 'Danilo Memoli',         2, '',   None,  False, False, False),
    ('284', 'Larisa Cimbrica',       2, 'N',  None,  False, False, False),
    ('283', 'Francesca Bernini',     2, '',   None,  False, False, False),
    ('283', 'Martina Severini',      2, 'CS', None,  False, False, False),
    ('284', 'Alberto Rapisarda',     2, '',   None,  False, False, False),
    ('285', 'Alice Rosito',          2, 'N',  None,  False, False, False),
    ('286', 'Alfredo Kupper',        2, 'CS', None,  False, False, False),
    ('286', 'Faysal Lalali',         2, 'N',  None,  False, False, False),
    ('291', 'Nicolo Bragantini',     2, 'N',  None,  False, False, False),
    ('291', 'Alessia Veneroni',      2, 'N',  None,  False, False, False),
    ('291', 'Simona Abd El Malek',   2, 'N',  None,  False, False, False),
    ('291', 'Davide Modugno',        2, 'N',  None,  False, False, False),
    ('291', 'Iara Galo',             2, 'I',  None,  False, False, False),
    # Box 3
    ('272', 'Oumaima Qartit',        3, '',   None,  False, False, False),
    ('273', 'Stanislav Radev',       3, '',   None,  False, False, False),
    ('275', 'Rachele Fragomeni',     3, 'N',  None,  True,  False, False),
    ('274', 'Michela Scannella',     3, '',   None,  False, False, False),
    ('276', 'Mirko Santia',          3, '',   None,  False, False, False),
    ('277', 'Francesco Fiorino',     3, '',   None,  False, False, False),
    ('278', 'Noemi Porro',           3, '',   None,  False, False, False),
    ('280', 'Ines Moreno Vinci',     3, 'CS', None,  False, False, False),
    ('280', 'Michele Buonamico',     3, 'I',  None,  False, False, False),
    ('291', 'Manjola Margjegjaj',    3, 'N',  None,  False, False, False),
]

ALL_DATA = [
    ('Store Manager',    SM),
    ('Assistant Manager', AM),
    ('Department Manager', DM),
    ('Team Manager',     TM),
]


class Command(BaseCommand):
    help = 'Popola la 9 Box Grid dal documento 9BG TOTALI.pdf (anno 2025)'

    def find_user(self, codice_store, name):
        store = Store.objects.filter(codice_store=codice_store).first()
        if not store:
            return None, f'store {codice_store} non trovato'

        parts = name.strip().split()
        if len(parts) < 2:
            return None, f'nome troppo corto: {name}'

        qs = User.objects.filter(store=store, is_active=True)

        # Check manual override map first
        key = (codice_store, name.lower())
        if key in MANUAL_MAP:
            cogn_frag, nome_frag = MANUAL_MAP[key]
            u = qs.filter(cognome__icontains=cogn_frag, nome__icontains=nome_frag).first()
            if u:
                return u, None

        # Try exact matches in all split permutations
        # PDF format is typically "Nome Cognome"
        # DB format: cognome field + nome field
        for split_at in range(1, len(parts)):
            nome_try = ' '.join(parts[:split_at])
            cogn_try = ' '.join(parts[split_at:])
            # try: PDF = "Nome Cognome" → DB cognome=cogn_try, nome=nome_try
            u = qs.filter(cognome__iexact=cogn_try, nome__iexact=nome_try).first()
            if u:
                return u, None
            # try: PDF = "Cognome Nome" → DB cognome=nome_try, nome=cogn_try
            u = qs.filter(cognome__iexact=nome_try, nome__iexact=cogn_try).first()
            if u:
                return u, None

        # Fallback: any single part match (unique)
        for part in parts:
            if len(part) < 3:
                continue
            # icontains on cognome
            hits = qs.filter(cognome__icontains=part)
            if hits.count() == 1:
                u = hits.first()
                # verify at least one other part matches nome
                remaining = [p for p in parts if p.lower() != part.lower()]
                if not remaining or any(r.lower() in u.nome.lower() for r in remaining):
                    return u, None
            # icontains on nome
            hits = qs.filter(nome__icontains=part)
            if hits.count() == 1:
                u = hits.first()
                remaining = [p for p in parts if p.lower() != part.lower()]
                if not remaining or any(r.lower() in u.cognome.lower() for r in remaining):
                    return u, None

        return None, f'nessun match per "{name}" in store {codice_store}'

    def handle(self, *args, **options):
        now = timezone.now()
        created_count = 0
        updated_count = 0
        not_found = []

        for role_name, entries in ALL_DATA:
            self.stdout.write(f'\n--- {role_name} ({len(entries)} entries) ---')
            seen_users = set()

            for (codice, name, box, mob_code, motivato, nuovo, gwu, vm) in entries:
                user, err = self.find_user(str(codice), name)
                if not user:
                    not_found.append(f'{codice} {name} [{role_name}]: {err}')
                    continue

                # Skip duplicates within same role run
                if user.id in seen_users:
                    continue
                seen_users.add(user.id)

                perf, pot = BOX_MAP[box]

                obj, created = NoveBoxGrid.objects.update_or_create(
                    user=user,
                    anno=ANNO,
                    defaults={
                        'store': user.store,
                        'performance': perf,
                        'gestione_se': pot,
                        'capacita_strategica': pot,
                        'agilita_relazionale': pot,
                        'aspirazione_professionale': pot,
                        'potenziale_complessivo': pot,
                        'motivazione': motivato,
                        'mobilita': MOB.get(mob_code, ''),
                        'nuovo_in_ruolo': nuovo,
                        'is_gwu': gwu,
                        'is_visual_manager': vm,
                        'stato': 'inviato',
                        'submitted_at': now,
                    }
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                symbol = '+' if created else '~'
                self.stdout.write(f'  {symbol} {codice} {name} box {box}')

        self.stdout.write(f'\n{"="*50}')
        self.stdout.write(f'Creati:    {created_count}')
        self.stdout.write(f'Aggiornati:{updated_count}')
        if not_found:
            self.stdout.write(f'\nNon trovati ({len(not_found)}):')
            for m in not_found:
                self.stdout.write(f'  X {m}')
        else:
            self.stdout.write('Tutti i nomi trovati nel DB!')
