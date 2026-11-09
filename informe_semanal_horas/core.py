"""Cálculo del informe semanal de horas, sin E/S: de time entries, tareas, ausencias y miembros al JSON
que consume la plantilla (`plantilla_semanal.html`). Definiciones en TAREA_informe_semanal_horas.md y README.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from dep_clickup.config import TZ
from dep_reportes.calendario import Calendario

UN_DIA = dt.timedelta(days=1)
UNA_SEMANA = dt.timedelta(days=7)
SS_REGISTRO = "901324495476"
PROPUESTAS = "Propuestas (SS)"
LISTAS_PRUEBA = ("PJ-TEST", "PJ-EJEMPLO")
LISTA_AUSENCIAS = "ADM-07"
UMBRAL_H = 4.0
JORNADA_ESTANDAR = 44.0
TIPOS_AUSENCIA = {0: "compensatorio", 1: "administrativo", 2: "vacaciones", 3: "licencia"}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
PLANTILLA = Path(__file__).with_name("plantilla_semanal.html")
# Copia de una entrada movida entre tareas por orden_adm: su `at` es el día del movimiento, no el del registro.
MOVIDA = re.compile(r"movida desde .+ el \d{4}-\d{2}-\d{2}")
_CODIGO = re.compile(r"^\s*(?:PJ|PR)-(\d{4}\.[0-9A-Za-z]+(?:-\d+)?)")
_ADM = re.compile(r"^\s*(ADM-\d+)")


def lunes(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def semanas(hoy: dt.date) -> list[dt.date]:
    """[semana pasada, actual, próxima], lunes de cada una."""
    w = lunes(hoy)
    return [w - UNA_SEMANA, w, w + UNA_SEMANA]


def dia_local(ms) -> dt.date | None:
    return dt.datetime.fromtimestamp(int(ms) / 1000, TZ).date() if ms else None


def etiqueta(lista: str | None, lista_id: str | None = None) -> str:
    """Proyecto que se muestra: código sin prefijo PJ-/PR-, ADM-…, «Propuestas (SS)» o el nombre de la lista."""
    if lista_id == SS_REGISTRO or lista == "SS_REGISTRO":
        return PROPUESTAS
    n = lista or "(sin lista)"
    m = _CODIGO.match(n) or _ADM.match(n)
    return m.group(1) if m else n.strip()


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFD", t or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower().strip()


def _tokens(nombre: str) -> set[str]:
    return {x for x in re.split(r"[^a-z]+", normalizar(nombre)) if len(x) > 1}


def mismo_nombre(a: str, b: str) -> bool:
    """Tolerante a tildes y apellidos parciales: las palabras del nombre más corto están todas en el otro."""
    ta, tb = _tokens(a), _tokens(b)
    return len(min(ta, tb, key=len)) >= 2 and (ta <= tb or tb <= ta)


def cruzar_nombre(nombre: str, candidatos: Iterable[str]) -> str | None:
    """El único candidato que calza con `nombre`; None si no hay ninguno o es ambiguo."""
    hallados = [c for c in candidatos if mismo_nombre(nombre, c)]
    return hallados[0] if len(hallados) == 1 else None


# --- Planilla de ausencias ----------------------------------------------------------------------

@dataclass
class Ausencias:
    dias: dict[str, dict[dt.date, tuple[str, float]]]   # nombre en la planilla → día → (tipo, fracción ausente)
    siglas: dict[str, str]                              # nombre en la planilla → sigla


def leer_ausencias(ws, fila_mes: int = 4, fila_dia: int = 5, col_nombre: int = 2, col_sigla: int = 1) -> Ausencias:
    """Fila 4 = mes (celda combinada, solo la primera columna trae fecha), fila 5 = día del mes, desde la
    fila 6 una persona por fila. Código: 0 compensatorio, 1 administrativo (0,5 medio día), 2 vacaciones,
    3 licencia. Cualquier otro valor se ignora."""
    fechas: dict[int, dt.date] = {}
    mes = None
    for col in range(1, ws.max_column + 1):
        v = ws.cell(fila_mes, col).value
        if isinstance(v, dt.datetime):
            mes = v.date()
        d = ws.cell(fila_dia, col).value
        if mes is not None and isinstance(d, (int, float)):
            try:
                fechas[col] = mes.replace(day=int(d))
            except ValueError:          # p. ej. 29 de febrero en una columna de relleno
                pass
    out, siglas = {}, {}
    for fila in range(fila_dia + 1, ws.max_row + 1):
        nombre = ws.cell(fila, col_nombre).value
        if not (isinstance(nombre, str) and nombre.strip()):
            continue
        nombre = nombre.strip()
        siglas[nombre] = str(ws.cell(fila, col_sigla).value or "").strip()
        dias = out.setdefault(nombre, {})
        for col, fecha in fechas.items():
            v = ws.cell(fila, col).value
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if v == 0.5:
                    dias[fecha] = (TIPOS_AUSENCIA[1], 0.5)
                elif v in TIPOS_AUSENCIA:
                    dias[fecha] = (TIPOS_AUSENCIA[int(v)], 1.0)
    return Ausencias(out, siglas)


# --- Normalización de entradas y tareas -----------------------------------------------------------

@dataclass(frozen=True)
class Entrada:
    uid: int
    nombre: str
    task_id: str
    tarea: str
    lista_id: str
    proyecto: str
    fecha: dt.date
    registro: dt.date
    horas: float


def normalizar_entradas(crudas: Iterable[dict], fechas_carga_api: Iterable[dt.date] = ()) -> list[Entrada]:
    """Sin cronómetros corriendo ni cargas históricas por API.

    Carga por API = source «api» registrada en una de `fechas_carga_api`. Las demás entradas con source «api»
    son horas reales movidas por script entre tareas (scripts/mover_entradas_pr.py) y sí cuentan. Las copias de
    orden_adm («movida desde <tarea> el <fecha>» en la descripción) no cuentan como cargadas tarde."""
    cargas = set(fechas_carga_api)
    out = []
    for e in crudas:
        dur = int(e.get("duration") or 0)
        if dur <= 0 or not e.get("start") or not e.get("at"):
            continue
        registro = dia_local(e["at"])
        if e.get("source") == "api" and registro in cargas:
            continue
        if MOVIDA.search(e.get("description") or ""):
            registro = dia_local(e["start"])
        loc, task, u = e.get("task_location") or {}, e.get("task") or {}, e.get("user") or {}
        if (loc.get("list_name") or "").startswith(LISTA_AUSENCIAS):
            continue
        out.append(Entrada(int(u.get("id") or 0), u.get("username") or "", task.get("id") or "", task.get("name") or "",
                           loc.get("list_id") or "", etiqueta(loc.get("list_name"), loc.get("list_id")),
                           dia_local(e["start"]), registro, dur / 3_600_000))
    return out


def _horas_estimadas(t: dict) -> float:
    return int(t["time_estimate"]) / 3_600_000 if t.get("time_estimate") else 0.0


def _de_prueba(t: dict) -> bool:
    """Listas de prueba y ADM-07: las ausencias no son horas asignadas (salen en días, desde la lista)."""
    return ((t.get("list") or {}).get("name") or "").startswith(LISTAS_PRUEBA + (LISTA_AUSENCIAS,))


@dataclass
class Tareas:
    por_id: dict[str, dict]
    hijos: dict[str, list[str]]

    @classmethod
    def desde(cls, crudas: Iterable[dict]) -> "Tareas":
        por_id = {t["id"]: t for t in crudas if not _de_prueba(t)}
        hijos: dict[str, list[str]] = defaultdict(list)
        for t in por_id.values():
            if t.get("parent"):
                hijos[t["parent"]].append(t["id"])
        return cls(por_id, hijos)

    def descendiente_estimada(self, tid: str) -> bool:
        pila = list(self.hijos.get(tid, ()))
        while pila:
            h = pila.pop()
            if h in self.por_id and _horas_estimadas(self.por_id[h]) > 0:
                return True
            pila.extend(self.hijos.get(h, ()))
        return False

    def cajon(self, t: dict) -> str:
        """Nombre de la tarea de primer nivel ancestro; vacío si la tarea ya es de primer nivel."""
        actual, vistos = t, {t["id"]}
        while actual.get("parent") and actual["parent"] in self.por_id and actual["parent"] not in vistos:
            actual = self.por_id[actual["parent"]]
            vistos.add(actual["id"])
        return actual["name"].strip() if actual is not t else ""


# --- Asignación (workload) ------------------------------------------------------------------------

def ventana(t: dict) -> tuple[dt.date, dt.date] | None:
    """Sin start → un día en due; solo start → un día en start; start > due → solo due. Sin fechas → None."""
    due, start = dia_local(t.get("due_date")), dia_local(t.get("start_date"))
    if not due and not start:
        return None
    due = due or start
    start = start or due
    return (due, due) if start > due else (start, due)


def repartir(a: dt.date, b: dt.date, cal: Calendario) -> dict[dt.date, float]:
    """Fracción por semana según días hábiles de a..b. Ventana sin hábiles → todo a la semana de b."""
    por_semana: Counter = Counter()
    for d in cal.dias_habiles(a, b):
        por_semana[lunes(d)] += 1
    n = sum(por_semana.values())
    return {s: k / n for s, k in por_semana.items()} if n else {lunes(b): 1.0}


def rango_dias(a: dt.date, b: dt.date) -> str:
    if a.month == b.month:
        return f"{a.day}–{b.day} {MESES[b.month - 1]}"
    return f"{a.day} {MESES[a.month - 1]}–{b.day} {MESES[b.month - 1]}"


@dataclass
class Asignado:
    horas: float = 0.0
    listas: set = field(default_factory=set)            # etiquetas de proyecto
    lista_ids: set = field(default_factory=set)
    tareas: list = field(default_factory=list)          # filas de tareas_prog


def calcular_asignado(tareas: Tareas, cal: Calendario, semanas_: list[dt.date]) -> dict[tuple[int, dt.date], Asignado]:
    """Por (persona, semana): tareas con responsable, fechas y estimación, prorrateadas por días hábiles. El
    time_estimate es por persona (convención de los JP, 05-nov): con varios responsables cuenta completo para cada uno,
    como en Carga de trabajo de ClickUp. Una tarea con alguna descendiente estimada no cuenta."""
    out: dict[tuple[int, dt.date], Asignado] = defaultdict(Asignado)
    objetivo = set(semanas_)
    for t in tareas.por_id.values():
        h = _horas_estimadas(t)
        if h <= 0 or not t.get("assignees") or tareas.descendiente_estimada(t["id"]):
            continue
        v = ventana(t)
        if v is None:
            continue
        for w, frac in repartir(v[0], v[1], cal).items():
            if w not in objetivo:
                continue
            ini, fin = max(v[0], w), min(v[1], w + dt.timedelta(days=4))
            if ini > fin:               # ventana solo en fin de semana
                ini, fin = v[1], v[1]
            proyecto = etiqueta(t["list"]["name"], t["list"]["id"])
            for a in t["assignees"]:
                k = out[(int(a["id"]), w)]
                k.horas += h * frac
                k.listas.add(proyecto)
                k.lista_ids.add(t["list"]["id"])
                k.tareas.append({"p": proyecto, "c": tareas.cajon(t), "t": t["name"], "h": round(h * frac, 1),
                                 "d": rango_dias(ini, fin)})
    return out


# --- Informe --------------------------------------------------------------------------------------

@dataclass
class Parametros:
    hoy: dt.date
    ultimo_dia: dt.date                 # último día con registro cerrado: hoy, o ayer si hoy sigue en curso
    excluir_nuevos_semanas: int = 4
    excluir: tuple[str, ...] = ()
    estimacion_sin_adm: bool = False    # la tabla de estimación sin las listas ADM (como la maqueta)
    incluir: tuple[str, ...] = ()       # entran aunque lleven menos de excluir_nuevos_semanas
    jornadas: dict = field(default_factory=dict)    # nombre → horas semanales, solo jornadas distintas de la estándar
    jornada_estandar: float = JORNADA_ESTANDAR
    sin_dias_fijos: tuple[str, ...] = ()    # jornada parcial en días variables: la semana en curso no sale en rojo

    def jornada(self, nombre: str) -> float:
        return next((float(h) for n, h in self.jornadas.items() if mismo_nombre(nombre, n)), float(self.jornada_estandar))


def personas_incluidas(miembros: list[dict], p: Parametros) -> tuple[list[dict], list[dict]]:
    """(incluidas, excluidas con motivo). Nadie sale por dejar de registrar."""
    limite = p.hoy - dt.timedelta(weeks=p.excluir_nuevos_semanas)
    dentro, fuera = [], []
    for m in miembros:
        ingreso = dia_local(m.get("ingreso_ms"))
        if any(mismo_nombre(m["nombre"], x) for x in p.excluir):
            fuera.append({**m, "motivo": "lista explícita"})
        elif ingreso and ingreso > limite and not any(mismo_nombre(m["nombre"], x) for x in p.incluir):
            fuera.append({**m, "motivo": f"ingresó el {ingreso.isoformat()}"})
        else:
            dentro.append(m)
    return dentro, fuera


def estado_dia(h: float, esperado: float = 1.0) -> str:
    if h <= 0:
        return "sin"
    return "ok" if h >= UMBRAL_H * esperado else "bajo"


def _dias(uid_entradas: list[Entrada], w: dt.date, ausencias: dict, cal: Calendario, p: Parametros,
          jornada: float | None = None, dias_variables: bool = False) -> list[dict]:
    """Con jornada parcial el umbral de «menos de 4 h» se escala, y si la persona ya registró su jornada de la
    semana los demás días sin horas no corresponden (hay quien la concentra en dos días). Sin días fijos, los días
    sin horas de la semana en curso tampoco salen en rojo: se evalúan al cerrar la semana."""
    jornada = p.jornada_estandar if jornada is None else jornada
    fraccion = jornada / p.jornada_estandar
    cumplida = jornada < p.jornada_estandar and sum(e.horas for e in uid_entradas) >= jornada - 0.05
    en_curso = dias_variables and w + dt.timedelta(days=4) > p.ultimo_dia
    limite_tarde = w + UNA_SEMANA
    por_dia = defaultdict(list)
    for e in uid_entradas:
        por_dia[e.fecha].append(e)
    out = []
    for i in range(5):
        d = w + dt.timedelta(days=i)
        s = d.isoformat()
        if d > p.ultimo_dia:
            out.append({"d": s, "e": "futuro", "h": 0})
        elif not cal.es_habil(d):
            out.append({"d": s, "e": "feriado", "h": 0})
        elif d in ausencias and ausencias[d][1] >= 1:
            out.append({"d": s, "e": "ausente", "h": 0, "t": ausencias[d][0]})
        else:
            es = por_dia[d]
            h = sum(e.horas for e in es)
            if h <= 0 and cumplida:
                out.append({"d": s, "e": "ausente", "h": 0, "t": "jornada cumplida"})
                continue
            if h <= 0 and en_curso:
                out.append({"d": s, "e": "ausente", "h": 0, "t": "sin días fijos: se evalúa al cerrar la semana"})
                continue
            fila = {"d": s, "e": estado_dia(h, (ausencias[d][1] if d in ausencias else 1.0) * fraccion), "h": round(h, 1),
                    "tarde": round(sum(e.horas for e in es if e.registro > limite_tarde), 1)}
            if d in ausencias:
                fila["t"] = "medio día administrativo"
            out.append(fila)
    return out


def _ausencias_de(nombre: str, a: Ausencias | None) -> dict:
    if a is None:
        return {}
    clave = cruzar_nombre(nombre, a.dias)
    return a.dias[clave] if clave else {}


def construir(entradas: list[Entrada], tareas: Tareas, miembros: list[dict], ausencias: Ausencias | None,
              cal: Calendario, p: Parametros) -> dict:
    """El JSON del informe general (los mismos campos que la maqueta)."""
    W = semanas(p.hoy)
    asignado = calcular_asignado(tareas, cal, W)
    vigentes = [e for e in entradas if e.fecha <= p.ultimo_dia]
    acum: Counter = Counter()
    for e in vigentes:
        acum[e.task_id] += e.horas
    en_semana = defaultdict(list)
    for e in vigentes:
        en_semana[(e.uid, lunes(e.fecha))].append(e)

    incluidas, _ = personas_incluidas(miembros, p)
    personas = []
    for m in sorted(incluidas, key=lambda x: normalizar(x["nombre"])):
        ausentes = _ausencias_de(m["nombre"], ausencias)
        jornada = p.jornada(m["nombre"])
        variables = any(mismo_nombre(m["nombre"], x) for x in p.sin_dias_fijos)
        filas = []
        for w in W:
            es = en_semana[(m["id"], w)]
            ag = asignado.get((m["id"], w)) or Asignado()
            proy, por_tarea = Counter(), defaultdict(list)
            for e in es:
                proy[e.proyecto] += e.horas
                por_tarea[e.task_id].append(e)
            detalle = []
            for tid, lista in por_tarea.items():
                t = tareas.por_id.get(tid)
                detalle.append({"p": lista[0].proyecto, "t": lista[0].tarea, "h": round(sum(e.horas for e in lista), 1),
                                "d": len({e.fecha for e in lista}), "est": round(_horas_estimadas(t), 1) if t else 0,
                                "acum": round(acum[tid], 1)})
            detalle.sort(key=lambda x: -x["h"])
            fila = {"w": w.isoformat(), "dias": _dias(es, w, ausentes, cal, p, jornada, variables), "asig": round(ag.horas, 1),
                    "reg": round(sum(e.horas for e in es), 1), "listas": sorted(ag.listas),
                    "proy": [{"p": k, "h": round(v, 1)} for k, v in proy.most_common()], "tareas": detalle}
            if w == W[2]:
                fila["tareas_prog"] = sorted(ag.tareas, key=lambda x: -x["h"])
            filas.append(fila)
        personas.append({"nombre": m["nombre"], "id": m["id"], "jornada": jornada, "semanas": filas})
    personas.sort(key=lambda x: -sum(d["e"] == "sin" for d in x["semanas"][0]["dias"]))   # sort estable: empate por nombre

    ids = {x["id"] for x in personas}
    proyectos: dict[str, dict] = defaultdict(dict)
    grupo = defaultdict(list)
    for e in vigentes:
        if e.uid in ids and lunes(e.fecha) in W:
            grupo[(e.proyecto, lunes(e.fecha))].append(e)
    for (k, w), es in grupo.items():
        proyectos[k][w.isoformat()] = {"h": round(sum(e.horas for e in es), 1), "n": len({e.uid for e in es})}
    asg_next: dict[str, set] = defaultdict(set)
    for x in personas:
        for fila in x["semanas"][2]["tareas_prog"]:
            asg_next[fila["p"]].add(x["nombre"])

    return {"hoy": p.hoy.isoformat(), "ultimo_dia": p.ultimo_dia.isoformat(), "W": [w.isoformat() for w in W],
            "personas": personas, "proyectos": dict(proyectos), "asg_next": {k: sorted(v) for k, v in asg_next.items()},
            "estimacion": estimacion(tareas, acum, W[0], p.estimacion_sin_adm)}


def estimacion(tareas: Tareas, acum: Counter, w: dt.date, sin_adm: bool = False) -> list[dict]:
    """Tareas con estimación propia que vencían en la semana w, con las horas acumuladas en la tarea misma."""
    out = []
    for t in tareas.por_id.values():
        h, due = _horas_estimadas(t), dia_local(t.get("due_date"))
        proyecto = etiqueta(t["list"]["name"], t["list"]["id"])
        if h > 0 and due and w <= due < w + UNA_SEMANA and not (sin_adm and proyecto.startswith("ADM-")):
            out.append({"p": proyecto, "t": t["name"], "est": round(h, 1),
                        "reg": round(acum[t["id"]], 1), "estado": t.get("status") or "", "_lista": t["list"]["id"]})
    out.sort(key=lambda x: -x["est"])
    return out


# --- Versiones por JP -----------------------------------------------------------------------------

def jefes(listas: list[dict], a_cargo: dict[str, str] | None = None,
          permitidos: Iterable[str] = ()) -> tuple[dict[str, dict], dict[str, int]]:
    """JP (responsable de la lista; ClickUp solo da su nombre al listar) → {nombre, listas}. Solo listas PJ- reales.

    `a_cargo`: responsable → JP que lo tiene a cargo; sus listas pasan a la versión de ese JP. `permitidos`: los únicos
    JP con versión (vacío = todos). Devuelve también los responsables sin versión, con su cantidad de listas."""
    permitidos = tuple(permitidos)
    out: dict[str, dict] = {}
    sin_version: dict[str, int] = {}
    for l in listas:
        if not (l.get("jp") and l["name"].startswith("PJ-") and not l["name"].startswith(LISTAS_PRUEBA)):
            continue
        jp = next((v for k, v in (a_cargo or {}).items() if mismo_nombre(l["jp"], k)), l["jp"])
        if permitidos:
            definido = next((x for x in permitidos if mismo_nombre(jp, x)), None)
            if definido is None:
                sin_version[jp] = sin_version.get(jp, 0) + 1
                continue
            jp = definido
        out.setdefault(jp, {"nombre": jp, "listas": set()})["listas"].add(l["id"])
    return out, sin_version


def version_jp(general: dict, jp: dict, entradas: list[Entrada], tareas: Tareas, cal: Calendario) -> dict | None:
    """Filtra el general a las personas con horas o asignación en alguna lista del JP en las tres semanas.
    Las tarjetas quedan completas; «Por proyecto» y la tabla de estimación, solo con los proyectos del JP.
    None si nadie trabaja en sus listas esas semanas."""
    W = [dt.date.fromisoformat(w) for w in general["W"]]
    ultimo = dt.date.fromisoformat(general["ultimo_dia"])
    listas = jp["listas"]
    ids = {e.uid for e in entradas if e.lista_id in listas and lunes(e.fecha) in W and e.fecha <= ultimo}
    asignado = calcular_asignado(tareas, cal, W)
    ids |= {uid for (uid, _), a in asignado.items() if a.lista_ids & listas}
    personas = [x for x in general["personas"] if x["id"] in ids]
    if not personas:
        return None
    codigos = {etiqueta(t["list"]["name"], t["list"]["id"]) for t in tareas.por_id.values() if t["list"]["id"] in listas}
    codigos |= {e.proyecto for e in entradas if e.lista_id in listas}
    return {**general, "personas": personas, "jp": jp["nombre"],
            "proyectos": {k: v for k, v in general["proyectos"].items() if k in codigos},
            "asg_next": {k: v for k, v in general["asg_next"].items() if k in codigos},
            "estimacion": [x for x in general["estimacion"] if x["_lista"] in listas]}


def iniciales(nombre: str, ausencias: Ausencias | None) -> str:
    """La sigla de la planilla si la persona está en ella; si no, las iniciales del nombre."""
    if ausencias:
        clave = cruzar_nombre(nombre, ausencias.siglas)
        if clave and ausencias.siglas.get(clave):
            return ausencias.siglas[clave]
    return "".join(x[0] for x in re.split(r"[^\w]+", nombre) if x).upper()


# --- Salida ---------------------------------------------------------------------------------------

def _escapar(x):
    """La plantilla arma el HTML con innerHTML: los nombres de tareas se escapan al insertarlos."""
    if isinstance(x, str):
        return html.escape(x, quote=True)
    if isinstance(x, list):
        return [_escapar(v) for v in x]
    if isinstance(x, dict):
        return {k: _escapar(v) for k, v in x.items()}
    return x


def _publico(datos: dict) -> dict:
    """Quita los campos internos (id de persona, id de lista) del JSON que va dentro del HTML."""
    return {**datos, "personas": [{k: v for k, v in x.items() if k != "id"} for x in datos["personas"]],
            "estimacion": [{k: v for k, v in x.items() if not k.startswith("_")} for x in datos["estimacion"]]}


def render(datos: dict, generado: str, plantilla: Path = PLANTILLA) -> str:
    cuerpo = _escapar({**_publico(datos), "generado": generado})
    return plantilla.read_text(encoding="utf-8").replace("__DATA__", json.dumps(cuerpo, ensure_ascii=False))
