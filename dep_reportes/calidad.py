"""Detector de problemas de datos en las tareas de un proyecto. Solo reporta; no corrige nada.

Convencion acordada para el futuro: HH Presupuestadas solo en tareas hoja.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .metricas import TareaMetrica

DOBLE_CONTEO = "hh_en_padre_y_subtarea"
HH_EN_PADRE = "hh_en_tarea_no_hoja"
SIN_FECHAS = "hh_sin_start_o_due"
DUE_ANTES_START = "due_anterior_a_start"
HH_VS_ESTIMATE = "hh_distinta_de_time_estimate"
AVANCE_SIN_HORAS = "avance_sin_horas"
HORAS_SIN_AVANCE = "horas_sin_avance"

SEVERIDAD = {
    DOBLE_CONTEO: "error", HH_EN_PADRE: "aviso", SIN_FECHAS: "error", DUE_ANTES_START: "error",
    HH_VS_ESTIMATE: "info", AVANCE_SIN_HORAS: "aviso", HORAS_SIN_AVANCE: "aviso",
}


@dataclass(frozen=True)
class Advertencia:
    tipo: str
    tarea_id: str
    tarea: str
    detalle: str
    datos: dict = field(default_factory=dict, compare=False)   # para el mensaje en español (presentacion.py)

    @property
    def severidad(self) -> str:
        return SEVERIDAD[self.tipo]


def detectar(tareas: Sequence[TareaMetrica], horas_por_tarea: Mapping[str, float] | None = None,
             estimate_h: Mapping[str, float | None] | None = None, tol_h: float = 1e-6) -> list[Advertencia]:
    """Advertencias sobre las tareas de un proyecto.

    horas_por_tarea: horas registradas por tarea, incluyendo las de sus subtareas (rolled up).
    estimate_h: time estimate de ClickUp en horas, por tarea.
    """
    hijos: dict[str, list[str]] = defaultdict(list)
    por_id = {t.id: t for t in tareas}
    for t in tareas:
        if t.parent:
            hijos[t.parent].append(t.id)

    def descendientes(tid: str) -> list[str]:
        out, pila = [], list(hijos.get(tid, []))
        while pila:
            x = pila.pop()
            out.append(x)
            pila.extend(hijos.get(x, []))
        return out

    tiene_hh = {t.id for t in tareas if t.hh is not None and t.hh > 0}
    adv: list[Advertencia] = []
    for t in tareas:
        hh = t.hh if t.hh is not None and t.hh > 0 else None
        if hh is not None and hijos.get(t.id):
            desc_hh = [d for d in descendientes(t.id) if d in tiene_hh]
            if desc_hh:
                suma = sum(por_id[d].hh for d in desc_hh)  # type: ignore[misc]
                nombres = ", ".join(por_id[d].nombre for d in desc_hh)
                adv.append(Advertencia(DOBLE_CONTEO, t.id, t.nombre,
                                       f"HH={hh:g} en el padre y {suma:g} en {len(desc_hh)} subtarea(s): {nombres}",
                                       {"hh": hh, "suma": suma, "n": len(desc_hh)}))
            else:
                adv.append(Advertencia(HH_EN_PADRE, t.id, t.nombre,
                                       f"HH={hh:g} en una tarea con {len(hijos[t.id])} subtarea(s) sin HH",
                                       {"hh": hh, "n": len(hijos[t.id])}))
        if hh is not None and (t.start is None or t.due is None):
            falta = " y ".join(x for x, v in (("start", t.start), ("due", t.due)) if v is None)
            adv.append(Advertencia(SIN_FECHAS, t.id, t.nombre, f"HH={hh:g} sin {falta}", {"hh": hh, "falta": falta}))
        if t.start is not None and t.due is not None and t.due < t.start:
            adv.append(Advertencia(DUE_ANTES_START, t.id, t.nombre, f"start {t.start} > due {t.due}",
                                   {"start": t.start, "due": t.due}))
        if hh is not None and estimate_h is not None:
            est = estimate_h.get(t.id)
            if est is None or abs(est - hh) > tol_h:
                txt = "sin time estimate" if est is None else f"time estimate {est:g} h"
                adv.append(Advertencia(HH_VS_ESTIMATE, t.id, t.nombre, f"HH={hh:g} vs {txt}", {"hh": hh, "estimate": est}))
        if horas_por_tarea is not None:
            h = horas_por_tarea.get(t.id, 0.0)
            av = t.avance or 0.0
            if av > 0 and h <= tol_h:
                adv.append(Advertencia(AVANCE_SIN_HORAS, t.id, t.nombre, f"avance {av:.0%} y 0 h registradas", {"avance": av}))
            elif av == 0 and h > tol_h:
                adv.append(Advertencia(HORAS_SIN_AVANCE, t.id, t.nombre, f"avance 0% y {h:.2f} h registradas", {"horas": h}))
    return adv


def incumple_hh_en_hojas(adv: Sequence[Advertencia]) -> bool:
    """True si el proyecto tiene HH en alguna tarea que no es hoja (convencion futura)."""
    return any(a.tipo in (DOBLE_CONTEO, HH_EN_PADRE) for a in adv)
