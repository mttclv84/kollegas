import openpyxl
from django.core.management.base import BaseCommand
from django.db import transaction
from events.models import Host


class Command(BaseCommand):
    help = 'Importa host da gestione host.xlsx'

    def add_arguments(self, parser):
        parser.add_argument('file', nargs='?',
            default=r'C:\Users\matti\OneDrive\Desktop\Popsquare2.0\gestione host.xlsx')

    def handle(self, *args, **options):
        wb = openpyxl.load_workbook(options['file'])
        ws = wb.active

        creati = gia_presenti = 0
        with transaction.atomic():
            for row in ws.iter_rows(min_row=2, values_only=True):
                _, valore = row
                if not valore:
                    continue
                nome = str(valore).strip()
                _, created = Host.objects.get_or_create(
                    descrizione=nome,
                    defaults={'posizione': 'interno', 'is_active': True}
                )
                if created:
                    creati += 1
                    self.stdout.write(f'  + {nome}')
                else:
                    gia_presenti += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nHost: {creati} creati, {gia_presenti} già presenti'
        ))
