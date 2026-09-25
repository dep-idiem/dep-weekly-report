"""Cumplimiento del plan semanal (porciones) por proyecto y semana. Funciones puras.

Solo agregados por proyecto y semana: el detalle por persona es de la fase 5 (personas.py) y no se escribe.
Semanas de lunes a domingo.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Mapping, Sequence

from .calendario import Calendario
from .estructura import PorcionPlan
from .metricas import Horas
from .proyecto import ADV_CUMPLIMIENTO, Aviso

SEMANAS_ATRAS = 8
SEMANAS_ADELANTE = 4
BAJO, ALTO = 0.5, 1.5


def lunes(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def semanas(corte: dt.date, atras: int = SEMANAS_ATRAS, adelante: int = SEMANAS_ADELANTE) -> tuple[list, list]:
    """(semanas pasadas, incluida la del corte; semanas futuras), como lunes."""
    l0 = lunes(corte)
    return ([l0 - dt.timedelta(weeks=k) for k in range(atras - 1, -1, -1)],
            [l0 + dt.timedelta(weeks=k) for k in range(1, adelante + 1)])


def filas(plan: Sequence[PorcionPlan], horas: Sequence[Horas], corte: dt.date) -> list[dict]:
    """{semana, hh_planificadas, hh_registradas, cumplimiento}; las semanas futuras sin registradas."""
    pasadas, futuras = semanas(corte)
    plan_s: dict[dt.date, float] = defaultdict(float)
    for p in plan:
        plan_s[lunes(p.fecha)] += p.horas
    reg_s: dict[dt.date, float] = defaultdict(float)
    for h in horas:
        if h.fecha <= corte:
            reg_s[lunes(h.fecha)] += h.horas
    out = []
    for s in pasadas + futuras:
        pl = plan_s.get(s, 0.0)
        reg = reg_s.get(s, 0.0) if s in pasadas else None
        out.append({"semana": s, "hh_planificadas": pl, "hh_registradas": reg,
                    "cumplimiento": reg / pl if (reg is not None and pl) else None})
    return out


def aviso_cumplimiento(fs: Sequence[dict], corte: dt.date, minimo: int = 3, ventana: int = 4) -> list[Aviso]:
    """Cumplimiento < 50 % o > 150 % en `minimo` de las ultimas `ventana` semanas (con plan)."""
    pasadas = [f for f in fs if f["semana"] <= lunes(corte)][-ventana:]
    fuera = [f for f in pasadas if f["cumplimiento"] is not None and not (BAJO <= f["cumplimiento"] <= ALTO)]
    if len(fuera) < minimo:
        return []
    bajo = sum(1 for f in fuera if f["cumplimiento"] < BAJO)
    return [Aviso(ADV_CUMPLIMIENTO, "", f"Cumplimiento fuera de 50-150 % en {len(fuera)} de las últimas {len(pasadas)} "
                                        "semanas: " + ", ".join(f"{f['semana']:%d-%m} {f['cumplimiento']:.0%}" for f in fuera),
                  {"n": len(fuera), "ventana": len(pasadas), "bajo": bajo, "alto": len(fuera) - bajo})]


def pendientes_por_paquete(plan: Sequence[PorcionPlan], corte: dt.date, cal: Calendario) -> dict[str, dict[dt.date, float]]:
    """Proyeccion por plan semanal: time estimate de las porciones futuras (despues del corte), repartido en los
    dias habiles de la porcion, por paquete."""
    out: dict[str, dict[dt.date, float]] = defaultdict(lambda: defaultdict(float))
    for p in plan:
        if not p.paquete or p.fecha <= corte:
            continue
        a, b = (max(p.start, corte + dt.timedelta(days=1)), p.due) if (p.start and p.due) else (p.fecha, p.fecha)
        dias = list(cal.dias_habiles(a, b)) or [p.fecha]
        for d in dias:
            out[p.paquete][d] += p.horas / len(dias)
    return {k: dict(v) for k, v in out.items()}


def por_agregar(filas_semana: Mapping[str, Sequence[dict]]) -> dict[str, float]:
    """list_id -> cumplimiento de las 8 semanas pasadas (registradas / planificadas)."""
    out = {}
    for lid, fs in filas_semana.items():
        pl = sum(f["hh_planificadas"] for f in fs if f["hh_registradas"] is not None)
        reg = sum(f["hh_registradas"] for f in fs if f["hh_registradas"] is not None)
        out[lid] = reg / pl if pl else None
    return out
