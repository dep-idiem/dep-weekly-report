"""Donde viven los custom fields de un proyecto (lista, tarea "00 Administracion", fases, subtareas)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from dep_clickup.models import CustomFieldDef, Task

CAMPOS_INTERES = (
    "Avance Real", "HH Presupuestadas", "JP Responsable",
    "Fecha Entrega Contractual", "Fecha Entrega Contractual Inicial", "Fecha Inicio Proyecto",
    "Fecha Límite Interna DEP", "Fecha Límite Interna", "Fecha Revisión Director", "Fecha Entrega Real",
)


def nivel(t: Task) -> str:
    if t.parent:
        return "subtarea"
    return "00 Administración" if t.name.strip().startswith("00") else "fase (primer nivel)"


@dataclass(frozen=True)
class UbicacionCampo:
    nombre: str
    tipo: str | None             # None = el campo no existe en la lista
    con_valor: Counter           # nivel -> nº de tareas con valor


def ubicacion_campos(defs: Sequence[CustomFieldDef], tareas: Sequence[Task],
                     nombres: Sequence[str] | None = None) -> list[UbicacionCampo]:
    tipos = {d.name: d.type for d in defs}
    nombres = list(nombres) if nombres else sorted(tipos)
    for n in tipos:
        if n.startswith("Fecha") and n not in nombres:
            nombres.append(n)
    out = []
    for n in nombres:
        cnt: Counter = Counter()
        for t in tareas:
            f = t.custom_fields.get(n)
            # Un manual_progress en 0 viene siempre ({"current": 0}); no cuenta como dato cargado.
            if f is not None and f.value not in (None, "", []) and not (f.type.endswith("progress") and f.value == 0):
                cnt[nivel(t)] += 1
        out.append(UbicacionCampo(n, tipos.get(n), cnt))
    return out


def fmt_ubicacion(u: UbicacionCampo) -> str:
    if u.tipo is None:
        return "no existe en la lista"
    if not u.con_valor:
        return f"{u.tipo}; sin valores en ninguna tarea"
    return f"{u.tipo}; " + ", ".join(f"{k}: {v}" for k, v in sorted(u.con_valor.items()))
