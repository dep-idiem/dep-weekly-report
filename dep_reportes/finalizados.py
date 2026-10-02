"""Proyectos finalizados: listas del folder "Proyectos Finalizados" (espacio Proyectos Activos). Funciones puras.

Al terminar un proyecto su lista se mueve de PJ Ingenieria a Proyectos Finalizados. La lista conserva list_id,
codigo y linea base; en la hoja queda con estado_proyecto = "finalizado" (en todas sus filas, tambien las
antiguas, para que Looker la saque de las tablas de proyectos en curso con un filtro).

Situacion de una lista del folder de finalizados en un corte:
- cambio_de_folder: la lista estuvo en curso en un corte anterior (tiene filas semanales en curso). En este corte
  se emiten sus filas semanales normales (la semana en que se movio), la advertencia informativa
  "proyecto_finalizado" y la fila de `cierres`.
- incorporado_finalizado: se ve por primera vez y ya esta finalizada (nunca se observo en curso). No se inventan
  semanas que no se observaron: solo la fila de proyectos, la de cierres y la advertencia.
- congelado: la fila de cierres es de un corte anterior. Se recalcula con el corte de cierre (la serie diaria y la
  fila de proyectos quedan iguales) y no se emiten filas semanales nuevas.
Las filas de cierres solo se escriben en corridas oficiales; si la lista vuelve a PJ Ingenieria, su cierre se borra.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Collection, Mapping, Sequence

from .calendario import Calendario

EN_CURSO, FINALIZADO = "en_curso", "finalizado"
FUERA_DE_FOLDERS = "fuera_de_folders"      # filas antiguas de listas que ya no estan en ninguno de los dos folders
CAMBIO, INCORPORADO = "cambio_de_folder", "incorporado_finalizado"


@dataclass(frozen=True)
class Situacion:
    estado: str = EN_CURSO
    tipo_cierre: str | None = None          # CAMBIO o INCORPORADO
    corte_cierre: dt.date | None = None     # corte en que se registro el cierre
    congelado: bool = False                 # cierre de un corte anterior: se calcula con corte_cierre
    emite_semanales: bool = True            # metricas_semanales, metricas_fase, fotos_tareas, plan_semanal, advertencias
    nuevo_cierre: bool = False              # se escribe (o reescribe) la fila de cierres en esta corrida
    ultimo_corte_en_curso: dt.date | None = None

    @property
    def finalizado(self) -> bool:
        return self.estado == FINALIZADO

    @property
    def avisar(self) -> bool:
        """Advertencia "proyecto_finalizado": en el corte en que se detecta, no despues."""
        return self.finalizado and not self.congelado


def situacion(list_id: str, en_finalizados: bool, corte: dt.date, oficial: bool,
              cierres: Mapping[str, dict], cortes_en_curso: Collection[dt.date]) -> Situacion:
    """cierres: list_id -> fila de la pestaña cierres; cortes_en_curso: cortes con filas semanales de la lista en
    curso (estado_proyecto vacio o en_curso), de corridas anteriores."""
    if not en_finalizados:
        return Situacion()
    c = cierres.get(list_id)
    if c is not None and c.get("corte_cierre") is not None and c["corte_cierre"] < corte:
        return Situacion(FINALIZADO, c.get("tipo_cierre"), c["corte_cierre"], congelado=True, emite_semanales=False,
                         ultimo_corte_en_curso=c.get("ultimo_corte_en_curso"))
    if c is not None and c.get("corte_cierre") is not None and c["corte_cierre"] > corte:
        # Reproceso de un corte anterior al cierre registrado: se respeta el cierre guardado.
        return Situacion(FINALIZADO, c.get("tipo_cierre"), c["corte_cierre"], emite_semanales=c.get("tipo_cierre") == CAMBIO,
                         ultimo_corte_en_curso=c.get("ultimo_corte_en_curso"))
    previos = sorted(x for x in cortes_en_curso if x < corte)
    tipo = CAMBIO if previos else INCORPORADO
    return Situacion(FINALIZADO, tipo, corte, emite_semanales=tipo == CAMBIO, nuevo_cierre=oficial,
                     ultimo_corte_en_curso=previos[-1] if previos else None)


def fuera_de_folders(existentes: Mapping[str, Sequence[dict]], en_folders: Collection[str],
                     tablas: Collection[str], columnas: Sequence[str]) -> dict[str, dict]:
    """Listas con filas en la hoja (tablas) que no estan en ninguno de los dos folders -> columnas de su fila mas
    reciente (la identificacion con que se publico) y ultimo_corte."""
    out: dict[str, dict] = {}
    for t in tablas:
        for f in existentes.get(t, []):
            lid = f.get("list_id")
            if not lid or lid in en_folders:
                continue
            c, prev = f.get("corte"), out.get(lid)
            if prev is None or (c is not None and (prev["ultimo_corte"] is None or c > prev["ultimo_corte"])):
                out[lid] = {**{k: f.get(k) for k in columnas}, "ultimo_corte": c}
    return out


def cortes_en_curso(metricas: Sequence[dict]) -> dict[str, set[dt.date]]:
    """list_id -> cortes con filas semanales en curso (las filas anteriores a este cambio no tienen estado)."""
    out: dict[str, set[dt.date]] = {}
    for m in metricas:
        if m.get("corte") is not None and m.get("estado_proyecto") in (None, "", EN_CURSO):
            out.setdefault(m["list_id"], set()).add(m["corte"])
    return out


def _dh(cal: Calendario, a: dt.date | None, b: dt.date | None) -> int | None:
    return cal.networkdays(a, b) if a and b else None


def _div(a, b):
    return a / b if a is not None and b else None


def _resta(a, b):
    return a - b if a is not None and b is not None else None


def fila_cierre(*, list_id: str, ident: Mapping, sit: Situacion, metricas: Mapping, presupuesto: Mapping,
                hh_linea_base: float | None, rev_linea_base: int | None, fecha_inicio: dt.date | None,
                fecha_ultima_hora: dt.date | None, entrega_linea_base: dt.date | None,
                termino_vigente: dt.date | None, cal: Calendario, ahora: dt.datetime) -> dict:
    """Fila de `cierres`. Duraciones en dias habiles (inicio y termino inclusive):
    - real: del inicio del proyecto a la ultima hora registrada (ClickUp o, si es posterior, Timetracker del saldo
      historico);
    - contractual: del inicio a la fecha de entrega contractual de la linea base o, si falta, al vencimiento de la
      lista (origen en entrega_contractual_origen)."""
    entrega, origen = ((entrega_linea_base, "linea_base") if entrega_linea_base else
                       (termino_vigente, "vencimiento_lista") if termino_vigente else (None, None))
    real, contractual = _dh(cal, fecha_inicio, fecha_ultima_hora), _dh(cal, fecha_inicio, entrega)
    gastadas = metricas.get("hh_gastadas_acum")
    contrato = presupuesto.get("hh_contrato")
    return {
        "list_id": list_id, **{k: ident.get(k) for k in ("codigo", "nombre_corto", "cliente", "proyecto",
                                                         "jp_nombre", "jp_email", "programa")},
        "estado_proyecto": FINALIZADO, "tipo_cierre": sit.tipo_cierre, "corte_cierre": sit.corte_cierre,
        "ultimo_corte_en_curso": sit.ultimo_corte_en_curso,
        "fecha_inicio": fecha_inicio, "fecha_ultima_hora": fecha_ultima_hora,
        "fecha_entrega_contractual": entrega, "entrega_contractual_origen": origen,
        "duracion_real_dias_habiles": real, "duracion_contractual_dias_habiles": contractual,
        "diferencia_duracion_dias_habiles": _resta(real, contractual),
        "hh_gastadas_acum": gastadas, "hh_historicas": metricas.get("hh_historicas"),
        "rev_linea_base": rev_linea_base, "hh_linea_base": hh_linea_base,
        "hh_sobre_linea_base": _resta(gastadas, hh_linea_base), "pct_linea_base_usado": _div(gastadas, hh_linea_base),
        "hh_contrato": contrato, "hh_sobre_contrato": _resta(gastadas, contrato),
        "pct_contrato_usado": _div(gastadas, contrato),
        "avance_real_final": metricas.get("avance_real"), "avance_prog_final": metricas.get("avance_prog"),
        "registrado_en": ahora,
    }


def fusionar_cierres(existentes: Sequence[dict], nuevas: Sequence[dict], en_curso: Collection[str],
                     oficial: bool) -> list[dict]:
    """Una fila por lista. Las nuevas reemplazan a las de su lista; se borran las de listas que volvieron a
    PJ Ingenieria (en_curso). Las preliminares no cambian la pestaña."""
    if not oficial:
        return list(existentes)
    fuera = set(en_curso) | {f["list_id"] for f in nuevas}
    return [f for f in existentes if f.get("list_id") not in fuera] + list(nuevas)
