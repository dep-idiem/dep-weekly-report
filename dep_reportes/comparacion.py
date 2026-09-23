"""Validacion 4b: datos de ClickUp en vivo contra el Excel (foto del dia del export).

Clasificacion de cada diferencia:
- "cambio posterior al export": el insumo (HH, fechas, avance, entradas de tiempo) no es el mismo que
  tenia el Excel. Es legitimo.
- "diferencia de logica": el insumo es identico pero el resultado por tarea (reparto diario programado,
  avance programado, avance real, reparto de pendientes) no coincide con las celdas del Excel, o una
  entrada de tiempo identica cae en otra fecha u otras horas tras la conversion. Debe ser cero.
- "revisar": diferencia de insumo sin evidencia de que sea posterior al export.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from dep_clickup.models import TimeEntry

from .calendario import SIN_FERIADOS, Calendario
from .fixture_excel import EntradaExcel, FixtureCurvaS
from .metricas import (TareaMetrica, fraccion_programada, hh_pendientes_tarea, hh_programadas_tarea)

POSTERIOR = "cambio posterior al export"
LOGICA = "diferencia de logica"
REVISAR = "revisar"

TOL = 1e-6


@dataclass(frozen=True)
class DifTarea:
    tarea_id: str
    tarea: str
    hoja: str            # "Programado" | "Avance" | "-"
    campo: str
    excel: str
    clickup: str
    clase: str


@dataclass(frozen=True)
class DifEntrada:
    tipo: str            # "faltante en ClickUp" | "sobrante en ClickUp" | "fecha/horas distintas"
    user_id: int
    tarea: str
    fecha: dt.date
    horas: float
    detalle: str
    clase: str


@dataclass
class Resultado4b:
    tareas: list[DifTarea] = field(default_factory=list)
    entradas: list[DifEntrada] = field(default_factory=list)
    entradas_coinciden: int = 0
    tareas_logica_verificadas: int = 0

    @property
    def n_logica(self) -> int:
        return sum(d.clase == LOGICA for d in self.tareas) + sum(d.clase == LOGICA for d in self.entradas)


def _fmt(v) -> str:
    if v is None:
        return "(vacio)"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _igual(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= TOL
    return a == b


def _dist_igual(a: dict, b: dict, tol: float = 1e-6) -> bool:
    return all(abs(a.get(k, 0.0) - b.get(k, 0.0)) <= tol for k in set(a) | set(b))


def _recortar(d: dict[dt.date, float], fx: FixtureCurvaS) -> dict[dt.date, float]:
    """El Excel solo tiene columnas entre la primera y la ultima fecha de su grilla diaria."""
    fechas = [k for k in fx.prog_acumulado if k]
    lo, hi = min(fechas), max(fechas)
    return {k: v for k, v in d.items() if lo <= k <= hi}


def comparar_tareas(fx: FixtureCurvaS, vivo: Sequence[TareaMetrica], cal: Calendario = SIN_FERIADOS) -> Resultado4b:
    res = Resultado4b()
    vivo_id = {t.id: t for t in vivo}
    for hoja, excel, campos in (
        ("Programado", fx.programa, ("hh", "start", "due")),
        ("Avance", fx.avance, ("hh", "start", "due", "avance")),
    ):
        ex_id = {t.id: t for t in excel}
        for tid in sorted(set(ex_id) | set(vivo_id), key=lambda x: (ex_id.get(x) or vivo_id[x]).nombre):
            e, v = ex_id.get(tid), vivo_id.get(tid)
            if e is None or v is None:
                t = e or v
                if t.hh:  # solo importa si la tarea entra al universo
                    res.tareas.append(DifTarea(tid, t.nombre, hoja, "tarea",
                                               "existe" if e else "no existe", "existe" if v else "no existe",
                                               POSTERIOR))
                continue
            difs = [c for c in campos if not _igual(getattr(e, c), getattr(v, c))]
            for c in difs:
                res.tareas.append(DifTarea(tid, e.nombre, hoja, c, _fmt(getattr(e, c)), _fmt(getattr(v, c)), POSTERIOR))
            if difs or not v.hh:
                continue
            # Insumo identico: el resultado por tarea debe calzar con las celdas del Excel.
            res.tareas_logica_verificadas += 1
            if hoja == "Programado":
                nuestro = _recortar(hh_programadas_tarea(v, cal), fx)
                if not _dist_igual(nuestro, fx.prog_diario_tarea.get(tid, {})):
                    res.tareas.append(DifTarea(tid, e.nombre, hoja, "reparto diario programado",
                                               f"{sum(fx.prog_diario_tarea.get(tid, {}).values()):g}",
                                               f"{sum(nuestro.values()):g}", LOGICA))
                n = v.hh * fraccion_programada(v, fx.control, cal) / fx.total_hh
                if tid in fx.fraccion_prog_tarea and abs(n - fx.fraccion_prog_tarea[tid]) > 1e-9:
                    res.tareas.append(DifTarea(tid, e.nombre, hoja, "avance programado ponderado",
                                               f"{fx.fraccion_prog_tarea[tid]:.6f}", f"{n:.6f}", LOGICA))
            else:
                nuestro = _recortar(hh_pendientes_tarea(v, fx.control, fx.fin, cal), fx)
                if not _dist_igual(nuestro, fx.pend_diario_tarea.get(tid, {})):
                    res.tareas.append(DifTarea(tid, e.nombre, hoja, "reparto diario de pendientes",
                                               f"{sum(fx.pend_diario_tarea.get(tid, {}).values()):g}",
                                               f"{sum(nuestro.values()):g}", LOGICA))
                u = (v.avance or 0.0) * v.hh / fx.total_hh_avance
                if tid in fx.avance_real_tarea and abs(u - fx.avance_real_tarea[tid]) > 1e-9:
                    res.tareas.append(DifTarea(tid, e.nombre, hoja, "avance real ponderado",
                                               f"{fx.avance_real_tarea[tid]:.6f}", f"{u:.6f}", LOGICA))
    return res


def _ms(t: dt.datetime) -> int:
    return round(t.timestamp() * 1000)


def comparar_entradas(res: Resultado4b, excel: Iterable[EntradaExcel], vivo: Iterable[TimeEntry],
                      export: dt.datetime) -> None:
    """Cruce por (usuario, start en ms, tarea) y luego por (usuario, start en ms).

    El Time Entry ID del Excel perdio precision (se guardo como float), y una persona puede tener dos
    entradas con el mismo start en tareas distintas.
    """
    ex = list(excel)
    vv = list(vivo)
    pares: list[tuple[EntradaExcel, TimeEntry]] = []
    for clave_ex, clave_vv in ((lambda e: (e.user_id, e.start_ms, e.tarea_id), lambda v: (v.user_id, _ms(v.start), v.task_id)),
                               (lambda e: (e.user_id, e.start_ms), lambda v: (v.user_id, _ms(v.start)))):
        libres: dict = {}
        for v in vv:
            libres.setdefault(clave_vv(v), []).append(v)
        resto = []
        for e in ex:
            cand = libres.get(clave_ex(e))
            if cand:
                v = cand.pop(0)
                pares.append((e, v))
                vv.remove(v)
            else:
                resto.append(e)
        ex = resto

    for e, v in sorted(pares, key=lambda p: p[0].start_ms):
        if e.tarea_id != v.task_id:
            res.entradas.append(DifEntrada("movida de tarea", v.user_id, v.task_name, v.date, v.hours,
                                           f"Excel en {e.tarea}", POSTERIOR))
        elif e.duration_ms != v.duration_ms:
            res.entradas.append(DifEntrada("duracion editada", v.user_id, v.task_name, v.date, v.hours,
                                           f"Excel {e.horas_excel:g} h, ClickUp {v.hours:g} h", POSTERIOR))
        elif e.fecha_excel != v.date or abs(e.horas_excel - v.hours) > 1e-6:
            res.entradas.append(DifEntrada("fecha/horas distintas", v.user_id, v.task_name, v.date, v.hours,
                                           f"Excel {e.fecha_excel} {e.horas_excel:g} h", LOGICA))
        else:
            res.entradas_coinciden += 1
    for e in ex:
        res.entradas.append(DifEntrada("faltante en ClickUp", e.user_id, e.tarea, e.fecha, e.horas,
                                       "borrada o con start editado despues del export", POSTERIOR))
    for v in sorted(vv, key=lambda v: v.start):
        if v.updated and v.updated > export:
            det, clase = f"creada/editada {v.updated:%Y-%m-%d %H:%M} (despues del export)", POSTERIOR
        elif v.start > export:
            det, clase = "start posterior al export", POSTERIOR
        else:
            det = f"ultima edicion {v.updated:%Y-%m-%d %H:%M}" if v.updated else "sin fecha de edicion"
            clase = REVISAR
        res.entradas.append(DifEntrada("sobrante en ClickUp", v.user_id, v.task_name, v.date, v.hours, det, clase))


# --- Validacion 4a: logica contra el Excel ------------------------------------------------------

@dataclass(frozen=True)
class Chequeo:
    nombre: str
    esperado: float | None
    obtenido: float | None
    tol: float

    @property
    def ok(self) -> bool:
        if self.esperado is None or self.obtenido is None:
            return self.esperado is None and self.obtenido is None
        return abs(self.esperado - self.obtenido) <= self.tol


def validar_4a(fx: FixtureCurvaS, cal: Calendario = SIN_FERIADOS) -> list[Chequeo]:
    """Corre metricas.py sobre los insumos del Excel y compara con los resultados del Excel."""
    from . import metricas as m

    C, fin = fx.control, fx.fin
    out = [
        Chequeo("TotalHH (Programado!M2)", fx.total_hh, m.total_hh(fx.programa), 1e-9),
        Chequeo("Avance programado (Programado!N2)", fx.avance_programado, m.avance_programado(fx.programa, C, cal), 1e-4),
        Chequeo("Avance real (Avance!U2)", fx.avance_real, m.avance_real(fx.avance), 1e-4),
        Chequeo("HH pendientes (Avance!D2)", fx.hh_pendientes, m.hh_pendientes_total(fx.avance), 0.01),
    ]
    serie = m.serie_resumen(fx.grilla, fx.programa, fx.avance, fx.horas, C, fin, cal)
    for fila, (a, b) in enumerate(zip(serie, fx.serie), start=54):
        out += [
            Chequeo(f"Resumen!E{fila} programadas {a.fecha}", b.programadas, a.programadas, 0.01),
            Chequeo(f"Resumen!F{fila} gastadas {a.fecha}", b.gastadas, a.gastadas, 0.01),
            Chequeo(f"Resumen!G{fila} proyectadas {a.fecha}", b.proyectadas, a.proyectadas, 0.01),
        ]
    # Celdas por tarea y por dia
    for t in fx.programa:
        nuestro = _recortar(hh_programadas_tarea(t, cal), fx)
        ex = fx.prog_diario_tarea.get(t.id, {})
        for d in sorted(set(nuestro) | set(ex)):
            if abs(nuestro.get(d, 0.0) - ex.get(d, 0.0)) > 1e-9:
                out.append(Chequeo(f"Programado {t.nombre} {d}", ex.get(d, 0.0), nuestro.get(d, 0.0), 1e-9))
        if t.id in fx.fraccion_prog_tarea:
            n = (t.hh or 0.0) * fraccion_programada(t, C, cal) / fx.total_hh
            if abs(n - fx.fraccion_prog_tarea[t.id]) > 1e-12:
                out.append(Chequeo(f"Programado!N {t.nombre}", fx.fraccion_prog_tarea[t.id], n, 1e-12))
    for t in fx.avance:
        nuestro = _recortar(hh_pendientes_tarea(t, C, fin, cal), fx)
        ex = fx.pend_diario_tarea.get(t.id, {})
        for d in sorted(set(nuestro) | set(ex)):
            if abs(nuestro.get(d, 0.0) - ex.get(d, 0.0)) > 1e-9:
                out.append(Chequeo(f"Avance {t.nombre} {d}", ex.get(d, 0.0), nuestro.get(d, 0.0), 1e-9))
    prog = m.hh_programadas_diarias(fx.programa, cal)
    pend = m.hh_pendientes_diarias(fx.avance, C, fin, cal)
    for d, v in fx.prog_acumulado.items():
        out.append(Chequeo(f"Programado!fila208 {d}", v, m.acumulado_a(prog, d), 1e-6))
    for d, v in fx.pend_acumulado.items():
        out.append(Chequeo(f"Avance!fila208 {d}", v, m.acumulado_a(pend, d), 1e-6))
    return out
