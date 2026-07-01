from django.core.management.base import BaseCommand
from users.models import User


class Command(BaseCommand):
    help = 'Imposta Primark01! come password per tutti gli utenti senza password valida (o tutti se --all)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Reimposta la password anche agli utenti che ne hanno già una valida',
        )

    def handle(self, *args, **options):
        if options['all']:
            qs = User.objects.all()
            label = 'tutti'
        else:
            qs = User.objects.filter(password__in=['', '!'])
            label = 'senza password valida'

        count = qs.count()
        self.stdout.write(f'Utenti {label}: {count}')

        updated = 0
        for user in qs:
            user.set_password('Primark01!')
            user.raw_password = 'Primark01!'
            user.save(update_fields=['password', 'raw_password'])
            updated += 1

        self.stdout.write(self.style.SUCCESS(f'Password aggiornata per {updated} utenti.'))
