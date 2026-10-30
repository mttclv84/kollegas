# Configurazione di gunicorn, letta in automatico all'avvio (qualunque sia il comando
# di start impostato su Render). Più processi, ciascuno con più thread: con molti
# negozi collegati insieme le richieste vengono servite in parallelo, non in coda.
import os

workers = int(os.getenv('WEB_CONCURRENCY', '2'))
worker_class = 'gthread'
threads = int(os.getenv('GUNICORN_THREADS', '4'))
timeout = 60
# Ricicla periodicamente i processi per contenere la memoria nel tempo.
max_requests = 1000
max_requests_jitter = 100
