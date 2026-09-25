"""Presupuesto contractual del proyecto. Funciones puras.

Fuente: HH Presupuestadas de la tarea "00 Administracion" de la lista (la API no expone campos de la lista), o
config/presupuestos.json (codigo -> HH) para casos especiales, que manda sobre la tarea. Las HH de 00 Administracion
NO entran al universo de la curva S (adaptador_clickup.a_tarea_metrica).
"""
from __future__ import annotations

import datetime as dt
from typing import Sequence

from dep_clickup.models import Task

from .adaptador_clickup import es_administracion, hh_de
from .metricas import Horas
from .proyecto import ADV_PRESUPUESTO_POR_AGOTARSE, ADV_SIN_PRESUPUESTO, Aviso

SEMANAS_RITMO = 4
SEMANAS_ALERTA = 4


def hh_contrato(tareas: Sequence[Task], manual: float | None = None) -> float | None:
    if manual:
        return float(manual)
    v = sum(hh_de(t) for t in tareas if es_administracion(t))
    return v or None


def metricas(contrato: float | None, gastadas: float | None, horas: Sequence[Horas], corte: dt.date) -> dict:
    """hh_contrato, pct_contrato_usado, ritmo_semanal (promedio de las ultimas 4 semanas), semanas_restantes_al_ritmo
    y fecha_agotamiento_estimada (vacia si ya se supero o si no hay ritmo)."""
    desde = corte - dt.timedelta(days=7 * SEMANAS_RITMO - 1)
    ritmo = sum(h.horas for h in horas if desde <= h.fecha <= corte) / SEMANAS_RITMO
    out = {"hh_contrato": contrato, "pct_contrato_usado": None, "ritmo_semanal": ritmo,
           "semanas_restantes_al_ritmo": None, "fecha_agotamiento_estimada": None}
    if contrato and gastadas is not None:
        out["pct_contrato_usado"] = gastadas / contrato
        if ritmo > 0:
            sem = (contrato - gastadas) / ritmo
            out["semanas_restantes_al_ritmo"] = sem
            if sem > 0:
                out["fecha_agotamiento_estimada"] = corte + dt.timedelta(days=round(sem * 7))
    return out


def avisos(m: dict, alerta_semanas: float = SEMANAS_ALERTA) -> list[Aviso]:
    if not m.get("hh_contrato"):
        return [Aviso(ADV_SIN_PRESUPUESTO, "", "Sin HH Presupuestadas en 00 Administración ni en config/presupuestos.json")]
    pct, sem = m.get("pct_contrato_usado"), m.get("semanas_restantes_al_ritmo")
    superado = pct is not None and pct >= 1
    if superado or (sem is not None and sem < alerta_semanas):
        return [Aviso(ADV_PRESUPUESTO_POR_AGOTARSE, "",
                      f"Presupuesto usado {pct:.0%}" + ("" if superado else f"; se agota en {sem:.1f} semanas al ritmo actual"),
                      {"pct": pct, "superado": superado, "semanas": sem, "fecha": m.get("fecha_agotamiento_estimada"),
                       "contrato": m["hh_contrato"]})]
    return []
