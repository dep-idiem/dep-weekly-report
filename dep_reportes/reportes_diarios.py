"""Reportes diarios de un programa (CMP-SHM: los de las 08:00 y las 17:00), para la pestaña programa_reportes_diarios.

Cada reporte es una tarea de la lista programas.<id>.reportes_diarios.list_id que pasa por
pendiente revision -> (observado) -> revisado -> aprobado -> enviado. El tiempo en cada estado sale de
/task/bulk_time_in_status (ClickUp): `since` es la primera vez que la tarea entro al estado. Se mide:
- generacion -> revision: de la creacion de la tarea a su entrada a «revisado»;
- revision -> aprobacion: de «revisado» a «aprobado»;
- aprobacion -> envio y generacion -> envio.
La aprobacion sale del campo «Fecha aprobación» (o, si esta vacio, del historial): «aprobado» suele durar segundos y
ClickUp no guarda los estados de menos de un minuto. Por lo mismo, sin «revisado» en el historial (se paso directo a
aprobado, o estuvo menos de un minuto) la revision -> aprobacion queda vacia. Un reporte que llego a «enviado» sin
aprobacion se cerro a mano para no enviarlo: enviado = False.
es_fin_de_semana: sabado, domingo o feriado (calendario del reporte), para repartir esos turnos entre revisores y
aprobadores.

Funciones puras salvo leer().
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Mapping, Sequence

from dep_clickup.config import TZ
from dep_clickup.models import Task

from .calendario import SIN_FERIADOS, Calendario

PENDIENTE, OBSERVADO, REVISADO, APROBADO, ENVIADO = "pendiente revisión", "observado", "revisado", "aprobado", "enviado"
NOMBRE = re.compile(r"(\d{1,2})-(\w{3})-(\d{4})\s*·\s*(\d{2})(\d{2})")
MESES = {m: i for i, m in enumerate(("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"), 1)}
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
LOTE = 100          # tareas por peticion de bulk_time_in_status
CAMPO_APROBACION = "Fecha aprobación"


def leer(cu, list_id: str) -> tuple[list[Task], dict[str, dict]]:
    """Tareas de la lista y su tiempo en estado (task_id -> respuesta de ClickUp)."""
    tareas = [t for t in cu.list_tasks(list_id, include_subtasks=False) if not t.parent]
    tis: dict[str, dict] = {}
    ids = [t.id for t in tareas]
    for i in range(0, len(ids), LOTE):
        tis.update(cu.get("/task/bulk_time_in_status/task_ids", [("task_ids", x) for x in ids[i:i + LOTE]]))
    return tareas, tis


def entradas(tis: Mapping) -> dict[str, dt.datetime]:
    """estado (minusculas) -> primera entrada, del historial y del estado actual."""
    out = {}
    for s in [*(tis.get("status_history") or []), tis.get("current_status") or {}]:
        since = (s.get("total_time") or {}).get("since")
        if s.get("status") and since:
            d = dt.datetime.fromtimestamp(int(since) / 1000, TZ)
            k = s["status"].strip().lower()
            out[k] = min(out[k], d) if k in out else d
    return out


def _min(a: dt.datetime | None, b: dt.datetime | None) -> float | None:
    return round((b - a).total_seconds() / 60, 1) if a and b and b >= a else None


def _fecha_hora(v) -> dt.datetime | None:
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=TZ)
    return None


def _personas(v) -> str:
    if not v:
        return ""
    return ", ".join(v) if isinstance(v, (list, tuple)) else str(v)


def fecha_turno(t: Task) -> tuple[dt.date | None, str]:
    """(fecha, "08:00"/"17:00") desde el nombre "Reporte diario · 03-nov-2026 · 1700"."""
    m = NOMBRE.search(t.name or "")
    if not m or m.group(2).lower() not in MESES:
        return None, ""
    return dt.date(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1))), f"{m.group(4)}:{m.group(5)}"


def filas(programa: str, programa_nombre: str, cliente: str, tareas: Sequence[Task], tis: Mapping[str, dict],
          corte: dt.date, tipo_corte: str, cal: Calendario = SIN_FERIADOS) -> list[dict]:
    out = []
    for t in tareas:
        fecha, turno = fecha_turno(t)
        if fecha is None or fecha > corte:
            continue
        e = entradas(tis.get(t.id) or {})
        generado = t.date_created
        # «aprobado» dura segundos (el envio es automatico) y ClickUp no guarda en el historial los estados de menos
        # de un minuto: manda el campo «Fecha aprobación» (lo escribe la automatizacion al aprobar).
        revisado, enviado_en = e.get(REVISADO), e.get(ENVIADO)
        aprobado = _fecha_hora(t.cf(CAMPO_APROBACION)) or e.get(APROBADO)
        enviado = bool(enviado_en and aprobado)
        out.append({"corte": corte, "tipo_corte": tipo_corte, "programa": programa, "programa_nombre": programa_nombre,
                    "cliente": cliente, "task_id": t.id, "nombre": t.name.strip(), "fecha": fecha, "turno": turno,
                    "dia_semana": DIAS[fecha.weekday()], "es_fin_de_semana": not cal.es_habil(fecha),
                    "estado": t.status, "generado_en": generado, "revisado_en": revisado, "aprobado_en": aprobado,
                    "enviado_en": enviado_en if enviado else None, "observado": OBSERVADO in e,
                    "enviado": enviado, "cerrado_sin_aprobar": bool(enviado_en and not aprobado),
                    "revisado_por": _personas(t.cf("Revisado por")), "aprobado_por": _personas(t.cf("Aprobada por")),
                    "min_generacion_revision": _min(generado, revisado),
                    "min_revision_aprobacion": _min(revisado, aprobado),
                    "min_aprobacion_envio": _min(aprobado, enviado_en) if enviado else None,
                    "min_generacion_envio": _min(generado, enviado_en) if enviado else None,
                    "url": t.url})
    return sorted(out, key=lambda f: (f["fecha"], f["turno"]))
