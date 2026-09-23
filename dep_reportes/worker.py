"""Punto de entrada del worker de GitHub Actions (fase 3).

Calendario (hora de Santiago):
- Oficial: lunes 04:00, corte = domingo anterior. Ventana valida 04:00-05:59.
- Preliminar: martes a domingo 19:00, corte (fecha de control) = dia anterior. Ventana valida 19:00-20:59.

GitHub usa cron en UTC y Chile cambia de horario, por eso hay dos cron por tipo (07:00/08:00 UTC los lunes
para la oficial; 22:00/23:00 UTC martes a domingo para la preliminar) y este script decide por la hora
local: fuera de la ventana, o si ya hubo una corrida exitosa del mismo tipo ese dia, termina con exito
sin hacer nada (y lo dice en el log). La corrida manual (workflow_dispatch) ignora la ventana horaria.

Uso:
    python -m dep_reportes.worker --evento schedule
    python -m dep_reportes.worker --evento workflow_dispatch --tipo preliminar [--corte AAAA-MM-DD] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from dataclasses import dataclass
from typing import Sequence

from dep_clickup.config import TZ

from . import esquema as E

VENTANAS = {E.OFICIAL: (4, 6), E.PRELIMINAR: (19, 21)}   # [desde, hasta) en horas locales
DIAS = {E.OFICIAL: {0}, E.PRELIMINAR: {1, 2, 3, 4, 5, 6}}  # lunes = 0


@dataclass(frozen=True)
class Plan:
    ejecutar: bool
    tipo: str | None
    corte: dt.date | None
    motivo: str


def _ya_corrio(ejecuciones: Sequence[dict], tipo: str, hoy_local: dt.date) -> bool:
    return any(e.get("modo") == "escritura" and e.get("resultado") == "ok"
               and (e.get("tipo_corte") or E.OFICIAL) == tipo and e.get("ejecutado_en")
               and e["ejecutado_en"].astimezone(TZ).date() == hoy_local for e in ejecuciones)


def planificar(ahora: dt.datetime, evento: str, ejecuciones: Sequence[dict] = (), tipo: str | None = None,
               corte: dt.date | None = None, dry_run: bool = False) -> Plan:
    """Decide si corre, de que tipo y con que corte. `ahora` con zona horaria (cualquiera)."""
    local = ahora.astimezone(TZ)
    hoy = local.date()
    if evento == "schedule":
        tipo = next((t for t, (h0, h1) in VENTANAS.items()
                     if local.weekday() in DIAS[t] and h0 <= local.hour < h1), None)
        if tipo is None:
            return Plan(False, None, None, f"Fuera de ventana: {local:%A %Y-%m-%d %H:%M} hora de Santiago "
                                           "(oficial: lunes 04:00-05:59; preliminar: martes a domingo 19:00-20:59)")
        corte = hoy - dt.timedelta(days=1)
    else:
        if tipo not in VENTANAS:
            raise SystemExit(f"Tipo de corrida inválido: {tipo!r}")
        if corte is None:
            corte = hoy - dt.timedelta(days=1)
            if tipo == E.OFICIAL:
                corte -= dt.timedelta(days=(corte.weekday() + 1) % 7)   # domingo mas reciente antes de hoy
    if tipo == E.OFICIAL and corte.weekday() != 6:
        raise SystemExit(f"Corte oficial {corte} no es domingo")
    if not dry_run and _ya_corrio(ejecuciones, tipo, hoy):
        return Plan(False, tipo, corte, f"Ya hay una corrida {tipo} exitosa hoy ({hoy}); no se repite")
    return Plan(True, tipo, corte, f"Corrida {tipo} con corte {corte} ({'dry-run' if dry_run else 'escritura'})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dep_reportes.worker", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evento", required=True, help="github.event_name: schedule o workflow_dispatch")
    ap.add_argument("--tipo", choices=[E.OFICIAL, E.PRELIMINAR])
    ap.add_argument("--corte", default="")
    ap.add_argument("--dry-run", default="false", help="true/false (entrada de workflow_dispatch)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    dry = str(a.dry_run).strip().lower() in ("1", "true", "yes", "si", "sí")
    corte = dt.date.fromisoformat(a.corte) if a.corte.strip() else None
    ahora = dt.datetime.now(dt.timezone.utc)

    # La ventana horaria se decide sin tocar la red; la deduplicacion necesita leer `ejecuciones`.
    previo = planificar(ahora, a.evento, (), a.tipo, corte, dry_run=True)
    if not previo.ejecutar:
        print(previo.motivo)
        return 0

    from .almacen import AlmacenSheets
    from .config_reportes import SHEETS_REPORTES_ID
    from .run import ControlFallido, ejecutar, imprimir
    sheets = AlmacenSheets(SHEETS_REPORTES_ID)
    ejecuciones = sheets.leer(["ejecuciones"]).get("ejecuciones", [])
    plan = planificar(ahora, a.evento, ejecuciones, a.tipo, corte, dry_run=dry)
    print(plan.motivo)
    if not plan.ejecutar:
        return 0
    try:
        c = ejecutar(plan.corte, dry_run=dry, tipo_corte=plan.tipo, sheets=sheets)
    except ControlFallido as e:
        print(f"ERROR: {e}")
        return 1
    imprimir(c, dry)
    return 1 if c.fallos else 0


if __name__ == "__main__":
    sys.exit(main())
