from django.contrib import admin

from .models import FileArchiviato


@admin.register(FileArchiviato)
class FileArchiviatoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'dimensione', 'creato_il')
    search_fields = ('nome',)
    exclude = ('contenuto',)
