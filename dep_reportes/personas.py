"""Reglas de conteo por persona, para el dashboard confidencial (fase 5). Funciones puras.

NO se escriben en la hoja de reportes ni en ningun otro lado por ahora: `run.ejecutar` las calcula y las deja
en `Corrida.personas` (solo en memoria).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from dep_clickup.models import TimeEntry

TOPE_DIA_H = 9.25
MAX_ENTRADA_H = 10.0


@dataclass(frozen=True)
class DiaSobreTope:
    usuario_id: int
    fecha: dt.date
    horas: float
    exceso: float


@dataclass(frozen=True)
class Superposicion:
    usuario_id: int
    entrada_a: str
    entrada_b: str
    horas: float


@dataclass(frozen=True)
class EntradaLarga:
    usuario_id: int
    entrada: str
    fecha: dt.date
    horas: float


@dataclass
class ReglasPersonas:
    dias_sobre_tope: list[DiaSobreTope]
    superposiciones: list[Superposicion]
    entradas_largas: list[EntradaLarga]


def dias_sobre_tope(entradas: Sequence[TimeEntry], tope: float = TOPE_DIA_H) -> list[DiaSobreTope]:
    por_dia: dict[tuple[int, dt.date], float] = defaultdict(float)
    for e in entradas:
        por_dia[(e.user_id, e.date)] += e.hours
    return [DiaSobreTope(u, d, h, h - tope) for (u, d), h in sorted(por_dia.items()) if h > tope + 1e-9]


def superposiciones(entradas: Sequence[TimeEntry], minimo_h: float = 1 / 60) -> list[Superposicion]:
    """Pares de entradas de la misma persona que se pisan en el tiempo (mas de un minuto)."""
    por_persona: dict[int, list[TimeEntry]] = defaultdict(list)
    for e in entradas:
        por_persona[e.user_id].append(e)
    out = []
    for uid, xs in por_persona.items():
        xs.sort(key=lambda e: e.start)
        for i, a in enumerate(xs):
            fin_a = a.end or a.start
            for b in xs[i + 1:]:
                if b.start >= fin_a:
                    break
                h = (min(fin_a, b.end or b.start) - b.start).total_seconds() / 3600
                if h > minimo_h:
                    out.append(Superposicion(uid, a.id, b.id, h))
    return out


def entradas_largas(entradas: Sequence[TimeEntry], maximo: float = MAX_ENTRADA_H) -> list[EntradaLarga]:
    return [EntradaLarga(e.user_id, e.id, e.date, e.hours) for e in entradas if e.hours > maximo]


def calcular(entradas: Sequence[TimeEntry]) -> ReglasPersonas:
    return ReglasPersonas(dias_sobre_tope(entradas), superposiciones(entradas), entradas_largas(entradas))
