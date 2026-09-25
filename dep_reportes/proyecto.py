"""Metricas de un proyecto para un corte, en modo `legado` (Excel) o `dep`. Funciones puras.

- El programado sale siempre de la linea base (`lb`); nunca de las fechas actuales de ClickUp.
- Avance real, HH gastadas y proyeccion salen de las tareas y horas actuales.
"""
from __future__ import annotations

import datetime as dt
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import accumulate
from typing import Mapping, Sequence

from . import metricas as m
from .calendario import Calendario
from .metricas import Horas, TareaMetrica
from .modos import Modo

NO_APLICA = "no aplica"
SIN_FASE = "(sin fase)"

# Tipos de advertencia de esta fase (las del detector de la fase 1 estan en calidad.py)
ADV_SIN_JP = "sin_jp"
ADV_EN_PLANIFICACION = "en_planificacion"
ADV_SIN_TAREA_12 = "sin_tarea_1_2"
ADV_TAREA_12_NO_APLICA = "tarea_1_2_no_aplica"
ADV_VARIAS_TAREAS_12 = "varias_tareas_1_2"
ADV_TERMINO_VENCIDO = "proyecto_con_termino_vencido"
ADV_SIN_TERMINO = "sin_termino_vigente"
ADV_NO_APLICA_CON_HH = "no_aplica_con_hh"
ADV_HH_CAMBIARON = "hh_cambiaron_vs_linea_base"
ADV_LB_TAREA_NO_APLICA = "tarea_de_linea_base_ahora_no_aplica"
ADV_LB_TARDIA = "linea_base_tardia"
ADV_LB_SIN_HH = "linea_base_sin_hh"
ADV_CODIGO_DUPLICADO = "codigo_duplicado_en_clickup"
ADV_NOMBRE_SIN_FORMATO = "nombre_lista_sin_formato"
# Reglas de conteo de horas (horas.py)
ADV_HORAS_EN_PADRE = "horas_en_tarea_padre"
ADV_HORAS_ADMIN = "horas_en_administracion"
ADV_FUERA_DE_PLAZO = "horas_fuera_de_plazo"
ADV_FASE_OTRO_PROYECTO = "fase_de_otro_proyecto"
ADV_TT_SIN_CLICKUP = "horas_timetracker_sin_clickup"
ADV_LISTA_COMBINADA = "lista_combinada"
# Fase 2b: porciones, presupuesto contractual y plan semanal
ADV_PORCION_CON_HH = "porcion_con_hh"
ADV_SIN_PRESUPUESTO = "sin_presupuesto_contractual"
ADV_PRESUPUESTO_POR_AGOTARSE = "presupuesto_por_agotarse"
ADV_CUMPLIMIENTO = "cumplimiento_semanal_fuera_de_rango"
ADV_PAQUETE_DESAPARECIDO = "paquete_desaparecido"
ADV_FASE_CON_HH = "fase_con_hh"

# Advertencias de nivel proyecto: se escriben siempre en la hoja (decision 2 de la fase 2). Las demas solo
# si son de una tarea con HH Presupuestadas; el detalle completo queda en calidad_datos.md.
NIVEL_PROYECTO = {
    ADV_SIN_JP, ADV_EN_PLANIFICACION, ADV_SIN_TAREA_12, ADV_TAREA_12_NO_APLICA, ADV_VARIAS_TAREAS_12,
    ADV_TERMINO_VENCIDO, ADV_SIN_TERMINO, ADV_HH_CAMBIARON, ADV_LB_SIN_HH, ADV_LB_TARDIA, ADV_CODIGO_DUPLICADO,
    ADV_NOMBRE_SIN_FORMATO, ADV_HORAS_ADMIN, ADV_FUERA_DE_PLAZO, ADV_FASE_OTRO_PROYECTO, ADV_TT_SIN_CLICKUP,
    ADV_LISTA_COMBINADA, ADV_SIN_PRESUPUESTO, ADV_PRESUPUESTO_POR_AGOTARSE, ADV_CUMPLIMIENTO, ADV_PAQUETE_DESAPARECIDO,
    "hh_en_padre_y_subtarea",   # doble conteo (calidad.DOBLE_CONTEO)
}
# De nivel tarea, pero se escriben aunque la tarea no tenga HH Presupuestadas.
SIEMPRE_EN_HOJA = NIVEL_PROYECTO | {ADV_HORAS_EN_PADRE}
# Solo en calidad_datos.md, nunca en la hoja: HH Presupuestadas distintas del time estimate (o sin el).
SOLO_CALIDAD = {"hh_distinta_de_time_estimate"}


