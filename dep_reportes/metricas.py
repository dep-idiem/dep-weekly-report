"""Metricas de curva S y avance. Traduccion de las formulas del Excel "Curva S - Proyecto 2026.0152".

Funciones puras: reciben tareas, horas y fechas; no tocan la API.

Referencias al Excel:
- HH programadas diarias: Programado!P4:DC199; acumulado: fila 208.
- Avance programado: Programado!N (por tarea) y N2.
- Avance real: Avance!U (por tarea) y U2.
- HH pendientes diarias: Avance!W4:DJ199; acumulado: fila 208.
- Serie de resumen: Resumen!D54:G75.

El Excel mezcla dos exports: el programa (fechas y HH) sale de la hoja Programado y el avance real y
las fechas usadas en la proyeccion salen de la hoja Avance. Por eso las funciones reciben por separado
las tareas del programa y las tareas de avance; con datos de ClickUp ambas son la misma lista.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .calendario import SIN_FERIADOS, Calendario

# Una celda de fecha vacia vale 0 en Excel (serial 0). Se replica para tareas con HH sin fechas;
# el detector de calidad las marca aparte.
EXCEL_CERO = dt.date(1899, 12, 31)


@dataclass(frozen=True)
class TareaMetrica:
    id: str
    nombre: str
    parent: str | None
    start: dt.date | None
    due: dt.date | None
    hh: float | None          # HH Presupuestadas
    avance: float | None      # Avance Real como fraccion 0-1
    estado: str | None = None  # nombre del estado en ClickUp (p. ej. "no aplica")


@dataclass(frozen=True)
class Horas:
    fecha: dt.date            # fecha local del start de la entrada
    horas: float
    tarea_id: str = ""


@dataclass(frozen=True)
class PuntoSerie:
    fecha: dt.date
    programadas: float
    gastadas: float | None       # None = #N/A (fecha posterior al control)
    proyectadas: float | None    # None = #N/A


def _fecha(d: dt.date | None) -> dt.date:
    return d if d is not None else EXCEL_CERO


def _hh(t: TareaMetrica) -> float:
    return float(t.hh) if t.hh else 0.0


# --- Universo -----------------------------------------------------------------------------------

def universo(tareas: Iterable[TareaMetrica]) -> list[TareaMetrica]:
    """Toda tarea (padre u hoja) con HH Presupuestadas > 0."""
    return [t for t in tareas if t.hh is not None and t.hh > 0]


def total_hh(tareas: Iterable[TareaMetrica]) -> float:
    return sum(_hh(t) for t in universo(tareas))


# --- Programado ---------------------------------------------------------------------------------

def hh_programadas_tarea(t: TareaMetrica, cal: Calendario = SIN_FERIADOS) -> dict[dt.date, float]:
    """HH / networkdays(S, D) en cada dia habil de [S, D]."""
    if not t.hh or t.start is None or t.due is None:
        return {}  # Excel: con fecha vacia la condicion P$3<=$I nunca se cumple
    n = cal.networkdays(t.start, t.due)
    if n <= 0:
        return {}
    return {d: t.hh / n for d in cal.dias_habiles(t.start, t.due)}


def hh_programadas_diarias(tareas: Iterable[TareaMetrica], cal: Calendario = SIN_FERIADOS) -> dict[dt.date, float]:
    out: dict[dt.date, float] = defaultdict(float)
    for t in universo(tareas):
        for d, v in hh_programadas_tarea(t, cal).items():
            out[d] += v
    return dict(out)


def acumulado_a(diario: Mapping[dt.date, float], fecha: dt.date) -> float:
    """Suma de los valores diarios con dia <= fecha (INDEX/MATCH aproximado sobre la fila acumulada)."""
    return sum(v for d, v in diario.items() if d <= fecha)


def fraccion_programada(t: TareaMetrica, control: dt.date, cal: Calendario = SIN_FERIADOS) -> float:
    """0 si S > C; networkdays(S, C)/networkdays(S, D) si D >= C; 1 en otro caso."""
    s, d = _fecha(t.start), _fecha(t.due)
    if s > control:
        return 0.0
    if d >= control:
        n = cal.networkdays(s, d)
        return cal.networkdays(s, control) / n if n else 0.0
    return 1.0


def avance_programado(tareas: Iterable[TareaMetrica], control: dt.date, cal: Calendario = SIN_FERIADOS) -> float:
    u = universo(tareas)
    tot = total_hh(u)
    return sum(_hh(t) * fraccion_programada(t, control, cal) for t in u) / tot if tot else 0.0


# --- Real ---------------------------------------------------------------------------------------

def avance_real(tareas: Iterable[TareaMetrica]) -> float:
    u = universo(tareas)
    tot = total_hh(u)
    return sum((t.avance or 0.0) * _hh(t) for t in u) / tot if tot else 0.0


def hh_gastadas_a(fecha: dt.date, horas: Iterable[Horas], control: dt.date) -> float | None:
    """Horas con fecha estrictamente menor que `fecha`; None (#N/A) si fecha > control."""
    if fecha > control:
        return None
    return sum(h.horas for h in horas if h.fecha < fecha)


# --- Proyectado ---------------------------------------------------------------------------------

def hh_pendientes_tarea(t: TareaMetrica, control: dt.date, fin: dt.date,
                        cal: Calendario = SIN_FERIADOS) -> dict[dt.date, float]:
    """Reparto diario de (1 - avance) * HH (hoja Avance, W:DJ).

    - empezo antes de C y due < C (atrasada): entre C+1 y la fecha de termino del proyecto;
    - empezo antes de C y due >= C: entre C y su due;
    - no ha empezado (start >= C): entre su start y su due.
    """
    if not t.hh or (t.avance or 0.0) == 1:
        return {}
    pend = (1 - (t.avance or 0.0)) * t.hh
    s, d = _fecha(t.start), _fecha(t.due)
    if s < control:
        a, b = (control + dt.timedelta(days=1), fin) if d < control else (control, d)
    else:
        a, b = s, d
    n = cal.networkdays(a, b)
    if n <= 0:
        return {}  # IFERROR / rango vacio
    return {x: pend / n for x in cal.dias_habiles(a, b)}


def hh_pendientes_diarias(tareas: Iterable[TareaMetrica], control: dt.date, fin: dt.date,
                          cal: Calendario = SIN_FERIADOS) -> dict[dt.date, float]:
    out: dict[dt.date, float] = defaultdict(float)
    for t in universo(tareas):
        for d, v in hh_pendientes_tarea(t, control, fin, cal).items():
            out[d] += v
    return dict(out)


def hh_pendientes_total(tareas: Iterable[TareaMetrica]) -> float:
    """Avance!D2: suma de (1 - avance) * HH."""
    return sum((1 - (t.avance or 0.0)) * _hh(t) for t in universo(tareas))


# --- Serie de resumen ---------------------------------------------------------------------------

def serie_resumen(grilla: Sequence[dt.date], programa: Iterable[TareaMetrica], avance: Iterable[TareaMetrica],
                  horas: Sequence[Horas], control: dt.date, fin: dt.date,
                  cal: Calendario = SIN_FERIADOS) -> list[PuntoSerie]:
    """Resumen!D:G.

    Proyectadas (G): solo en puntos cuyo siguiente punto ya no tiene gastadas. En el ultimo punto con
    gastadas vale la base; despues, base + acumulado de pendientes. La base es VLOOKUP(C, D:F): las
    gastadas en el ultimo punto de la grilla <= C (no necesariamente las gastadas a C).
    """
    prog_diario = hh_programadas_diarias(programa, cal)
    pend_diario = hh_pendientes_diarias(avance, control, fin, cal)
    gastadas = [hh_gastadas_a(g, horas, control) for g in grilla]
    previos = [i for i, g in enumerate(grilla) if g <= control]
    base = gastadas[previos[-1]] if previos else None

    out = []
    for i, g in enumerate(grilla):
        sig_na = i + 1 >= len(grilla) or gastadas[i + 1] is None
        if not sig_na or base is None:
            proy = None
        elif gastadas[i] is None:
            proy = base + acumulado_a(pend_diario, g)
        else:
            proy = base
        out.append(PuntoSerie(g, acumulado_a(prog_diario, g), gastadas[i], proy))
    return out


def grilla(inicio: dt.date, fin: dt.date, control: dt.date, paso_dias: int = 7) -> list[dt.date]:
    """Grilla de fechas para el sistema: cada `paso_dias` desde inicio, mas la fecha de control y el fin.

    (La grilla del Excel salta de a 3 o 2 dias con formulas fijas por fila; para validar se usan sus fechas.)
    """
    pts = set()
    d = inicio
    while d <= fin:
        pts.add(d)
        d += dt.timedelta(days=paso_dias)
    pts.update({control, fin})
    return sorted(p for p in pts if inicio <= p <= fin)


# --- Agregacion por fase ------------------------------------------------------------------------

def fase_de(tarea_id: str, padres: Mapping[str, str | None]) -> str:
    """Ancestro de primer nivel (la propia tarea si no tiene padre)."""
    actual, vistos = tarea_id, set()
    while padres.get(actual) and actual not in vistos:
        vistos.add(actual)
        actual = padres[actual]  # type: ignore[assignment]
    return actual


@dataclass(frozen=True)
class ResumenFase:
    fase_id: str
    fase: str
    hh_programadas: float
    hh_programadas_a_control: float
    hh_gastadas_a_control: float


def agregado_por_fase(tareas: Sequence[TareaMetrica], horas: Iterable[Horas], control: dt.date,
                      cal: Calendario = SIN_FERIADOS, padres: Mapping[str, str | None] | None = None,
                      nombres: Mapping[str, str] | None = None) -> list[ResumenFase]:
    """Por fase: HH programadas totales, programadas a C (dias <= C) y gastadas a C (fecha < C).

    Las horas de tareas que no estan en `padres` (p. ej. tareas borradas) quedan en la fase "(sin fase)".
    """
    padres = dict(padres) if padres is not None else {t.id: t.parent for t in tareas}
    nombres = dict(nombres) if nombres is not None else {t.id: t.nombre for t in tareas}
    prog: dict[str, float] = defaultdict(float)
    prog_c: dict[str, float] = defaultdict(float)
    gast: dict[str, float] = defaultdict(float)
    for t in universo(tareas):
        f = fase_de(t.id, padres)
        prog[f] += _hh(t)
        prog_c[f] += acumulado_a(hh_programadas_tarea(t, cal), control)
    for h in horas:
        if h.fecha < control:
            f = fase_de(h.tarea_id, padres) if h.tarea_id in padres else "(sin fase)"
            gast[f] += h.horas
    fases = [t.id for t in tareas if not padres.get(t.id)]
    fases += sorted((set(prog) | set(gast)) - set(fases))
    out = [ResumenFase(f, nombres.get(f, f), prog.get(f, 0.0), prog_c.get(f, 0.0), gast.get(f, 0.0))
           for f in fases]
    return sorted(out, key=lambda r: r.fase)
