"""Bloque C de la Fase 2: corrida diaria de la auditoría documental (job audit-docs de Actions).

    python -m audit_docs.diario --evento schedule|workflow_dispatch [--dry-run]

1. Con evento schedule corre solo a las 07:xx de Santiago: GitHub usa UTC y Chile cambia de horario,
   así que hay dos cron (10:00 y 11:00 UTC) y el que no cae a las 07 termina sin hacer nada.
2. recon.py (inventario + evaluación). Falla si ClickUp o Drive rechazan la autenticación.
3. Si hay links a «06 Backup» nuevos, los informa como advertencia (Make volvió a fallar). No los corrige:
   fix_links.py es una corrección puntual y no corre a diario.
4. Protección: si las tareas en alcance con carpeta (Completo + Incompleto) caen más de 30 % respecto de
   la corrida anterior (la pestaña docs_propuestas), falla sin escribir nada en ClickUp. Así un cambio de
   estructura en Drive no deja todo en Sin carpeta. Se cuentan las que tienen carpeta porque una carpeta
   que deja de resolver pasa a Sin carpeta y sigue en alcance: el total no bajaría.
5. sync_checklists.py --apply (o --dry-run).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys

from dep_clickup.config import TZ

from . import recon, sync_checklists
from .recon import OUT

CAIDA_MAXIMA = 0.30
HORA_LOCAL = 7


def _gh(nivel: str, msg: str) -> None:
    """Anotación de GitHub Actions (error/warning) y la misma línea en la salida normal."""
    print(f"::{nivel}::{msg}" if os.getenv("GITHUB_ACTIONS") else f"{nivel.upper()}: {msg}")


def con_carpeta_anterior() -> int | None:
    """Filas Completo/Incompleto de la pestaña docs_propuestas (la corrida anterior). None si no hay."""
    from dep_reportes.google_auth import sesion
    s = sesion(interactivo=False)
    r = s.get(f"https://sheets.googleapis.com/v4/spreadsheets/{os.environ['SHEETS_REPORTES_ID']}/values/"
              f"'{sync_checklists.PESTANA}'", timeout=60)
    if r.status_code == 400 and "Unable to parse range" in r.text:
        return None                     # la pestaña no existe todavía
    if r.status_code != 200:
        raise RuntimeError(f"Sheets {r.status_code} al leer {sync_checklists.PESTANA}: {r.text[:200]}")
    valores = r.json().get("values", [])
    if len(valores) < 2:
        return None
    i = valores[0].index("docs_ok")
    return sum(1 for f in valores[1:] if len(f) > i and f[i] in ("Completo", "Incompleto"))


def revisar(recon_csv, anterior: int | None) -> tuple[int, list[str], str | None]:
    """(tareas con carpeta ahora, códigos con link a una subcarpeta, error de la protección o None)."""
    ahora, backup = set(), set()
    with recon_csv.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["resultado_tarea"] in ("COMPLETO", "INCOMPLETO"):
                ahora.add(r["task_id"])
            if r["enlace"].startswith("subcarpeta"):
                backup.add(r["ss_code"])
    error = None
    if anterior and len(ahora) < anterior * (1 - CAIDA_MAXIMA):
        error = (f"Tareas en alcance con carpeta: {len(ahora)}, antes {anterior} (caída de "
                 f"{1 - len(ahora) / anterior:.0%}, máximo {CAIDA_MAXIMA:.0%}). No se escribe en ClickUp: "
                 "revisar la estructura de Drive y el reporte de recon.")
    return len(ahora), sorted(backup), error


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evento", default="workflow_dispatch")
    ap.add_argument("--dry-run", action="store_true", help="sync en dry-run: ninguna escritura en ClickUp ni Sheets")
    a = ap.parse_args(argv)
    ahora = dt.datetime.now(TZ)
    if a.evento == "schedule" and ahora.hour != HORA_LOCAL:
        print(f"{ahora:%H:%M} en Santiago: no es la hora de la corrida diaria ({HORA_LOCAL:02d}:xx). Nada que hacer.")
        return 0

    codigo = recon.main(["--no-interactivo"])
    if codigo:
        _gh("error", "recon.py falló (¿autenticación de Drive?); no se sincroniza ClickUp")
        return codigo
    recon_csv = OUT / f"recon_{ahora.date().isoformat()}.csv"
    n, backup, error = revisar(recon_csv, con_carpeta_anterior())
    print(f"Tareas en alcance con carpeta: {n}")
    if backup:
        _gh("warning", f"{len(backup)} tarea(s) con Drive PR URL apuntando a una subcarpeta (¿Make volvió a fallar?): "
                       + ", ".join(backup))
    if error:
        _gh("error", error)
        return 2
    return sync_checklists.main(["--dry-run" if a.dry_run else "--apply", "--recon", str(recon_csv)])


if __name__ == "__main__":
    sys.exit(main())
