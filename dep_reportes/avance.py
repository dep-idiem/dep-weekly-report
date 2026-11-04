"""Avance físico calculado desde el estado de las porciones (TAREA_avance_fisico, 2026-11-04). Funciones puras.

Reemplaza al campo manual «Avance Real», que ya no entra en ningún cálculo (queda como columna informativa
`avance_manual`). Por tarea que aporta presupuesto (universo de la curva S), en este orden:
1. tarea cerrada (estado de tipo done/closed) -> 100 % (modo `cerrada`);
2. abierta con porciones (descendientes de cualquier nivel con `time_estimate`, sin No Aplica ni cancelado) ->
   Σ estimate de las porciones cerradas ÷ Σ estimate de todas (modo `porciones`);
3. abierta sin porciones y con checklists propios -> ítems marcados ÷ ítems totales (modo `checklist`);
4. el resto -> consumo: horas registradas en ella y sus descendientes ÷ HH, con tope 90 % (modo `consumo`).
Proyecto (y fase): Σ avance × HH ÷ Σ HH; modo = el de sus tareas abiertas si es uno solo, si no `mixto`.

Porción vencida abierta (advertencia `porcion_vencida_abierta`): porción de una tarea en modo `porciones` con término
anterior al corte, abierta y con horas registradas >= 50 % de su estimate. No se asume terminada: se muestra el avance
que tendría si se cerrara (`avance_fisico_si_cerradas`).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from dep_clickup.models import Task

from .adaptador_clickup import CAMPO_AVANCE

CERRADA, PORCIONES, CHECKLIST, CONSUMO, MIXTO = "cerrada", "porciones", "checklist", "consumo", "mixto"
TOPE_CONSUMO = 0.9
UMBRAL_VENCIDA = 0.5          # horas registradas / estimate desde la que una porción vencida abierta se avisa
EXCLUIDOS = {"no aplica", "cancelado", "cancelada"}


def excluida(t: Task) -> bool:
    """No Aplica o cancelada: fuera del denominador (y su subárbol también)."""
    return (t.status or "").strip().lower() in EXCLUIDOS


@dataclass(frozen=True)
class PorcionVencida:
    task_id: str
    nombre: str
    tarea: str              # id de la tarea que aporta presupuesto
    due: dt.date
    horas: float            # registradas en la porción y sus descendientes hasta el corte
    estimado: float         # time estimate en horas


@dataclass(frozen=True)
class AvanceTarea:
    avance: float
    modo: str
    manual: float | None = None                      # «Avance Real» de ClickUp (solo informativo)
    hh_porciones: float = 0.0                        # Σ estimate de las porciones (modo porciones)
    hh_cerradas: float = 0.0                         # Σ estimate de las porciones cerradas
    vencidas: tuple[PorcionVencida, ...] = field(default=(), compare=False)

    @property
    def si_cerradas(self) -> float:
        """Avance que tendría si se cerraran sus porciones vencidas abiertas."""
        if self.modo != PORCIONES or not self.hh_porciones:
            return self.avance
        return (self.hh_cerradas + sum(p.estimado for p in self.vencidas)) / self.hh_porciones


def _hijos(tareas: Iterable[Task]) -> dict[str, list[Task]]:
    out: dict[str, list[Task]] = defaultdict(list)
    for t in tareas:
        if t.parent:
            out[t.parent].append(t)
    return out


def _estimada(t: Task) -> bool:
    return (t.time_estimate_ms or 0) > 0


def porciones(tid: str, hijos: Mapping[str, Sequence[Task]]) -> list[Task]:
    """Descendientes con time estimate, sin No Aplica ni cancelados (ni sus subárboles). Si una porción tiene a su vez
    descendientes con estimate, cuentan esos y no ella (no se suma dos veces el mismo trabajo)."""
    out: list[Task] = []

    def tiene_estimada_debajo(x: Task) -> bool:
        return any(not excluida(h) and (_estimada(h) or tiene_estimada_debajo(h)) for h in hijos.get(x.id, ()))

    def recorrer(x_id: str, vistos: set[str]) -> None:
        for h in hijos.get(x_id, ()):
            if excluida(h) or h.id in vistos:
                continue
            vistos.add(h.id)
            if _estimada(h) and not tiene_estimada_debajo(h):
                out.append(h)
            else:
                recorrer(h.id, vistos)

    recorrer(tid, {tid})
    return out


def _horas(estimate_ms: int | None) -> float:
    return (estimate_ms or 0) / 3_600_000


def avance_tarea(t: Task, hh: float, hijos: Mapping[str, Sequence[Task]], horas: Mapping[str, float],
                 corte: dt.date) -> AvanceTarea:
    """horas: task_id -> horas registradas en la tarea y sus descendientes hasta el corte."""
    manual = t.cf(CAMPO_AVANCE)
    if t.cerrada:
        return AvanceTarea(1.0, CERRADA, manual)
    ps = porciones(t.id, hijos)
    den = sum(_horas(p.time_estimate_ms) for p in ps)
    if den > 0:
        num = sum(_horas(p.time_estimate_ms) for p in ps if p.cerrada)
        venc = tuple(PorcionVencida(p.id, p.name, t.id, p.due_date, horas.get(p.id, 0.0), _horas(p.time_estimate_ms))
                     for p in ps if not p.cerrada and p.due_date and p.due_date < corte
                     and horas.get(p.id, 0.0) >= UMBRAL_VENCIDA * _horas(p.time_estimate_ms))
        return AvanceTarea(num / den, PORCIONES, manual, den, num, venc)
    if t.checklist_total:
        return AvanceTarea(t.checklist_resueltos / t.checklist_total, CHECKLIST, manual)
    return AvanceTarea(min(horas.get(t.id, 0.0) / hh, TOPE_CONSUMO) if hh else 0.0, CONSUMO, manual)


def calcular(tareas: Sequence[Task], hh: Mapping[str, float], horas: Mapping[str, float],
             corte: dt.date) -> dict[str, AvanceTarea]:
    """task_id -> avance de cada tarea que aporta presupuesto (hh: task_id -> HH)."""
    por_id = {t.id: t for t in tareas}
    hijos = _hijos(tareas)
    return {tid: avance_tarea(por_id[tid], h, hijos, horas, corte) for tid, h in hh.items() if tid in por_id}


def modo_conjunto(avs: Iterable[AvanceTarea]) -> str | None:
    """El modo de las tareas abiertas si es uno solo; `mixto` si hay varios; `cerrada` si todas están cerradas."""
    avs = list(avs)
    modos = {a.modo for a in avs if a.modo != CERRADA}
    if not modos:
        return CERRADA if avs else None
    return modos.pop() if len(modos) == 1 else MIXTO


def resumen(avs: Mapping[str, AvanceTarea], hh: Mapping[str, float]) -> dict:
    """Columnas de proyecto (o de fase) sobre las tareas de `hh` (task_id -> HH)."""
    ids = [i for i in hh if i in avs and hh[i]]
    tot = sum(hh[i] for i in ids)
    if not tot:
        return {"avance_fisico": None, "avance_fisico_modo": None, "avance_manual": None,
                "hh_porciones_vencidas_abiertas": None, "n_porciones_vencidas_abiertas": None,
                "avance_fisico_si_cerradas": None}
    venc = [p for i in ids for p in avs[i].vencidas]
    manuales = [avs[i].manual for i in ids if avs[i].manual]
    return {
        "avance_fisico": sum(avs[i].avance * hh[i] for i in ids) / tot,
        "avance_fisico_modo": modo_conjunto(avs[i] for i in ids),
        # Un manual_progress en 0 viene siempre: sin ningún valor > 0 el campo no se usa en el proyecto.
        "avance_manual": sum((avs[i].manual or 0.0) * hh[i] for i in ids) / tot if manuales else None,
        "hh_porciones_vencidas_abiertas": sum(p.estimado for p in venc),
        "n_porciones_vencidas_abiertas": len(venc),
        "avance_fisico_si_cerradas": sum(avs[i].si_cerradas * hh[i] for i in ids) / tot,
    }