def para_hoja(advertencias: Sequence[dict], tareas_con_hh: set[str]) -> list[dict]:
    """Advertencias que van a la hoja que ven los JP."""
    return [a for a in advertencias if a["tipo"] not in SOLO_CALIDAD
            and (a["tipo"] in SIEMPRE_EN_HOJA or a.get("task_id") in tareas_con_hh)]


@dataclass(frozen=True)
class Aviso:
    tipo: str
    task_id: str
    detalle: str
    datos: dict = field(default_factory=dict, compare=False)   # para el mensaje en español (presentacion.py)


@dataclass
class ResultadoProyecto:
    metricas: dict
    fases: list[dict]
    serie: list[m.PuntoSerie]
    avisos: list[Aviso] = field(default_factory=list)


def es_no_aplica(t: TareaMetrica) -> bool:
    return (t.estado or "").strip().lower() == NO_APLICA


def fases_por_tarea(tareas: Sequence[TareaMetrica]) -> dict[str, str]:
    """task_id -> nombre del ancestro de primer nivel."""
    padres = {t.id: t.parent for t in tareas}
    nombres = {t.id: t.nombre for t in tareas}
    return {t.id: nombres.get(m.fase_de(t.id, padres), SIN_FASE) for t in tareas}


def primer_habil_despues(d: dt.date, cal: Calendario) -> dt.date:
    x = d + dt.timedelta(days=1)
    while not cal.es_habil(x):
        x += dt.timedelta(days=1)
    return x


def pendientes_tarea(t: TareaMetrica, control: dt.date, fin: dt.date, modo: Modo) -> dict[dt.date, float]:
    """Reparto de (1 - avance) * HH. En modo dep: si el termino ya paso (fin <= C) o el rango no tiene
    dias habiles, las HH pendientes van al primer dia habil despues de C (o del inicio del rango)."""
    if not modo.vencido_primer_habil:
        return m.hh_pendientes_tarea(t, control, fin, modo.cal)
    if not t.hh or (t.avance or 0.0) >= 1:
        return {}
    pend = (1 - (t.avance or 0.0)) * t.hh
    s, d = m._fecha(t.start), m._fecha(t.due)
    if s < control:
        if d < control:
            if fin <= control:
                return {primer_habil_despues(control, modo.cal): pend}
            a, b = control + dt.timedelta(days=1), fin
        else:
            a, b = control, d
    else:
        a, b = s, d
    n = modo.cal.networkdays(a, b)
    if n <= 0:
        return {primer_habil_despues(max(a, control + dt.timedelta(days=1)) - dt.timedelta(days=1), modo.cal): pend}
    return {x: pend / n for x in modo.cal.dias_habiles(a, b)}


class _Acum:
    """Acumulado de una serie diaria con busqueda O(log n)."""
    def __init__(self, diario: Mapping[dt.date, float]):
        self.dias = sorted(diario)
        self.acum = list(accumulate(diario[d] for d in self.dias))

    def hasta(self, d: dt.date, inclusive: bool = True) -> float:
        i = bisect_right(self.dias, d) if inclusive else bisect_right(self.dias, d - dt.timedelta(days=1))
        return self.acum[i - 1] if i else 0.0


