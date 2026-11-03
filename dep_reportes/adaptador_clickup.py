"""De objetos de dep_clickup a los insumos de metricas.py."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from typing import Iterable, Mapping

from dep_clickup.models import Task, TimeEntry

from .metricas import Horas, TareaMetrica

CAMPO_HH = "HH Presupuestadas"
CAMPO_AVANCE = "Avance Real"
ADMINISTRACION = re.compile(r"^\s*0?0\s+administraci", re.I)


def es_administracion(t: Task) -> bool:
    """La fase "00 Administración": sus HH son el presupuesto contractual, no parte de la curva S. En una lista v2
    («00 Administración y cierre») es un cajón más: ver a_tareas_metrica y v2.py."""
    return not t.parent and bool(ADMINISTRACION.match(t.name or ""))


def hh_de(t: Task) -> float:
    v = t.cf(CAMPO_HH)
    return float(v) if v not in (None, "") and float(v) > 0 else 0.0


def a_tarea_metrica(t: Task, v2: bool = False) -> TareaMetrica:
    # presupuesto contractual: fuera del universo, salvo en listas v2 (00 Administración y cierre es un cajón)
    hh = None if (es_administracion(t) and not v2) else t.cf(CAMPO_HH)
    return TareaMetrica(
        id=t.id, nombre=t.name, parent=t.parent,
        start=t.start_date, due=t.due_date,
        hh=float(hh) if hh is not None else None,
        avance=t.cf(CAMPO_AVANCE),
        estado=t.status,
    )


def con_ancestro_con_hh(tareas: Iterable[Task], v2: bool) -> set[str]:
    """Tareas con algún ancestro (padre, abuelo, ...) con HH Presupuestadas: sus HH no suman al presupuesto
    (decisión de Ale del 2026-11-02; docs/definiciones_reporte.md). 00 Administración de una lista antigua no cuenta
    como ancestro con HH (es el presupuesto contractual, fuera de la curva)."""
    por_id = {t.id: t for t in tareas}
    cuenta = lambda t: hh_de(t) > 0 and not (es_administracion(t) and not v2)
    out = set()
    for t in por_id.values():
        p, vistos = t.parent, set()
        while p in por_id and p not in vistos:
            vistos.add(p)
            if cuenta(por_id[p]):
                out.add(t.id)
                break
            p = por_id[p].parent
    return out


def a_tareas_metrica(tareas: Iterable[Task], solo_superiores: bool = True) -> list[TareaMetrica]:
    """solo_superiores: las HH de una tarea con un ancestro con HH quedan vacías (no suman). False: las HH tal cual
    están en ClickUp (detector de calidad, que avisa el doble conteo)."""
    from .v2 import es_v2
    tareas = list(tareas)
    v2 = es_v2(tareas)
    tm = [a_tarea_metrica(t, v2) for t in tareas]
    if not solo_superiores:
        return tm
    debajo = con_ancestro_con_hh(tareas, v2)
    return [replace(x, hh=None) if x.id in debajo else x for x in tm]


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
