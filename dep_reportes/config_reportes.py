"""Parametros de los reportes DEP (fase 2)."""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

from dep_clickup.config import ROOT  # carga .env

FOLDER_PJ_INGENIERIA = "901316452800"
SHEETS_REPORTES_ID = os.getenv("SHEETS_REPORTES_ID", "")
DRY_RUN_DIR = ROOT / "reportes" / "dry_run"
RESPALDOS_DIR = ROOT / "reportes" / "respaldos"
TIME_ENTRIES_DESDE = dt.date(2024, 1, 1)


def parametros() -> dict:
    """config/reportes.json (parametros de negocio que no son secretos)."""
    import json
    p = ROOT / "config" / "reportes.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


RETENCION_PRELIMINAR_DIAS = int(parametros().get("retencion_preliminar_dias", 15))


@dataclass(frozen=True)
class ImportacionExcel:
    ruta: Path
    fecha_entrega_contractual: dt.date


# Proyectos en curso cuya Rev. 0 se importa desde el Excel manual (decision 6 de la fase 2).
IMPORTADAS = {
    "901328186343": ImportacionExcel(ROOT / "fixtures" / "Curva S - Proyecto 2026.0152.xlsx", dt.date(2026, 10, 2)),
}
