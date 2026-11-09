"""Ausencias desde la lista «ADM-07 | Ausencias» de ClickUp (TAREA_pj_asignar_v2 B). Funciones puras, salvo leer YAML.

Una tarea = una persona y un tramo contiguo del mismo tipo. Cuenta solo en estado `aprobada`. Las horas son
8,8 h × días hábiles (4,4 h para medio día), calculadas desde las fechas: el Time Estimate es para Carga de trabajo.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import yaml

from dep_clickup.config import ROOT
from dep_clickup.models import Task

from .calendario import Calendario

CONFIG = ROOT / "config" / "ausencias.yaml"
PREFIJO_LISTA = "ADM-07"
APROBADA, RECHAZADA = "aprobada", "rechazada"
H_DIA = 8.8
MEDIO_DIA = "medio día administrativo"
TIPOS = ("vacaciones", "administrativo", MEDIO_DIA, "compensatorio", "licencia", "otro")
TAG_IMPORTADA = "importada"


def config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}


def lista_id() -> str:
    return str(config().get("lista_id") or "")


def es_lista_ausencias(nombre: str | None) -> bool:
    return (nombre or "").strip().startswith(PREFIJO_LISTA)


@dataclass(frozen=True)
class Tramo:
    persona: str
    tipo: str
    inicio: dt.date
    fin: dt.date

    @property
    def fraccion(self) -> float:
        return 0.5 if self.tipo == MEDIO_DIA else 1.0

    def dias(self, cal: Calendario) -> list[dt.date]:
        return list(cal.dias_habiles(self.inicio, self.fin))

    def horas(self, cal: Calendario) -> float:
        return round(H_DIA * self.fraccion * len(self.dias(cal)), 2)


def tramos_de_tareas(tareas: Iterable[Task], campo_tipo: str = "Tipo de ausencia") -> list[Tramo]:
    """Tareas aprobadas con alguna fecha; con varios responsables, un tramo por cada uno."""
    out = []
    for t in tareas:
        if (t.status or "").strip().lower() != APROBADA or not (t.start_date or t.due_date):
            continue
        cf = t.custom_fields.get(campo_tipo)
        tipo = cf.value if cf and cf.value in TIPOS else "otro"
        ini, fin = t.start_date or t.due_date, t.due_date or t.start_date
        out.extend(Tramo(p, tipo, ini, fin) for p in t.assignees)
    return out


def dias_por_persona(tramos: Iterable[Tramo], cal: Calendario) -> dict[str, dict[dt.date, tuple[str, float]]]:
    """Formato de informe_semanal_horas.core.Ausencias.dias: persona → día → (tipo, fracción ausente)."""
    out: dict[str, dict[dt.date, tuple[str, float]]] = defaultdict(dict)
    for t in tramos:
        for d in t.dias(cal):
            tipo = "administrativo" if t.tipo == MEDIO_DIA else t.tipo
            out[t.persona][d] = (tipo, t.fraccion)
    return dict(out)


def horas_por_semana(dias: Mapping[str, Mapping[dt.date, tuple[str, float]]]) -> dict[tuple[str, dt.date], float]:
    """(persona, lunes) → horas ausentes."""
    out: dict[tuple[str, dt.date], float] = defaultdict(float)
    for persona, por_dia in dias.items():
        for d, (_, fr) in por_dia.items():
            out[(persona, d - dt.timedelta(days=d.weekday()))] += H_DIA * fr
    return {k: round(v, 2) for k, v in out.items()}


def siguiente_habil(d: dt.date, cal: Calendario) -> dt.date:
    d += dt.timedelta(days=1)
    while not cal.es_habil(d):
        d += dt.timedelta(days=1)
    return d


def tramos_de_planilla(dias: Mapping[str, Mapping[dt.date, tuple[str, float]]], cal: Calendario) -> list[Tramo]:
    """De la planilla (persona → día → (tipo, fracción)) a tramos: días hábiles seguidos del mismo tipo y fracción."""
    out = []
    for persona, por_dia in dias.items():
        actual: Tramo | None = None
        for d in sorted(x for x in por_dia if cal.es_habil(x)):
            tipo, fr = por_dia[d]
            tipo = MEDIO_DIA if fr < 1 else tipo
            if actual and actual.tipo == tipo and siguiente_habil(actual.fin, cal) == d:
                actual = Tramo(persona, tipo, actual.inicio, d)
            else:
                if actual:
                    out.append(actual)
                actual = Tramo(persona, tipo, d, d)
        if actual:
            out.append(actual)
    return out


def conteo_por_persona(tramos: Sequence[Tramo], cal: Calendario) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"tramos": 0, "dias": 0.0, "horas": 0.0, "tipos": defaultdict(int)})
    for t in tramos:
        c = out[t.persona]
        c["tramos"] += 1
        c["dias"] += len(t.dias(cal)) * t.fraccion
        c["horas"] += t.horas(cal)
        c["tipos"][t.tipo] += 1
    return dict(out)
