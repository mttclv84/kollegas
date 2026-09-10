from django.apps import AppConfig


class EhsConfig(AppConfig):
    name = 'ehs'
    verbose_name = 'EHS'

    def ready(self):
        from . import signals  # noqa: F401
