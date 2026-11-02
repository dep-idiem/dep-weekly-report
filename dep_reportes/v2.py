"""Estructura v2 de las listas PJ (cajones + checklists + hitos; pj_v2, desde PJ-2026.0271). Funciones puras.

Una lista es v2 si alguna tarea de primer nivel se llama «00 Administración y cierre» o lleva la etiqueta `v2`
(pj_v2 la pone en esa tarea). En una lista v2 (decisiones de Ale del 2026-11-02, reportes/auditoria_v2.md):
- los cajones son las tareas de primer nivel con HH Presupuestadas, «00 Administración y cierre» incluida: entran a
  la curva S y el presupuesto contractual es la suma de sus HH (presupuesto.hh_contrato);
- un cajón con HH no es una «fase con HH» (estructura.clasificar);
- la Rev. 0 se congela con lo primero entre la primera hora registrada en la lista y la primera porción creada
  (hija directa de un cajón con responsable y time estimate); hasta entonces el programado es PROVISIONAL, con las
  HH y fechas vigentes de los cajones (linea_base.decidir, run.procesar_lista);
- avance de un cajón: cerrado = 100 %; si no, «Avance Real» manual; si no, por consumo: horas / HH con tope 90 %
  (estructura.avance_efectivo).
"""
from __future__ import annotations

import datetime as dt
from typing import Sequence

from dep_clickup.models import Task

NOMBRE_ADMIN = "00 Administración y cierre"
TAG = "v2"
TOPE_CONSUMO = 0.9


def _norm(s: str) -> str:
    return " ".join((s or "").split()).casefold()


def es_tarea_v2(t: Task) -> bool:
    """Tarea de primer nivel que marca la lista como v2 (por nombre o por etiqueta)."""
    return not t.parent and (_norm(t.name) == _norm(NOMBRE_ADMIN)
                             or any(_norm(g) == TAG for g in getattr(t, "tags", ()) or ()))


def es_v2(tareas: Sequence[Task]) -> bool:
    return any(es_tarea_v2(t) for t in tareas)


def evento_congelar(tareas: Sequence[Task], fechas_horas: Sequence[dt.date], corte: dt.date) -> str | None:
    """Lo que dispara la Rev. 0 de una lista v2, o None si todavía no pasa: la primera hora registrada hasta el corte
    o la primera porción (hija directa de un cajón, con responsable y time estimate)."""
    horas = sorted(f for f in fechas_horas if f <= corte)
    if horas:
        return f"primera hora registrada el {horas[0]:%d-%m-%Y}"
    nivel0 = {t.id for t in tareas if not t.parent}
    porciones = sorted((t for t in tareas if t.parent in nivel0 and t.assignees and (t.time_estimate_ms or 0) > 0),
                       key=lambda t: (t.date_created.timestamp() if t.date_created else float("inf"), t.name))
    if porciones:
        return f"primera porción creada «{porciones[0].name}»"
    return None
