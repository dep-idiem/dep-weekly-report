"""Prueba de humo OAuth de Google: lee e imprime el titulo de la hoja SHEETS_REPORTES_ID. Solo lectura.

La primera vez abre el navegador para iniciar sesion y guarda secrets/google_token.json.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dep_reportes.google_auth import sesion  # noqa: E402


def main() -> int:
    sheet_id = os.getenv("SHEETS_REPORTES_ID")
    if not sheet_id:
        print("Falta SHEETS_REPORTES_ID en .env", file=sys.stderr)
        return 2
    s = sesion(interactivo=True)
    r = s.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}", params={"fields": "properties.title"},
              timeout=60)
    if r.status_code != 200:
        print(f"Error {r.status_code}: {r.text[:500]}", file=sys.stderr)
        return 1
    print(r.json()["properties"]["title"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
