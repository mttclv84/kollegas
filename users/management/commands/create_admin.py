from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    def handle(self, *args, **options):
        User = get_user_model()
        email = 'mcalvi@primark.it'
        if not User.objects.filter(email=email).exists():
            u = User.objects.create_superuser(
                email=email,
                password='Primark01!',
                cognome='Calvi',
                nome='Mattia',
                livello_accesso='admin',
            )
            u.raw_password = 'Primark01!'
            u.save()
            self.stdout.write('Admin creato.')
        else:
            self.stdout.write('Admin già esistente.')
