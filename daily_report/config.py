"""Configuración. Todo lo sensible viene de variables de entorno."""
import os
from datetime import date
from zoneinfo import ZoneInfo

CHANNEL_ID = os.environ.get("DAILY_SLACK_CHANNEL", "C08AHSM8VRS")
TOKEN_ENV = "SLACK_READONLY_TOKEN"
DB_PATH = os.environ.get("DAILY_DB", os.path.join("data", "daily.db"))
PEOPLE_FILE = os.environ.get("DAILY_PEOPLE_FILE", "people.json")
TZ = ZoneInfo(os.environ.get("DAILY_TZ", "America/Bogota"))

HISTORY_START = date(2026, 8, 27)       # primer Daily en Slack
STRUCTURED_START = date(2026, 9, 9)     # desde aquí hay marcas ✅ 🔄 ⬜

DAILY_PREFIX = "Daily Delivery —"
BULLETIN_PREFIX = "Boletín Daily —"

# Texto casi idéntico para la regla del tercer día (0..1, difflib).
SIMILARITY_THRESHOLD = 0.9

# Aceptar la marca escrita como palabra oficial ("— hecho") sin emoji.
# Con DAILY_STRICT_MARKS=1 esas líneas van a revisión.
STRICT_MARKS = os.environ.get("DAILY_STRICT_MARKS") == "1"

# Interruptor de apagado.
IMPORT_DISABLED = os.environ.get("DAILY_IMPORT_DISABLED") == "1"
