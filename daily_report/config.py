"""Configuración. Todo lo sensible viene de variables de entorno."""
import os
from datetime import date
from zoneinfo import ZoneInfo

CHANNEL_ID = os.environ.get("DAILY_SLACK_CHANNEL", "C08AHSM8VRS")
TOKEN_ENV = "SLACK_READONLY_TOKEN"
# Postgres. Credenciales solo por variables de entorno.
DATABASE_URL = os.environ.get("DATABASE_URL")                  # dueño: importación y migraciones
APP_DATABASE_URL = os.environ.get("DAILY_APP_DATABASE_URL")    # rol de la app, pasa por RLS
APP_DB_ROLE = os.environ.get("DAILY_APP_DB_ROLE", "daily_app")
PEOPLE_FILE = os.environ.get("DAILY_PEOPLE_FILE", "people.json")
TZ = ZoneInfo(os.environ.get("DAILY_TZ", "America/Bogota"))

HISTORY_START = date(2026, 8, 27)       # primer Daily en Slack
STRUCTURED_START = date(2026, 9, 9)     # desde aquí hay marcas ✅ 🔄 ⬜

DAILY_PREFIX = "Daily Delivery —"
BULLETIN_PREFIX = "Boletín Daily —"

HISTORY_FILE = os.environ.get("DAILY_HISTORY_FILE", "daily_historia_2026-08-27_a_09-30.json")

# Regla del tercer día:
#  - con el mismo link de Monday, el texto además debe ser parecido;
#  - sin link (o con links distintos), el texto debe ser casi idéntico.
LINKED_SIMILARITY_THRESHOLD = 0.5
SIMILARITY_THRESHOLD = 0.9

# Aceptar la marca escrita como palabra oficial ("— hecho") sin emoji.
# Con DAILY_STRICT_MARKS=1 esas líneas van a revisión.
STRICT_MARKS = os.environ.get("DAILY_STRICT_MARKS") == "1"

# Interruptor de apagado.
IMPORT_DISABLED = os.environ.get("DAILY_IMPORT_DISABLED") == "1"

# La importación directa desde Slack quedó desactivada: la historia viene del
# archivo JSON. Para volver a usarla hay que poner DAILY_SLACK_IMPORT_ENABLED=1.
SLACK_IMPORT_ENABLED = os.environ.get("DAILY_SLACK_IMPORT_ENABLED") == "1"

