"""Parametros de los reportes DEP (fase 2)."""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

from dep_clickup.config import ROOT  # carga .env

FOLDER_PJ_INGENIERIA = "901316452800"
# Espacio Proyectos Activos: los proyectos que terminan se mueven de PJ Ingenieria a este folder (finalizados.py).
FOLDER_PROYECTOS_FINALIZADOS = "901318475416"
SHEETS_REPORTES_ID = os.getenv("SHEETS_REPORTES_ID", "")
DRY_RUN_DIR = ROOT / "reportes" / "dry_run"
RESPALDOS_DIR = ROOT / "reportes" / "respaldos"
TIME_ENTRIES_DESDE = dt.date(2024, 1, 1)
PROGRAMAS_JSON = ROOT / "config" / "programas.json"      # programas de servicio continuo (programas.py)


def parametros() -> dict:
    """config/reportes.json (parametros de negocio que no son secretos)."""
    import json
    p = ROOT / "config" / "reportes.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


RETENCION_PRELIMINAR_DIAS = int(parametros().get("retencion_preliminar_dias", 15))
# Reglas de conteo de horas (horas.py)
TIMETRACKER_LIST_ID = parametros().get("timetracker_list_id", "")
UMBRAL_HORAS_ADMINISTRACION = float(parametros().get("umbral_horas_administracion", 0.2))
MINIMO_HORAS_ADMINISTRACION = float(parametros().get("minimo_horas_administracion", 20))
# Fase 2b: "uniforme" (reparto de las HH pendientes) o "plan_semanal" (time estimates de las porciones futuras)
PROYECCION = parametros().get("proyeccion", "uniforme")
# Presentacion: umbrales del semaforo (presentacion.UmbralesSemaforo) y horizonte de "vence en" de fotos_tareas
UMBRALES_SEMAFORO = dict(parametros().get("semaforo") or {})
HORIZONTE_VENCIMIENTOS_DIAS = int(parametros().get("horizonte_vencimientos_dias", 14))
# Lista SS_REGISTRO (Propuestas / MAESTRO): horas registradas en la tarea de la SS de cada proyecto (columna aparte,
# fuera de la curva S; plan_vs_real.py)
SS_REGISTRO_LIST_ID = parametros().get("ss_registro_list_id", "901324495476")
# Hoja aparte, de acceso restringido a los JP, con la pestaña plan_vs_real (datos por persona). Nunca «DEP - Reportes».
# Sin id: la pestaña solo se escribe en el CSV del dry-run.
SHEETS_PLAN_VS_REAL_ID = os.getenv("SHEETS_PLAN_VS_REAL_ID", "")


def lineas_base_retenidas() -> dict[str, str]:
    """config/reportes.json "linea_base_retenida": list_id -> motivo. Esas listas no congelan la Rev. 0 (quedan con
    programado provisional) hasta que se saquen de la lista."""
    return {str(k): str(v) for k, v in (parametros().get("linea_base_retenida") or {}).items()}


def presupuestos() -> dict[str, float]:
    """config/presupuestos.json: codigo del proyecto -> HH contratadas (manda sobre la tarea 00 Administración)."""
    import json
    p = ROOT / "config" / "presupuestos.json"
    return {k: float(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()} if p.exists() else {}


def cortes_historicos() -> dict[str, dt.date]:
    """codigo del proyecto -> fecha de corte historico fijada a mano (si falta: primera entrada nativa)."""
    return {k: dt.date.fromisoformat(v) for k, v in (parametros().get("corte_historico") or {}).items()}


@dataclass(frozen=True)
class ImportacionExcel:
    ruta: Path
    fecha_entrega_contractual: dt.date


# Proyectos en curso cuya Rev. 0 se importa desde el Excel manual (decision 6 de la fase 2).
IMPORTADAS = {
    "901328186343": ImportacionExcel(ROOT / "fixtures" / "Curva S - Proyecto 2026.0152.xlsx", dt.date(2026, 10, 2)),
}