def calcular(lb: Sequence[TareaMetrica] | None, actuales: Sequence[TareaMetrica], horas: Sequence[Horas],
             control: dt.date, fin: dt.date | None, modo: Modo,
             fase_lb: Mapping[str, str] | None = None, hh_historicas: float = 0.0,
             desde_historico: dt.date | None = None,
             pendientes_plan: Mapping[str, Mapping[dt.date, float]] | None = None) -> ResultadoProyecto:
    """Metricas de un proyecto al corte `control`.

    lb: tareas de la linea base vigente (None = sin linea base: no hay programado).
    fase_lb: task_id -> fase guardada en la linea base (si falta, se usa la fase actual de ClickUp).
    hh_historicas: saldo del Timetracker antes del corte historico (horas.py). Se suma a las HH gastadas de
        metricas_semanales, a CPI y a las HH estimadas al termino. En la serie diaria, las gastadas parten del saldo
        en `desde_historico` (antes quedan vacias) y la proyeccion lo incluye, para que la curva termine en el valor
        de metricas_semanales. Las fases usan solo `horas`.
    desde_historico: fecha del corte historico (si es posterior al corte, la serie parte en el corte).
    pendientes_plan: proyeccion por plan semanal (plan_semanal.py): paquete -> HH por dia de sus porciones futuras.
        Esos paquetes usan ese reparto en vez del uniforme; los demas, el uniforme.
    """
    cal = modo.cal
    avisos: list[Aviso] = []
    fase_act = fases_por_tarea(actuales)
    fase_lb = dict(fase_lb or {})
    for t in lb or []:
        fase_lb.setdefault(t.id, fase_act.get(t.id, SIN_FASE))

    # Universo actual
    no_aplica = [t for t in m.universo(actuales) if es_no_aplica(t)]
    for t in no_aplica:
        avisos.append(Aviso(ADV_NO_APLICA_CON_HH, t.id, f"\"{t.nombre}\" está en No Aplica con HH={t.hh:g}"
                            + (" (excluida del universo)" if modo.excluir_no_aplica else ""), {"hh": t.hh}))
    ids_na = {t.id for t in no_aplica}
    actual_u = [t for t in m.universo(actuales) if not (modo.excluir_no_aplica and t.id in ids_na)]
    lb_u = m.universo(lb or [])

    # Fecha de termino
    sin_fecha = False
    if fin is None:
        dues = [t.due for t in (lb_u or actual_u) if t.due]
        sin_fecha = not dues
        fin = max(dues) if dues else control
        avisos.append(Aviso(ADV_SIN_TERMINO, "", "La lista no tiene fecha de vencimiento; "
                            + (f"se usa el due más tardío de las tareas con HH ({fin})" if dues else
                               "tampoco hay tareas con HH y fechas"), {"fin": fin if dues else None}))
    if fin <= control and not sin_fecha:
        avisos.append(Aviso(ADV_TERMINO_VENCIDO, "", f"Término vigente {fin} ≤ corte {control}"
                            + ("; pendientes atrasadas al primer día hábil después del corte" if modo.vencido_primer_habil else ""),
                            {"fin": fin}))

    # Programado (linea base)
    total = m.total_hh(lb_u) if lb is not None else None
    prog_diario = m.hh_programadas_diarias(lb_u, cal)
    prog = _Acum(prog_diario)
    hh_prog_acum = prog.hasta(control) if lb is not None else None
    avance_prog = m.avance_programado(lb_u, control, cal) if total else None
    if lb is not None:
        for t in lb_u:
            if t.id in ids_na:
                avisos.append(Aviso(ADV_LB_TAREA_NO_APLICA, t.id, f"\"{t.nombre}\" (HH={t.hh:g} en la línea base) está hoy en No Aplica", {"hh": t.hh}))

    # Real
    tot_act = m.total_hh(actual_u)
    avance_real = m.avance_real(actual_u) if tot_act else None
    horas_ord = _Acum(_por_dia(horas))
    inclusivo = modo.base_en_control
    gastadas = horas_ord.hasta(control, inclusive=inclusivo)
    if lb is not None:
        # Paquete a paquete: solo si cambio la HH de uno ya congelado. Las tareas nuevas no la disparan
        # (los paquetes nuevos se congelan como filas incrementales, linea_base.incrementales).
        hh_act = {t.id: m._hh(t) for t in actuales}
        cambiados = [t for t in lb_u if t.id in hh_act and t.id not in ids_na and abs(hh_act[t.id] - (t.hh or 0)) > 1e-6]
        if cambiados:
            a_, b_ = sum(hh_act[t.id] for t in cambiados), sum(t.hh or 0 for t in cambiados)
            avisos.append(Aviso(ADV_HH_CAMBIARON, "", f"{len(cambiados)} paquete(s) congelado(s) con otra HH: {a_:g} en "
                                                      f"ClickUp vs {b_:g} en la línea base ("
                                                      + ", ".join(t.nombre for t in cambiados[:5]) + ")",
                                {"n": len(cambiados), "actual": a_, "linea_base": b_}))

    # Proyeccion
    pend_diario: dict[dt.date, float] = defaultdict(float)
    for t in actual_u:
        if pendientes_plan and t.id in pendientes_plan:
            reparto = {d: v for d, v in pendientes_plan[t.id].items() if d > control}
        else:
            reparto = pendientes_tarea(t, control, fin, modo)
        for d, v in reparto.items():
            pend_diario[d] += v
    pend = _Acum(pend_diario)
    if modo.base_en_control:
        base = gastadas
    else:
        starts = [t.start for t in (lb_u or actual_u) if t.start]
        g0 = (min(starts) if starts else control) - dt.timedelta(days=1)
        ultimo = g0 + dt.timedelta(days=((control - g0).days // modo.paso_grilla_legado) * modo.paso_grilla_legado)
        base = horas_ord.hasta(ultimo, inclusive=False)
    estimadas = hh_historicas + base + sum(pend_diario.values())
    gastadas_total = hh_historicas + gastadas

    ev = avance_real * total if (avance_real is not None and total) else None
    metricas = {
        "total_hh": total,
        "hh_prog_acum": hh_prog_acum,
        "hh_gastadas_acum": gastadas_total,
        "hh_historicas": hh_historicas,
        "avance_prog": avance_prog,
        "avance_real": avance_real,
        "ev": ev,
        "spi": ev / hh_prog_acum if (ev is not None and hh_prog_acum) else None,
        "cpi": ev / gastadas_total if (ev is not None and gastadas_total) else None,
        "hh_estimadas_al_termino": estimadas,
        "hh_actuales_clickup": tot_act,
        "fecha_termino_usada": fin,
    }

    # Serie diaria
    candidatos = [t.start for t in lb_u + actual_u if t.start] + [h.fecha for h in horas]
    d0 = min(candidatos) if candidatos else control
    d1 = max([fin, control] + [t.due for t in lb_u if t.due] + list(pend_diario))
    serie = []
    d = d0
    parte = min(desde_historico, control) if (hh_historicas and desde_historico) else None
    while d <= d1:
        g = horas_ord.hasta(d, inclusive=inclusivo) if d <= control else None
        if g is not None and hh_historicas:
            g = hh_historicas + g if (parte is None or d >= parte) else None
        p = hh_historicas + base + pend.hasta(d) if d >= control else None
        serie.append(m.PuntoSerie(d, prog.hasta(d) if lb is not None else 0.0, g, p))
        d += dt.timedelta(days=1)

    # Fases
    hh_lb_f: dict[str, float] = defaultdict(float)
    prog_f: dict[str, float] = defaultdict(float)
    for t in lb_u:
        f = fase_lb.get(t.id, SIN_FASE)
        hh_lb_f[f] += t.hh or 0.0
        prog_f[f] += sum(v for x, v in m.hh_programadas_tarea(t, cal).items() if x <= control)
    gast_f: dict[str, float] = defaultdict(float)
    for h in horas:
        if h.fecha < control or (inclusivo and h.fecha == control):
            gast_f[fase_act.get(h.tarea_id, SIN_FASE)] += h.horas
    num_f: dict[str, float] = defaultdict(float)
    den_f: dict[str, float] = defaultdict(float)
    for t in actual_u:
        f = fase_act.get(t.id, SIN_FASE)
        num_f[f] += (t.avance or 0.0) * (t.hh or 0.0)
        den_f[f] += t.hh or 0.0
    fases = []
    for f in sorted(set(hh_lb_f) | set(gast_f) | set(den_f)):
        fases.append({
            "fase": f,
            "hh_linea_base": hh_lb_f.get(f, 0.0) if lb is not None else None,
            "hh_prog_acum": prog_f.get(f, 0.0) if lb is not None else None,
            "hh_gastadas_acum": gast_f.get(f, 0.0),
            "avance_real": num_f[f] / den_f[f] if den_f.get(f) else None,
        })
    return ResultadoProyecto(metricas, fases, serie, avisos)


def _por_dia(horas: Sequence[Horas]) -> dict[dt.date, float]:
    out: dict[dt.date, float] = defaultdict(float)
    for h in horas:
        out[h.fecha] += h.horas
    return out
