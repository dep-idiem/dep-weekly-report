"""Controles de cordura: se corren despues de calcular y antes de escribir.

Si alguno falla no se escribe nada salvo la fila de `ejecuciones` con el fallo, y la corrida termina con
error para que GitHub notifique. Umbrales en config/controles.json.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from dep_clickup.config import ROOT

CONFIG = ROOT / "config" / "controles.json"


@dataclass(frozen=True)
class Umbrales:
    dias_ventana_horas: int = 7          # cero horas en todo el folder en estos dias -> error
    caida_max_proyectos: float = 0.20    # caida del numero de proyectos respecto de la ultima corrida exitosa
    tolerancia_total_hh: float = 1e-6


def cargar_umbrales(ruta: Path = CONFIG) -> Umbrales:
    if not ruta.exists():
        return Umbrales()
    return Umbrales(**json.loads(ruta.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class ProyectoControl:
    list_id: str
    codigo: str
    rev_vigente: int | None
    lb_existente_hh: float | None     # suma de HH de la revision vigente ya guardada en la hoja (None si es nueva)
    total_hh: float | None            # TotalHH calculado en esta corrida
    hh_prog_acum: float | None
    avance_prog: float | None
    hh_incrementales_nuevas: float = 0.0          # filas incrementales agregadas en esta corrida
    incrementales: tuple = ()                     # (fecha_captura, hh) de todas las filas incrementales vigentes


def verificar(corte: dt.date, fechas_horas: Sequence[dt.date], proyectos: Sequence[ProyectoControl],
              ejecuciones: Sequence[dict], metricas_previas: Sequence[dict], u: Umbrales,
              parcial: bool = False) -> list[str]:
    """Lista de fallos (vacia = se puede escribir).

    fechas_horas: fecha de cada entrada de tiempo del folder.
    ejecuciones / metricas_previas: filas actuales de esas pestañas.
    parcial: corrida con --solo (no se compara el numero de proyectos).
    """
    fallos: list[str] = []

    desde = corte - dt.timedelta(days=u.dias_ventana_horas - 1)
    if not any(desde <= f <= corte for f in fechas_horas):
        fallos.append(f"Cero entradas de tiempo en todo el folder entre {desde} y {corte} "
                      "(¿token de ClickUp sin permisos o vencido?)")

    if not parcial:
        previas = [e for e in ejecuciones if e.get("modo") == "escritura" and e.get("resultado") == "ok"
                   and e.get("n_proyectos")]
        if previas:
            ultima = max(previas, key=lambda e: e["ejecutado_en"])
            n0, n1 = ultima["n_proyectos"], len(proyectos)
            if n1 < n0 * (1 - u.caida_max_proyectos):
                fallos.append(f"El número de proyectos cae de {n0} a {n1} (más de {u.caida_max_proyectos:.0%}) "
                              f"respecto de la última corrida exitosa ({ultima['ejecutado_en']:%Y-%m-%d %H:%M})")

    for p in proyectos:
        if p.rev_vigente is None:
            continue
        if p.total_hh is None or p.hh_prog_acum is None or p.avance_prog is None:
            fallos.append(f"{p.codigo}: tiene línea base vigente (Rev. {p.rev_vigente}) pero quedó sin métricas")
        if p.lb_existente_hh is not None and p.total_hh is not None \
                and abs(p.total_hh - p.lb_existente_hh - p.hh_incrementales_nuevas) > u.tolerancia_total_hh:
            fallos.append(f"{p.codigo}: TotalHH {p.total_hh:g} distinto de la Rev. {p.rev_vigente} guardada "
                          f"({p.lb_existente_hh:g} + {p.hh_incrementales_nuevas:g} incrementales); la línea base es inmutable")
        previos = [m for m in metricas_previas if m.get("list_id") == p.list_id
                   and m.get("rev_linea_base") == p.rev_vigente and m.get("total_hh") is not None]
        if previos and p.total_hh is not None:
            ultimo = max(previos, key=lambda m: m["corte"])
            # Filas incrementales capturadas despues de la ultima escritura de ese corte explican la diferencia.
            escrito = [e["ejecutado_en"] for e in ejecuciones if e.get("corte") == ultimo["corte"]
                       and e.get("modo") == "escritura" and e.get("resultado") == "ok" and e.get("ejecutado_en")]
            t_pub = max(escrito) if escrito else None
            incr = sum(h for fc, h in p.incrementales if t_pub is None or fc > t_pub) + p.hh_incrementales_nuevas
            if abs(ultimo["total_hh"] - (p.total_hh - incr)) > u.tolerancia_total_hh:
                fallos.append(f"{p.codigo}: TotalHH {p.total_hh:g} distinto del publicado para la misma Rev. "
                              f"{p.rev_vigente} en el corte {ultimo['corte']} ({ultimo['total_hh']:g})")
    return fallos
