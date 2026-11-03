"""Estructura v2 de las listas PJ (cajones + checklists + hitos; pj_v2, desde PJ-2026.0271). Funciones puras.

Una lista es v2 si alguna tarea de primer nivel se llama «00 Administración y cierre» o lleva la etiqueta `v2`
(pj_v2 la pone en esa tarea). En una lista v2 (decisiones de Ale del 2026-11-02, reportes/auditoria_v2.md):
- los cajones son las tareas de primer nivel con HH Presupuestadas, «00 Administración y cierre» incluida: entran a
  la curva S y el presupuesto contractual es la suma de sus HH (presupuesto.hh_contrato);
- un cajón con HH no es una «fase con HH» (estructura.clasificar);
- la Rev. 0 se congela con la regla común a todas las listas desde el 2026-11-02 (linea_base.evento_congelar): lo
  primero entre la primera hora registrada y la primera porción creada; hasta entonces el programado es PROVISIONAL;
- avance de un cajón: cerrado = 100 %; si no, «Avance Real» manual; si no, por consumo: horas / HH con tope 90 %
  (estructura.avance_efectivo).
"""
from __future__ import annotations

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
