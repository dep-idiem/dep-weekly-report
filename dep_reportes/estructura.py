"""Clasificacion de las tareas de un proyecto: fase, paquete, porcion u otra. Funciones puras.

Dos planes superpuestos (analisis de estructura, reportes/analisis_estructura/informe.md):
- paquetes (JP): tareas con HH Presupuestadas; son el plan por entregable y la base de la curva S;
- porciones (planificadora): copias semanales por persona, sin HH y con time estimate; son el plan de capacidad.

Regla, en este orden:
1. paquete: cualquier tarea con HH Presupuestadas > 0, sea del nivel que sea (una hoja corta con HH es paquete, no
   porcion; una tarea de nivel 0 con HH tambien, con `es_fase` y la advertencia "fase con HH"). La fase
   "00 Administracion" no: sus HH son el presupuesto contractual.
2. fase: nivel 0.
   `recurrente` si el nombre trae un mes o un numero de periodo ("Jul 2026", "N°8", "Informe Mensual").
3. porcion: hoja de nivel >= 1, sin HH, sin numeracion de plantilla ("5.2", "5.2.a", "06"), que dura <= 7 dias
   o que no tiene fechas y si time estimate.
4. otra: el resto (agrupadores, tareas de plantilla sin HH, hitos).
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from dep_clickup.models import Task

from .adaptador_clickup import CAMPO_AVANCE, es_administracion, hh_de
from .proyecto import NO_APLICA

FASE, PAQUETE, PORCION, OTRA = "fase", "paquete", "porcion", "otra"
MANUAL, PORCIONES, SIN_DATO = "manual", "porciones", "sin_dato"
NUMERADA = re.compile(r"^\s*\d{1,2}(\.\d+)*(\.[a-z])?\b", re.I)
PERIODO = re.compile(r"\b(ene|feb|mar|abr|may|jun|jul|ago|sep|sept|oct|nov|dic|enero|febrero|marzo|abril|mayo|junio|"
                     r"julio|agosto|septiembre|octubre|noviembre|diciembre)\b|mensual|n°\s*\d", re.I)
MAX_DIAS_PORCION = 7


@dataclass(frozen=True)
class Clase:
    tipo: str
    nivel: int
    recurrente: bool = False        # paquete con mes o numero de periodo en el nombre
    paquete: str | None = None      # porcion: id del paquete ancestro mas cercano
    porcion_con_hh: bool = False    # paquete con forma de porcion semanal (se advierte: mover las HH al paquete)
    es_fase: bool = False           # paquete de nivel 0 (se advierte: mover las HH a un paquete con fechas)


def _dias(t: Task) -> int | None:
    return (t.due_date - t.start_date).days if t.start_date and t.due_date else None


def _sin_numero(nombre: str) -> str:
    return NUMERADA.sub("", nombre or "").strip().lower()


def _forma_de_porcion(t: Task) -> bool:
    """Hoja corta sin numeracion de plantilla (<= 7 dias, o sin fechas y con time estimate)."""
    d = _dias(t)
    sin_fechas = t.start_date is None and t.due_date is None
    return not NUMERADA.match(t.name or "") and ((d is not None and d <= MAX_DIAS_PORCION)
                                                 or (sin_fechas and (t.time_estimate_ms or 0) > 0))


def clasificar(tareas: Sequence[Task]) -> dict[str, Clase]:
    por_id = {t.id: t for t in tareas}
    hijos: dict[str, list[Task]] = defaultdict(list)
    for t in tareas:
        if t.parent in por_id:
            hijos[t.parent].append(t)

    def nivel(t: Task) -> int:
        n, x, vistos = 0, t, set()
        while x.parent in por_id and x.id not in vistos:
            vistos.add(x.id)
            x, n = por_id[x.parent], n + 1
        return n

    base: dict[str, Clase] = {}
    for t in tareas:
        n, hoja, hh = nivel(t), not hijos.get(t.id), hh_de(t)
        if n == 0 and (hh <= 0 or es_administracion(t)):
            base[t.id] = Clase(FASE, n)
        elif n == 0:
            base[t.id] = Clase(PAQUETE, n, bool(PERIODO.search(t.name or "")), es_fase=True)
        elif hh > 0:
            hermanas = [h for h in hijos.get(t.parent, []) if h.id != t.id]
            repite = any(h.name.strip().lower() == t.name.strip().lower() for h in hermanas)
            como_padre = t.parent in por_id and _sin_numero(por_id[t.parent].name) == _sin_numero(t.name)
            recurrente = bool(PERIODO.search(t.name or ""))
            base[t.id] = Clase(PAQUETE, n, recurrente,
                               porcion_con_hh=hoja and not recurrente and _forma_de_porcion(t) and (repite or como_padre))
        elif hoja and _forma_de_porcion(t):
            base[t.id] = Clase(PORCION, n)
        else:
            base[t.id] = Clase(OTRA, n)
    out = {}
    for tid, c in base.items():
        if c.tipo == PORCION:
            x, paq = por_id[tid], None
            while x.parent in por_id:
                x = por_id[x.parent]
                if base[x.id].tipo == PAQUETE:
                    paq = x.id
                    break
            c = Clase(c.tipo, c.nivel, paquete=paq)
        out[tid] = c
    return out


def es_no_aplica(t: Task) -> bool:
    return (t.status or "").strip().lower() == NO_APLICA


def porciones_de(clases: Mapping[str, Clase]) -> dict[str, list[str]]:
    """paquete -> ids de sus porciones."""
    out: dict[str, list[str]] = defaultdict(list)
    for tid, c in clases.items():
        if c.tipo == PORCION and c.paquete:
            out[c.paquete].append(tid)
    return dict(out)


def solo_porciones_debajo(tareas: Sequence[Task], clases: Mapping[str, Clase]) -> set[str]:
    """Tareas cuyas subtareas son todas porciones (estructura normal de un paquete: no se advierte)."""
    hijos: dict[str, list[str]] = defaultdict(list)
    for t in tareas:
        if t.parent:
            hijos[t.parent].append(t.id)
    return {p for p, hs in hijos.items() if hs and all(clases.get(h, Clase(OTRA, 0)).tipo == PORCION for h in hs)}


def avance_efectivo(tareas: Sequence[Task], clases: Mapping[str, Clase]) -> dict[str, tuple[float | None, str]]:
    """Paquete -> (avance 0-1, origen). Manual si es > 0; si no y tiene porciones (sin No Aplica), la fraccion de
    porciones en estado de tipo cerrado; si no, sin_dato (se conserva el valor manual, 0 o vacio)."""
    por_id = {t.id: t for t in tareas}
    porc = porciones_de(clases)
    out = {}
    for tid, c in clases.items():
        if c.tipo != PAQUETE:
            continue
        t = por_id[tid]
        manual = t.cf(CAMPO_AVANCE)
        ps = [por_id[p] for p in porc.get(tid, []) if not es_no_aplica(por_id[p])]
        if manual:
            out[tid] = (manual, MANUAL)
        elif ps:
            out[tid] = (sum(1 for p in ps if p.cerrada) / len(ps), PORCIONES)
        else:
            out[tid] = (manual, SIN_DATO)
    return out


@dataclass(frozen=True)
class PorcionPlan:
    task_id: str
    paquete: str | None
    fecha: dt.date          # fecha de la semana: inicio o, si falta, vencimiento
    start: dt.date | None
    due: dt.date | None
    horas: float            # time estimate


def plan_porciones(tareas: Sequence[Task], clases: Mapping[str, Clase]) -> list[PorcionPlan]:
    """Porciones con time estimate y alguna fecha (sin las No Aplica)."""
    out = []
    for t in tareas:
        c = clases.get(t.id)
        if not c or c.tipo != PORCION or not t.time_estimate_ms or es_no_aplica(t):
            continue
        f = t.start_date or t.due_date
        if f:
            out.append(PorcionPlan(t.id, c.paquete, f, t.start_date, t.due_date, t.time_estimate_ms / 3_600_000))
    return out
