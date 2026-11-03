"""Curva programada única para todas las listas PJ, antiguas y v2 (TAREA_curva_programada_unica, 2026-11-03).

Lo único que se considera confiable en todas las listas: las fechas de la lista y las horas registradas. Funciones
puras.

- Presupuesto: HH Presupuestadas de las tareas sin ningún ancestro con HH (adaptador_clickup.a_tareas_metrica).
- Programada: cada tarea del presupuesto reparte sus HH por día hábil entre su inicio y su término. Si le falta una
  fecha, las fechas están al revés, no tiene días hábiles o alguna cae fuera de [inicio, término] de la lista, sus HH
  se reparten entre el inicio y el término de la lista (respaldo).
- programada_modo: `tareas` (ninguna cayó al respaldo), `mixta` (algunas) o `lineal` (todas: la curva es una recta
  entre inicio y término de la lista).
- estado_curva del proyecto: `ok`, `sin_presupuesto` (presupuesto 0: sin programada ni línea base),
  `presupuesto_incoherente` (horas registradas > presupuesto antes de la Rev. 0: no se congela), `retenida` (config
  "linea_base_retenida": se calcula todo, no se congela) o `recurrente` (lista de un programa de servicio continuo,
  config/programas.json: fuera de la curva S).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Sequence

from .calendario import Calendario
from .metricas import TareaMetrica

TAREAS, MIXTA, LINEAL = "tareas", "mixta", "lineal"
OK, SIN_PRESUPUESTO, INCOHERENTE, RETENIDA, RECURRENTE = (
    "ok", "sin_presupuesto", "presupuesto_incoherente", "retenida", "recurrente")
TOL_HORAS = 0.01


@dataclass(frozen=True)
class Respaldo:
    """Tarea del presupuesto cuyas HH se repartieron entre el inicio y el término de la lista."""
    task_id: str
    nombre: str
    hh: float
    start: dt.date | None
    due: dt.date | None
    motivo: str


@dataclass(frozen=True)
class Programada:
    tareas: list[TareaMetrica]          # tareas del presupuesto con las fechas con que se reparten
    modo: str | None                    # tareas / mixta / lineal; None sin presupuesto
    respaldo: list[Respaldo]
    inicio: dt.date | None              # rango de la lista con que se validó
    termino: dt.date | None

    @property
    def presupuesto(self) -> float:
        return sum(t.hh or 0.0 for t in self.tareas)


def _f(d: dt.date | None) -> str:
    return f"{d:%d-%m-%Y}" if d else "—"


def motivo_respaldo(t: TareaMetrica, inicio: dt.date | None, termino: dt.date | None, cal: Calendario) -> str | None:
    """Por qué la tarea no se reparte con sus propias fechas (None si se reparte con ellas)."""
    if t.start is None and t.due is None:
        return "sin fechas"
    if t.start is None:
        return "sin fecha de inicio"
    if t.due is None:
        return "sin fecha de término"
    if t.start > t.due:
        return f"inicio {_f(t.start)} posterior al término {_f(t.due)}"
    if inicio and t.start < inicio:
        return f"inicio {_f(t.start)} anterior al inicio de la lista {_f(inicio)}"
    if termino and t.due > termino:
        return f"término {_f(t.due)} posterior al término de la lista {_f(termino)}"
    if inicio and t.start > (termino or t.start):
        return f"inicio {_f(t.start)} posterior al término de la lista {_f(termino)}"
    if termino and t.due < (inicio or t.due):
        return f"término {_f(t.due)} anterior al inicio de la lista {_f(inicio)}"
    if cal.networkdays(t.start, t.due) <= 0:
        return f"sin días hábiles entre {_f(t.start)} y {_f(t.due)}"
    return None


def programar(universo: Sequence[TareaMetrica], inicio: dt.date | None, termino: dt.date | None,
              cal: Calendario) -> Programada:
    """Fechas con que se reparte cada tarea del presupuesto (`universo`: tareas con HH > 0 sin ancestro con HH).

    inicio, termino: de la lista (start_date y due_date) o, para una línea base, las guardadas al congelar. Si la lista
    no tiene alguna de las dos, el respaldo usa el inicio más temprano o el término más tardío de las tareas con fechas
    propias; si tampoco hay, la tarea queda sin fechas (no aporta a la curva).
    """
    tareas = [t for t in universo if t.hh and t.hh > 0]
    if not tareas:
        return Programada([], None, [], inicio, termino)
    motivos = {t.id: motivo_respaldo(t, inicio, termino, cal) for t in tareas}
    propias = [t for t in tareas if motivos[t.id] is None]
    a = inicio or min((t.start for t in propias), default=None)
    b = termino or max((t.due for t in propias), default=None)
    rango_ok = a is not None and b is not None and a <= b and cal.networkdays(a, b) > 0
    out, respaldo = [], []
    for t in tareas:
        m = motivos[t.id]
        if m is None:
            out.append(t)
            continue
        respaldo.append(Respaldo(t.id, t.nombre, float(t.hh), t.start, t.due, m))
        out.append(replace(t, start=a, due=b) if rango_ok else replace(t, start=None, due=None))
    modo = TAREAS if not respaldo else LINEAL if len(respaldo) == len(tareas) else MIXTA
    return Programada(out, modo, respaldo, inicio, termino)


def estado(presupuesto: float, gastadas: float, tiene_linea_base: bool, retenida: bool, recurrente: bool) -> str:
    """estado_curva del proyecto. El incoherente solo se evalúa antes de la Rev. 0 (después, el plan ya está
    congelado y el exceso es desvío)."""
    if recurrente:
        return RECURRENTE
    if not tiene_linea_base and presupuesto <= 0:
        return SIN_PRESUPUESTO
    if not tiene_linea_base and gastadas > presupuesto + TOL_HORAS:
        return INCOHERENTE
    if retenida and not tiene_linea_base:
        return RETENIDA
    return OK
