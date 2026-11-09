"""Plan vs real por persona y semana (TAREA_reportes_plan_vs_real, decisiones de Ale del 2026-11-02). Funciones puras,
salvo `escribir_hoja`.

Definiciones (docs/definiciones_reporte.md):
- Planificado (semana): sobre las tareas con responsable, alguna fecha y time estimate, que no tengan descendientes con
  time estimate (sin restringir a «porción»; No Aplica fuera): time_estimate × días hábiles de la tarea dentro de la
  semana / días hábiles totales de la tarea (calendario del modo: feriados de Chile y días no hábiles de IDIEM). Sin
  start (o sin días hábiles, o due < start): entera en la semana del due (o del start si no hay due). El time
  estimate es por persona (convención de los JP, 2026-11-05): con varios responsables cuenta completo para cada uno,
  como en Carga de trabajo de ClickUp, y el plan del proyecto suma el de cada responsable.
- Registrado (semana): entradas de tiempo por fecha trabajada (start de la entrada). Las de la lista PJ y, aparte, las
  de la tarea de la SS del proyecto en SS_REGISTRO (origen "SS"; fuera de la curva S).

Los datos son por persona: van a una hoja APARTE de «DEP - Reportes» (SHEETS_PLAN_VS_REAL_ID), de acceso restringido a
los JP. Nunca a la hoja de reportes.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from dep_clickup.models import Task, TimeEntry

from .calendario import Calendario

PESTAÑA = "plan_vs_real"
SEMANAS_ATRAS, SEMANAS_ADELANTE = 4, 6
SIN_RESPONSABLE, PROYECTO = "(sin responsable)", "(proyecto)"
PROPUESTAS = "Propuestas (SS)"     # proyecto de la carga de propuestas (tareas SS de SS_REGISTRO con estimate)
# SS que ya no son carga aunque tengan estimate y fechas (decisión de Ale del 2026-11-09). «cerrada» además es de tipo closed.
SS_INACTIVAS = frozenset({"ganada", "perdida", "cancelada", "cerrada"})
AUSENCIA = "(ausencia)"          # proyecto y estado de las filas de ausencia: filtrarlas para no sumarlas al plan
OK, PARCIAL, SIN_REGISTRO, SIN_PLAN, FUTURO = "ok", "parcial", "sin_registro", "sin_plan", "futuro"
UMBRAL_OK, UMBRAL_PARCIAL = 0.8, 0.5
ORIGEN_PJ, ORIGEN_SS = "PJ", "SS"
NO_APLICA = "no aplica"

COLUMNAS = [("fecha_corte", "fecha"), ("corte", "fecha"), ("tipo_corte", "texto"), ("semana_inicio", "fecha"),
            ("list_id", "texto"), ("proyecto", "texto"), ("proyecto_nombre", "texto"), ("jp", "texto"),
            ("persona", "texto"), ("horas_planificadas", "numero"), ("horas_registradas", "numero"),
            ("horas_registradas_ss", "numero"), ("cumplimiento", "numero"), ("estado", "texto"),
            ("horas_necesarias_semana", "numero"), ("es_ultimo_corte", "booleano")]


def lunes(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def fecha_corte(corte: dt.date) -> dt.date:
    """«Lunes del corte»: el lunes siguiente al domingo de corte (para un preliminar, el lunes de la semana que sigue
    al día de control si es domingo, o el de su misma semana)."""
    return lunes(corte + dt.timedelta(days=1))


def semanas(corte: dt.date, atras: int = SEMANAS_ATRAS, adelante: int = SEMANAS_ADELANTE) -> list[dt.date]:
    """Lunes de la ventana: `atras` semanas hasta la del corte (incluida) y `adelante` semanas siguientes."""
    l0 = lunes(corte)
    return [l0 + dt.timedelta(weeks=k) for k in range(-(atras - 1), adelante + 1)]


# --- Planificado ---------------------------------------------------------------------------------

def _es_no_aplica(t: Task) -> bool:
    return (t.status or "").strip().lower() == NO_APLICA


def tareas_plan(tareas: Sequence[Task], con_responsable: bool = True) -> list[Task]:
    """Tareas que entran al plan: time estimate y alguna fecha, sin descendientes con time estimate, no No Aplica.
    con_responsable=False incluye también las que no tienen responsable (fila «(sin responsable)»)."""
    por_id = {t.id: t for t in tareas}
    con_te_debajo: set[str] = set()
    for t in tareas:
        if (t.time_estimate_ms or 0) > 0:
            p, vistos = t.parent, set()
            while p in por_id and p not in vistos:
                vistos.add(p)
                con_te_debajo.add(p)
                p = por_id[p].parent
    return [t for t in tareas if (t.time_estimate_ms or 0) > 0 and (t.start_date or t.due_date)
            and t.id not in con_te_debajo and not _es_no_aplica(t) and (t.assignees or not con_responsable)]


def reparto_semanal(t: Task, cal: Calendario) -> dict[dt.date, float]:
    """Horas del time estimate por lunes de semana."""
    h = t.time_estimate_ms / 3_600_000
    s, d = t.start_date, t.due_date
    if not s or not d or d < s:
        return {lunes(d or s): h}
    dias = list(cal.dias_habiles(s, d))
    if not dias:
        return {lunes(d): h}
    out: dict[dt.date, float] = defaultdict(float)
    for x in dias:
        out[lunes(x)] += h / len(dias)
    return dict(out)


def plan_por_persona(tareas: Sequence[Task], cal: Calendario) -> dict[tuple[str, dt.date], float]:
    """(persona, lunes) -> horas planificadas. Persona = cada responsable (el time estimate es por persona: completo
    para cada uno) o SIN_RESPONSABLE."""
    out: dict[tuple[str, dt.date], float] = defaultdict(float)
    for t in tareas_plan(tareas, con_responsable=False):
        personas = list(t.assignees) or [SIN_RESPONSABLE]
        for sem, h in reparto_semanal(t, cal).items():
            for p in personas:
                out[(p, sem)] += h
    return dict(out)


def plan_semanal_total(plan: Mapping[tuple[str, dt.date], float]) -> dict[dt.date, float]:
    """lunes -> horas planificadas del proyecto (solo tareas con responsable, regla C)."""
    out: dict[dt.date, float] = defaultdict(float)
    for (p, sem), h in plan.items():
        if p != SIN_RESPONSABLE:
            out[sem] += h
    return dict(out)


# --- Registrado ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Registro:
    persona: str
    fecha: dt.date          # fecha trabajada (start de la entrada)
    horas: float
    origen: str             # ORIGEN_PJ | ORIGEN_SS


def registros(entradas: Iterable[TimeEntry], origen: str) -> list[Registro]:
    return [Registro(e.user_name or str(e.user_id), e.date, e.hours, origen) for e in entradas]


def por_semana(regs: Iterable[Registro], corte: dt.date, origen: str | None = None) -> dict[tuple[str, dt.date], float]:
    out: dict[tuple[str, dt.date], float] = defaultdict(float)
    for r in regs:
        if r.fecha <= corte and (origen is None or r.origen == origen):
            out[(r.persona, lunes(r.fecha))] += r.horas
    return dict(out)


# --- Horas necesarias ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Cajon:
    task_id: str
    hh: float
    due: dt.date | None
    gastadas: float          # horas del cajón y sus descendientes hasta el corte
    cerrado: bool


def necesarias_por_semana(cajones: Iterable[Cajon], corte: dt.date) -> dict[dt.date, float]:
    """HH presupuestadas de los cajones con fecha de término menos lo gastado, repartidas en partes iguales en las
    semanas posteriores al corte hasta la del término. Si el término ya pasó (o cae en la semana del corte), todo va a
    la primera semana siguiente. Cajones cerrados: 0."""
    primera = lunes(corte) + dt.timedelta(weeks=1)
    out: dict[dt.date, float] = defaultdict(float)
    for c in cajones:
        if c.cerrado or not c.due:
            continue
        resto = max(c.hh - c.gastadas, 0.0)
        if resto <= 0:
            continue
        ult = max(lunes(c.due), primera)
        sems = [primera + dt.timedelta(weeks=k) for k in range((ult - primera).days // 7 + 1)]
        for s in sems:
            out[s] += resto / len(sems)
    return dict(out)


# --- Filas ---------------------------------------------------------------------------------------

def estado(semana: dt.date, corte: dt.date, plan: float, reg: float) -> str | None:
    if semana > corte:
        return FUTURO
    if plan > 1e-9:
        c = reg / plan
        return OK if c >= UMBRAL_OK else PARCIAL if c >= UMBRAL_PARCIAL else SIN_REGISTRO
    return SIN_PLAN if reg > 1e-9 else None


def filas(corte: dt.date, tipo_corte: str, list_id: str, codigo: str, nombre: str, jp: str,
          plan: Mapping[tuple[str, dt.date], float], regs: Sequence[Registro],
          necesarias: Mapping[dt.date, float]) -> list[dict]:
    """Una fila por semana de la ventana y persona con algún valor, más la fila «(proyecto)» con las horas
    necesarias. codigo sin el prefijo PJ- (2026.0225)."""
    sems = semanas(corte)
    reg_pj, reg_ss = por_semana(regs, corte, ORIGEN_PJ), por_semana(regs, corte, ORIGEN_SS)
    personas = sorted({p for p, _ in plan} | {p for p, _ in reg_pj} | {p for p, _ in reg_ss},
                      key=lambda p: (p == SIN_RESPONSABLE, p))
    base = {"fecha_corte": fecha_corte(corte), "corte": corte, "tipo_corte": tipo_corte, "list_id": list_id,
            "proyecto": codigo, "proyecto_nombre": nombre, "jp": jp}
    out = []
    for s in sems:
        for p in personas:
            pl = plan.get((p, s), 0.0)
            futura = s > corte
            r = None if futura else reg_pj.get((p, s), 0.0)
            rs = None if futura else reg_ss.get((p, s), 0.0)
            if not (pl or r or rs):
                continue
            out.append({**base, "semana_inicio": s, "persona": p, "horas_planificadas": round(pl, 4),
                        "horas_registradas": r if r is None else round(r, 4),
                        "horas_registradas_ss": rs if rs is None else round(rs, 4),
                        "cumplimiento": (r / pl) if (r is not None and pl > 1e-9) else None,
                        "estado": estado(s, corte, pl, r or 0.0), "horas_necesarias_semana": None})
        n = necesarias.get(s)
        if n:
            out.append({**base, "semana_inicio": s, "persona": PROYECTO, "horas_planificadas": None,
                        "horas_registradas": None, "horas_registradas_ss": None, "cumplimiento": None,
                        "estado": None, "horas_necesarias_semana": round(n, 4)})
    return out


def filas_ausencia(corte: dt.date, tipo_corte: str, horas: Mapping[tuple[str, dt.date], float]) -> list[dict]:
    """Una fila por persona y semana de la ventana con ausencias de ADM-07: proyecto y estado «(ausencia)», horas en
    horas_planificadas. Una ausencia no es de ningún proyecto: va aparte y no cambia los encabezados de la hoja."""
    sems = set(semanas(corte))
    return [{"fecha_corte": fecha_corte(corte), "corte": corte, "tipo_corte": tipo_corte, "semana_inicio": s, "list_id": "",
             "proyecto": AUSENCIA, "proyecto_nombre": AUSENCIA, "jp": "", "persona": p, "horas_planificadas": round(h, 4),
             "horas_registradas": None, "horas_registradas_ss": None, "cumplimiento": None, "estado": AUSENCIA,
             "horas_necesarias_semana": None} for (p, s), h in sorted(horas.items(), key=lambda x: (x[0][1], x[0][0])) if s in sems]


def ss_activas(tareas: Sequence[Task]) -> list[Task]:
    """Tareas SS que cuentan como carga de propuestas: sin las cerradas ni las ganadas, perdidas o canceladas."""
    return [t for t in tareas if not t.cerrada and (t.status or "").strip().lower() not in SS_INACTIVAS]


def filas_propuestas(corte: dt.date, tipo_corte: str, list_id: str, plan: Mapping[tuple[str, dt.date], float]) -> list[dict]:
    """Carga de propuestas: tareas SS de SS_REGISTRO con responsable, fechas y estimate (regla C), proyecto «Propuestas
    (SS)» (decisión de Ale del 2026-11-09). Solo plan: las horas registradas en las SS siguen en horas_registradas_ss de
    su proyecto."""
    sems = set(semanas(corte))
    return [{"fecha_corte": fecha_corte(corte), "corte": corte, "tipo_corte": tipo_corte, "semana_inicio": s, "list_id": list_id,
             "proyecto": PROPUESTAS, "proyecto_nombre": PROPUESTAS, "jp": "", "persona": p, "horas_planificadas": round(h, 4),
             "horas_registradas": None, "horas_registradas_ss": None, "cumplimiento": None, "estado": None,
             "horas_necesarias_semana": None} for (p, s), h in sorted(plan.items(), key=lambda x: (x[0][1], x[0][0]))
            if s in sems and h > 1e-9 and p != SIN_RESPONSABLE]


# --- Hoja aparte ---------------------------------------------------------------------------------

def fusionar(existentes: Sequence[dict], nuevas: Sequence[dict], corte: dt.date, tipo_corte: str,
             alcance: set[str] | None = None) -> list[dict]:
    """Cada corte oficial se guarda (no se sobrescribe el historial): una corrida oficial reemplaza solo las filas de
    su corte y borra las preliminares; una preliminar reemplaza las preliminares. es_ultimo_corte se recalcula."""
    en = (lambda f: True) if alcance is None else (lambda f: f.get("list_id") in alcance)

    def se_borra(f: dict) -> bool:
        if not en(f):
            return False
        if (f.get("tipo_corte") or "oficial") == "preliminar":
            return True
        return tipo_corte == "oficial" and f.get("corte") == corte
    out = [dict(f) for f in existentes if not se_borra(f)] + [dict(f) for f in nuevas]
    ultimo = max((f["corte"] for f in out if f.get("corte")), default=None)
    for f in out:
        f["es_ultimo_corte"] = f.get("corte") == ultimo
    return out


def columnas() -> list[str]:
    return [c for c, _ in COLUMNAS]


def escribir_csv(ruta, filas_: Sequence[dict]) -> None:
    import csv
    from .almacen import celda_csv
    ti = dict(COLUMNAS)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columnas())
        for r in filas_:
            w.writerow([celda_csv(r.get(c), ti[c]) for c in columnas()])


def escribir_hoja(spreadsheet_id: str, nuevas: Sequence[dict], corte: dt.date, tipo_corte: str,
                  alcance: set[str] | None = None) -> int:
    """Lee la pestaña plan_vs_real de la hoja aparte, fusiona y la reescribe completa. Devuelve el número de filas."""
    from .almacen import AlmacenSheets, celda_sheets, desde_celda
    sh = AlmacenSheets(spreadsheet_id)
    meta = sh.metadata()
    ti = dict(COLUMNAS)
    existentes, largo = [], 0
    if PESTAÑA in meta:
        d = sh._req("GET", f"{sh.API}/{sh.id}/values/'{PESTAÑA}'", "leer:valores",
                    params={"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"})
        valores = d.get("values", [])
        largo = len(valores)
        if valores:
            cab = [str(c) for c in valores[0]]
            if cab != columnas():
                raise RuntimeError(f"La pestaña {PESTAÑA} tiene encabezados distintos: {cab}")
            existentes = [{c: desde_celda(fila[i] if i < len(fila) else None, ti[c]) for i, c in enumerate(cab)}
                          for fila in valores[1:] if any(x not in (None, "") for x in fila)]
    finales = fusionar(existentes, nuevas, corte, tipo_corte, alcance)
    vals = [columnas()] + [[celda_sheets(r.get(c), ti[c]) for c in columnas()] for r in finales]
    reqs = []
    if PESTAÑA not in meta:
        reqs.append({"addSheet": {"properties": {"title": PESTAÑA, "gridProperties": {
            "rowCount": max(len(vals) + 100, 1000), "columnCount": len(COLUMNAS)}}}})
    else:
        gp = meta[PESTAÑA].get("gridProperties", {})
        if gp.get("rowCount", 0) < len(vals) + 100:
            reqs.append({"updateSheetProperties": {"properties": {"sheetId": meta[PESTAÑA]["sheetId"], "gridProperties": {
                "rowCount": len(vals) + 100}}, "fields": "gridProperties.rowCount"}})
    if reqs:
        sh._req("POST", f"{sh.API}/{sh.id}:batchUpdate", "escribir:batchUpdate", json={"requests": reqs})
        meta = sh.metadata(refrescar=True)
    # Formato de fecha en las columnas de fecha (Looker las lee como fecha), como en almacen.AlmacenSheets.escribir.
    hoja = meta[PESTAÑA]["sheetId"]
    sh._req("POST", f"{sh.API}/{sh.id}:batchUpdate", "escribir:batchUpdate", json={"requests": [
        {"repeatCell": {"range": {"sheetId": hoja, "startRowIndex": 1, "startColumnIndex": j, "endColumnIndex": j + 1},
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}},
                        "fields": "userEnteredFormat.numberFormat"}}
        for j, (_, tipo) in enumerate(COLUMNAS) if tipo == "fecha"]})
    sh._req("POST", f"{sh.API}/{sh.id}/values:batchUpdate", "escribir:valores",
            json={"valueInputOption": "RAW", "data": [{"range": f"'{PESTAÑA}'!A1", "values": vals}]})
    if largo > len(vals):
        sh._req("POST", f"{sh.API}/{sh.id}/values:batchClear", "escribir:limpiar_sobrantes",
                json={"ranges": [f"'{PESTAÑA}'!A{len(vals) + 1}:P{largo}"]})
    return len(finales)
