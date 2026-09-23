"""Configuracion del cliente de ClickUp. El token viene del entorno (.env en local, secreto en CI)."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

import truststore
from dotenv import load_dotenv

# Verificacion TLS contra el almacen de Windows (Kaspersky inspecciona HTTPS en este equipo).
truststore.inject_into_ssl()

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TZ = ZoneInfo("America/Santiago")
API_BASE = "https://api.clickup.com/api/v2"

# Limite documentado: 100 peticiones/min por token. Se deja margen.
MAX_REQUESTS_PER_MIN = 90
MAX_RETRIES = 5


def api_token() -> str:
    """CLICKUP_API_TOKEN (nombre de la tarea de reportes) o CLICKUP_TOKEN (nombre usado en .env)."""
    token = os.getenv("CLICKUP_API_TOKEN") or os.getenv("CLICKUP_TOKEN") or ""
    if not token:
        raise RuntimeError("Falta CLICKUP_API_TOKEN (o CLICKUP_TOKEN) en el entorno/.env")
    return token
