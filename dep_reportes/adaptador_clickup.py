"""De objetos de dep_clickup a los insumos de metricas.py."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from dep_clickup.models import Task, TimeEntry

from .metricas import Horas, TareaMetrica

CAMPO_HH = "HH Presupuestadas"
CAMPO_AVANCE = "Avance Real"


def a_tarea_metrica(t: Task) -> TareaMetrica:
    hh = t.cf(CAMPO_HH)
    return TareaMetrica(
        id=t.id, nombre=t.name, parent=t.parent,
        start=t.start_date, due=t.due_date,
        hh=float(hh) if hh is not None else None,
        avance=t.cf(CAMPO_AVANCE),
        estado=t.status,
    )


def a_tareas_metrica(tareas: Iterable[Task]) -> list[TareaMetrica]:
    return [a_tarea_metrica(t) for t in tareas]


def a_horas(entradas: Iterable[TimeEntry]) -> list[Horas]:
    return [Horas(e.date, e.hours, e.task_id) for e in entradas]


def horas_por_tarea(horas: Iterable[Horas], padres: Mapping[str, str | None] | None = None,
                    acumular_en_ancestros: bool = False) -> dict[str, float]:
    """Horas por tarea; con acumular_en_ancestros, cada tarea suma tambien las de sus descendientes."""
    out: dict[str, float] = defaultdict(float)
    for h in horas:
        out[h.tarea_id] += h.horas
        if acumular_en_ancestros and padres:
            p, vistos = padres.get(h.tarea_id), set()
            while p and p not in vistos:
                vistos.add(p)
                out[p] += h.horas
                p = padres.get(p)
    return dict(out)
