"""Reproceso de cortes oficiales ya escritos: solo desde sus fotos_tareas y su linea base, nunca desde ClickUp en vivo.

Un corte oficial queda escrito con los datos del momento de su primera escritura. Volver a correrlo
(`python -m dep_reportes.run --tipo-corte oficial --corte <domingo>`) recalcula metricas_semanales y metricas_fase de
cada proyecto con:
- las tareas de fotos_tareas de ese corte (HH, fechas, avance, estado, padre y horas propias hasta el corte);
- la linea base vigente al momento de la ultima escritura del corte;
- de la fila guardada: el saldo historico (hh_historicas) y el termino con que se repartieron los pendientes
  (fecha_termino_usada).
Si algun proyecto necesita un dato que las fotos no tienen, el corte no se reescribe: queda con sus datos y se
registra en ejecuciones (resultado "reproceso_omitido", con el dato faltante). No se tocan fotos_tareas, proyectos,
advertencias, plan_semanal, serie_diaria (necesita horas por dia) ni cierres, ni las columnas que salen de datos en
vivo (presupuesto contractual, proyeccion por plan semanal, dias habiles para la entrega, extension del plazo).

Marca de reproceso: antes de esta regla un corte oficial se podia reescribir con ClickUp en vivo. Si un corte tiene
mas de una escritura con datos en vivo (modo "escritura"), sus numeros son de la ultima: metricas_semanales lleva
`reprocesado_en` = ese momento y ejecuciones una fila "reprocesado con datos de <fecha>" (una por corte). Ambas se
deducen del historial de ejecuciones en cada escritura. Funciones puras.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from . import esquema as E, linea_base as LB, presentacion as PR, proyecto as P
from .metricas import Horas, TareaMetrica
from .modos import Modo

ESCRITURA, REPROCESO, MARCA = "escritura", "reproceso_fotos", "marca"       # ejecuciones.modo
OK, OMITIDO, REPROCESADO = "ok", "reproceso_omitido", "reprocesado"         # ejecuciones.resultado
TOL_HORAS = 0.01
# Columnas de metricas_semanales que el reproceso recalcula (el resto se conserva de la fila escrita).
RECALCULADAS = [c for c, _ in E.METRICAS if c != "hh_estimadas_termino_plan_semanal"]


def _oficial(f: Mapping) -> bool:
    return (f.get("tipo_corte") or E.OFICIAL) == E.OFICIAL


def escrituras(corte: dt.date, ejecuciones: Sequence[Mapping]) -> list[dt.datetime]:
    """Momentos de las escrituras exitosas con datos en vivo de un corte oficial, en orden."""
    return sorted(e["ejecutado_en"] for e in ejecuciones
                  if e.get("corte") == corte and _oficial(e) and e.get("modo") == ESCRITURA
                  and e.get("resultado") == OK and e.get("ejecutado_en"))


def ya_escrito(corte: dt.date, ejecuciones: Sequence[Mapping]) -> bool:
    return bool(escrituras(corte, ejecuciones))


def reprocesado_en(corte: dt.date, ejecuciones: Sequence[Mapping]) -> dt.datetime | None:
    """Momento de los datos de un corte reescrito con ClickUp en vivo (mas de una escritura); None si no."""
    e = escrituras(corte, ejecuciones)
    return e[-1] if len(e) > 1 else None


def texto_marca(fecha: dt.datetime) -> str:
    return f"reprocesado con datos de {fecha:%Y-%m-%d %H:%M}"


def marcar(metricas: Sequence[dict], ejecuciones: Sequence[Mapping]) -> list[dict]:
    """reprocesado_en en todas las filas oficiales de metricas_semanales (las preliminares quedan vacias)."""
    cache: dict = {}
    out = []
    for f in metricas:
        f = dict(f)
        c = f.get("corte")
        if c not in cache:
            cache[c] = reprocesado_en(c, ejecuciones) if c else None
        f["reprocesado_en"] = cache[c] if _oficial(f) else None
        out.append(f)
    return out


def filas_marca(ejecuciones: Sequence[Mapping], ahora: dt.datetime) -> list[dict]:
    """Filas de ejecuciones que faltan: una por corte oficial reprocesado ("reprocesado con datos de <fecha>")."""
    hechas = {(e.get("corte"), e.get("detalle_error")) for e in ejecuciones if e.get("resultado") == REPROCESADO}
    out = []
    for c in sorted({e["corte"] for e in ejecuciones if e.get("corte") and _oficial(e)}):
        r = reprocesado_en(c, ejecuciones)
        if r and (c, texto_marca(r)) not in hechas:
            ultima = next(e for e in ejecuciones if e.get("corte") == c and e.get("ejecutado_en") == r)
            out.append({"ejecutado_en": ahora, "corte": c, "tipo_corte": E.OFICIAL, "modo": MARCA,
                        "n_proyectos": ultima.get("n_proyectos"), "resultado": REPROCESADO,
                        "detalle_error": texto_marca(r)})
    return out


# --- Recalculo desde fotos ---------------------------------------------------------------------------

class Falta(Exception):
    """El recalculo necesita un dato que las fotos (o la fila guardada) no tienen."""


def lb_del_corte(filas: Sequence[LB.FilaLB], list_id: str, hasta: dt.datetime | None) -> list[LB.FilaLB]:
    """Revision vigente de la lista con las filas capturadas hasta `hasta` (la ultima escritura del corte)."""
    propias = [f for f in filas if f.list_id == list_id and (hasta is None or _dt(f.fecha_captura) <= hasta)]
    v = LB.vigente(propias, list_id)
    return v[1] if v else []


def _dt(x) -> dt.datetime:
    return dt.datetime.fromisoformat(x) if isinstance(x, str) else x


def recalcular(corte: dt.date, fila: Mapping, fotos: Sequence[Mapping], lb_filas: Sequence[LB.FilaLB], modo: Modo,
               tipos_advertencia: Sequence[str] = (), proyeccion: str = "uniforme") -> tuple[dict, list[dict]]:
    """Fila nueva de metricas_semanales y filas de metricas_fase de una lista. Lanza Falta."""
    faltan = []
    if not fotos:
        faltan.append("fotos_tareas del corte")
    fin = fila.get("fecha_termino_usada")
    if fin is None:
        faltan.append("fecha de término con que se repartieron los pendientes (fecha_termino_usada)")
    if proyeccion == "plan_semanal":
        faltan.append("time estimates de las porciones (proyección por plan semanal)")
    hist = float(fila.get("hh_historicas") or 0.0)
    propias = sum(float(f.get("hh_gastadas_acum") or 0.0) for f in fotos)
    guardadas = fila.get("hh_gastadas_acum")
    if fotos and guardadas is not None and abs(hist + propias - guardadas) > TOL_HORAS:
        faltan.append(f"horas en tareas que no están en fotos_tareas ({hist + propias:.2f} h en las fotos y el saldo "
                      f"histórico, {guardadas:.2f} h en el corte)")
    if faltan:
        raise Falta("; ".join(faltan))

    tm = [TareaMetrica(f["task_id"], f.get("task_nombre") or "", f.get("parent_id") or None, f.get("start"),
                       f.get("due"), f.get("hh"), f.get("avance_real"), f.get("estado")) for f in fotos]
    # Las horas propias de cada tarea hasta el corte: fechadas en el corte (las metricas usan solo el acumulado).
    horas = [Horas(corte, float(f["hh_gastadas_acum"]), f["task_id"]) for f in fotos if f.get("hh_gastadas_acum")]
    lb_t, fase_lb = LB.a_tareas(lb_filas) if lb_filas else (None, {})
    res = P.calcular(lb_t, tm, horas, corte, fin, modo, fase_lb, hh_historicas=hist, entrega=fin)
    nueva = dict(fila)
    nueva.update({c: res.metricas.get(c) for c in RECALCULADAS})
    nueva["rev_linea_base"] = lb_filas[0].rev if lb_filas else None
    nueva["modo_calculo"] = modo.nombre
    motivo = None if lb_filas else PR.motivo_sin_linea_base(tipos_advertencia)
    nueva.update(PR.derivadas_semanales(nueva, motivo))
    ident = {k: fila.get(k) for k in ["corte", "tipo_corte", "list_id"] + [c for c, _ in E.IDENT]}
    return nueva, [{**ident, **f} for f in res.fases]


@dataclass
class Reproceso:
    corte: dt.date
    datos_de: dt.datetime | None                   # ultima escritura con datos en vivo del corte
    recalculadas: dict[str, tuple[dict, list[dict]]] = field(default_factory=dict)   # list_id -> (semanal, fases)
    faltas: dict[str, str] = field(default_factory=dict)                               # list_id -> dato faltante

    @property
    def omitido(self) -> bool:
        return bool(self.faltas) or not self.recalculadas

    def detalle(self, codigos: Mapping[str, str]) -> str:
        if not self.omitido:
            return ""
        base = f"el corte queda con datos de {self.datos_de:%Y-%m-%d %H:%M}" if self.datos_de else "el corte queda igual"
        grupos: dict[str, list[str]] = {}
        for lid, texto in self.faltas.items():
            grupos.setdefault(texto, []).append(codigos.get(lid) or lid)
        falta = "; ".join(f"{texto} en {len(cs)} proyecto{'s' if len(cs) > 1 else ''} ("
                          + ", ".join(sorted(cs)[:5]) + (", …" if len(cs) > 5 else "") + ")"
                          for texto, cs in sorted(grupos.items())) or "no hay proyectos del corte"
        return f"No se reescribió ({base}). Falta: {falta}"


def reprocesar(corte: dt.date, existentes: Mapping[str, Sequence[dict]], modo: Modo, solo: str | None = None,
               proyeccion: str = "uniforme") -> Reproceso:
    """Recalcula cada lista del corte oficial desde sus fotos y su linea base (todo o nada: ver Reproceso.omitido)."""
    ej = existentes.get("ejecuciones", [])
    datos_de = (escrituras(corte, ej) or [None])[-1]
    r = Reproceso(corte, datos_de)
    lb = [f if isinstance(f, LB.FilaLB) else LB.FilaLB(**f) for f in existentes.get("linea_base", [])]
    filas = [f for f in existentes.get("metricas_semanales", []) if f.get("corte") == corte and _oficial(f)
             and (solo is None or f.get("list_id") == solo)]
    for f in filas:
        lid = f["list_id"]
        fotos = [x for x in existentes.get("fotos_tareas", []) if x.get("corte") == corte and x.get("list_id") == lid]
        tipos = [a["tipo"] for a in existentes.get("advertencias", [])
                 if a.get("corte") == corte and _oficial(a) and a.get("list_id") == lid]
        try:
            r.recalculadas[lid] = recalcular(corte, f, fotos, lb_del_corte(lb, lid, datos_de), modo, tipos, proyeccion)
        except Falta as e:
            r.faltas[lid] = str(e)
    return r


def aplicar(r: Reproceso, metricas: Sequence[dict], fases: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """Contenido final de metricas_semanales y metricas_fase (sin cambios si el reproceso se omite)."""
    if r.omitido:
        return list(metricas), list(fases)
    es = lambda f: f.get("corte") == r.corte and _oficial(f) and f.get("list_id") in r.recalculadas
    sem = [r.recalculadas[f["list_id"]][0] if es(f) else f for f in metricas]
    fas = [f for f in fases if not es(f)] + [x for _, fs in r.recalculadas.values() for x in fs]
    return sem, fas
