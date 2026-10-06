"""Programas de servicio continuo (config/programas.json). Funciones puras, salvo cargar().

Un programa agrupa listas de un mismo servicio largo (sin curva S) que se reporta por contrato y por linea:
- linea: de la lista (cada encargado presenta solo la suya);
- contrato: fijo en la lista ("contrato") o deducido del nombre de la fase (tarea de primer nivel) con
  contratos.<id>.patron_fase. Si la fase calza con mas de un contrato o con ninguno, la hora va al
  "contrato_por_defecto" de la lista o, si no tiene, queda "compartido": aparece en las horas por linea, pero no en el
  consumo de ningun contrato.
Asi funciona igual con las listas actuales (una lista general por contrato) y con una lista "General" con una fase
por contrato.

Las horas son las mismas que cuenta el reporte (horas.py): las nativas de ClickUp que el reporte cuenta en cada
lista y, antes del corte historico, el saldo del Timetracker de la lista (origen "timetracker", linea "historial").
Una lista solo_consumo (p. ej. una finalizada) no entra a la vista, pero sus horas cuentan en el consumo de su contrato.

Tres pestañas, que se reemplazan completas en cada corrida (salvo con --solo):
- programa_horas: horas por mes, contrato, linea, lista y origen;
- programa_contratos: por contrato y mes, horas del mes y acumuladas frente al ritmo planificado
  (HH del periodo / meses del periodo; vacio mientras no haya presupuesto en la config), y las horas "compartido"
  del programa en ese mes (no son de ningun contrato: no se suman entre contratos);
- programa_entregables: entregables por prefijo del nombre (IM, VT, RD, RA...), con su situacion frente a la fecha de
  entrega y su frecuencia ("mensual": un paquete por mes; "evento": uno por evento, con plazo). Una tarea cuyo ancestro
  ya es un entregable del mismo tipo no cuenta aparte (los RD diarios dentro del paquete mensual). Las lineas de
  entregables_excluir_lineas no aportan entregables (sus horas si cuentan en la linea).

Advertencias para Administracion DEP (run.filas_programa): horas "compartido" (nivel programa, con las fases de
origen) y limpieza de entregables (plantilla sin usar, codigo repetido en el contrato, cierre muy anterior a la
fecha de entrega).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from dep_clickup.models import Task

COMPARTIDO = "compartido"
HISTORIAL = "historial"
NOMBRE_COMPARTIDO = "Compartido (varios contratos)"
NOMBRE_HISTORIAL = "Historial Timetracker (sin línea)"
CLICKUP, TIMETRACKER = "clickup", "timetracker"
A_TIEMPO, ATRASADO, PENDIENTE, VENCIDO, SIN_FECHA = "a_tiempo", "atrasado", "pendiente", "vencido", "sin_fecha"
CERRADO_SIN_FECHA = "cerrado_sin_fecha_cierre"
ABIERTAS = (VENCIDO, PENDIENTE, SIN_FECHA)
PLANTILLA = r"N[°º]\s*[a-z]\b"          # "VT-02 Visita N°x": numero sin completar
CODIGO_ENTREGABLE = re.compile(r"^\s*([A-Za-z]+-\d+(?:\.\d+)?)")
DIAS_CIERRE_ANTICIPADO = 30
MENSUAL, EVENTO = "mensual", "evento"
FRECUENCIAS = (MENSUAL, EVENTO)


@dataclass(frozen=True)
class Contrato:
    id: str
    nombre: str
    codigo: str
    patron_fase: re.Pattern | None
    hh_periodo: float | None = None
    hh_mes: float | None = None
    periodo_inicio: dt.date | None = None
    periodo_fin: dt.date | None = None

    @property
    def meses_periodo(self) -> int | None:
        if not (self.periodo_inicio and self.periodo_fin):
            return None
        return meses_entre(self.periodo_inicio, self.periodo_fin)

    @property
    def ritmo(self) -> float | None:
        """HH planificadas por mes: hh_mes, o hh_periodo / meses del periodo."""
        if self.hh_mes:
            return self.hh_mes
        if self.hh_periodo and self.meses_periodo:
            return self.hh_periodo / self.meses_periodo
        return None

    @property
    def hh_total_periodo(self) -> float | None:
        if self.hh_periodo:
            return self.hh_periodo
        if self.hh_mes and self.meses_periodo:
            return self.hh_mes * self.meses_periodo
        return None


@dataclass(frozen=True)
class ListaPrograma:
    list_id: str
    linea: str
    contrato: str | None = None       # fijo; None = se deduce de la fase
    solo_consumo: bool = False
    contrato_por_defecto: str | None = None   # fase que no calza con un unico contrato (None = "compartido")


@dataclass(frozen=True)
class Programa:
    id: str
    nombre: str
    cliente: str
    contratos: dict[str, Contrato]
    lineas: dict[str, str]
    listas: dict[str, ListaPrograma]
    entregables: dict[str, re.Pattern] = field(default_factory=dict)
    advertencias_omitidas: frozenset[str] = frozenset()
    entregables_excluir_lineas: frozenset[str] = frozenset()
    patron_plantilla: re.Pattern = re.compile(PLANTILLA, re.I)
    dias_cierre_anticipado: int = DIAS_CIERRE_ANTICIPADO
    frecuencias: dict[str, str] = field(default_factory=dict)    # tipo de entregable -> mensual / evento

    def contrato_de(self, list_id: str, fase: str | None) -> str:
        lp = self.listas[list_id]
        if lp.contrato:
            return lp.contrato
        calzan = [c.id for c in self.contratos.values() if c.patron_fase and fase and c.patron_fase.search(fase)]
        return calzan[0] if len(calzan) == 1 else lp.contrato_por_defecto or COMPARTIDO

    def contrato_historico(self, list_id: str) -> str:
        """Contrato del saldo del Timetracker de la lista (no tiene fase)."""
        lp = self.listas[list_id]
        return lp.contrato or lp.contrato_por_defecto or COMPARTIDO

    def nombre_contrato(self, cid: str) -> str:
        return self.contratos[cid].nombre if cid in self.contratos else NOMBRE_COMPARTIDO

    def nombre_linea(self, linea: str) -> str:
        return NOMBRE_HISTORIAL if linea == HISTORIAL else self.lineas.get(linea, linea)


def _fecha(x) -> dt.date | None:
    return dt.date.fromisoformat(x) if x else None


def desde_dict(pid: str, d: Mapping) -> Programa:
    contratos = {}
    for cid, c in d.get("contratos", {}).items():
        p = c.get("presupuesto") or {}
        contratos[cid] = Contrato(cid, c.get("nombre", cid), c.get("codigo", ""),
                                  re.compile(c["patron_fase"], re.I) if c.get("patron_fase") else None,
                                  p.get("hh_periodo"), p.get("hh_mes"), _fecha(p.get("periodo_inicio")),
                                  _fecha(p.get("periodo_fin")))
    listas = {}
    for l in d.get("listas", []):
        for campo in ("contrato", "contrato_por_defecto"):
            if l.get(campo) and l[campo] not in contratos:
                raise ValueError(f"programa {pid}: la lista {l['list_id']} tiene {campo} {l[campo]} sin definir")
        if l.get("contrato") and l.get("contrato_por_defecto"):
            raise ValueError(f"programa {pid}: la lista {l['list_id']} tiene contrato fijo y contrato_por_defecto")
        if l["linea"] not in d.get("lineas", {}):
            raise ValueError(f"programa {pid}: la lista {l['list_id']} tiene la línea {l['linea']} sin definir")
        listas[l["list_id"]] = ListaPrograma(l["list_id"], l["linea"], l.get("contrato"), bool(l.get("solo_consumo")),
                                             l.get("contrato_por_defecto"))
    patrones, frecuencias = {}, {}
    for tipo, v in (d.get("entregables") or {}).items():
        v = {"patron": v} if isinstance(v, str) else v       # forma corta: solo el patron (frecuencia "evento")
        frecuencias[tipo] = v.get("frecuencia", EVENTO)
        if frecuencias[tipo] not in FRECUENCIAS:
            raise ValueError(f"programa {pid}: el entregable {tipo} tiene frecuencia {frecuencias[tipo]} "
                             f"(válidas: {', '.join(FRECUENCIAS)})")
        patrones[tipo] = re.compile(v["patron"], re.I)
    return Programa(pid, d.get("nombre", pid), d.get("cliente", ""), contratos, dict(d.get("lineas", {})), listas,
                    patrones,
                    frozenset(d.get("advertencias_omitidas") or ()),
                    frozenset(d.get("entregables_excluir_lineas") or ()),
                    re.compile(d.get("patron_plantilla") or PLANTILLA, re.I),
                    int(d.get("dias_cierre_anticipado", DIAS_CIERRE_ANTICIPADO)), frecuencias)


def cargar(ruta: Path) -> dict[str, Programa]:
    """config/programas.json -> programas (vacio si no existe)."""
    if not ruta.exists():
        return {}
    d = json.loads(ruta.read_text(encoding="utf-8"))
    return {pid: desde_dict(pid, p) for pid, p in (d.get("programas") or {}).items()}


def por_lista(programas: Mapping[str, Programa]) -> dict[str, Programa]:
    out: dict[str, Programa] = {}
    for p in programas.values():
        for lid in p.listas:
            if lid in out:
                raise ValueError(f"la lista {lid} está en dos programas: {out[lid].id} y {p.id}")
            out[lid] = p
    return out


# --- Meses --------------------------------------------------------------------------------------

def mes(d: dt.date) -> dt.date:
    return d.replace(day=1)


def meses_entre(a: dt.date, b: dt.date) -> int:
    """Meses calendario de a a b, ambos incluidos."""
    return (b.year - a.year) * 12 + b.month - a.month + 1


def serie_meses(a: dt.date, b: dt.date) -> list[dt.date]:
    out, m = [], mes(a)
    while m <= mes(b):
        out.append(m)
        m = (m + dt.timedelta(days=32)).replace(day=1)
    return out


# --- Horas --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class HoraPrograma:
    list_id: str
    linea: str
    contrato: str
    fecha: dt.date
    horas: float
    origen: str = CLICKUP
    en_vista: bool = True             # False: lista solo_consumo
    fase: str = ""


def fase_por_tarea(tareas: Iterable[Task]) -> dict[str, str]:
    """task_id -> nombre de su tarea de primer nivel (la fase)."""
    por_id = {t.id: t for t in tareas}
    out = {}
    for t in por_id.values():
        r, vistos = t, set()
        while r.parent and r.parent in por_id and r.parent not in vistos:
            vistos.add(r.id)
            r = por_id[r.parent]
        out[t.id] = r.name.strip()
    return out


def horas_de_lista(p: Programa, list_id: str, tareas: Sequence[Task], nativas: Iterable[tuple[dt.date, float, str]],
                   historicas: Iterable[tuple[dt.date, float]]) -> list[HoraPrograma]:
    """nativas: (fecha, horas, task_id) que el reporte cuenta en la lista; historicas: (fecha, horas) del saldo del
    Timetracker de la lista. Las historicas van al contrato fijo o por defecto de la lista (o "compartido")."""
    lp = p.listas[list_id]
    fases = fase_por_tarea(tareas)
    vista = not lp.solo_consumo
    out = [HoraPrograma(list_id, lp.linea, p.contrato_de(list_id, fases.get(tid)), f, h, CLICKUP, vista,
                        fases.get(tid, "(tarea que ya no está en la lista)"))
           for f, h, tid in nativas]
    out += [HoraPrograma(list_id, HISTORIAL, p.contrato_historico(list_id), f, h, TIMETRACKER, vista)
            for f, h in historicas]
    return out


def _base(p: Programa, corte: dt.date, tipo_corte: str) -> dict:
    return {"corte": corte, "tipo_corte": tipo_corte, "programa": p.id, "programa_nombre": p.nombre,
            "cliente": p.cliente}


def filas_horas(p: Programa, horas: Sequence[HoraPrograma], corte: dt.date, tipo_corte: str,
                responsables: Mapping[str, str]) -> list[dict]:
    """programa_horas: una fila por mes, contrato, linea, lista y origen (solo listas en la vista)."""
    acc: dict[tuple, float] = defaultdict(float)
    for h in horas:
        if h.en_vista and h.fecha <= corte:
            acc[(mes(h.fecha), h.contrato, h.linea, h.list_id, h.origen)] += h.horas
    base = _base(p, corte, tipo_corte)
    return [{**base, "mes": m, "contrato": c, "contrato_nombre": p.nombre_contrato(c), "linea": l,
             "linea_nombre": p.nombre_linea(l), "responsable_linea": "" if l == HISTORIAL else responsables.get(lid, ""),
             "list_id": lid, "origen": o, "hh": round(v, 4)}
            for (m, c, l, lid, o), v in sorted(acc.items())]


def filas_contratos(p: Programa, horas: Sequence[HoraPrograma], corte: dt.date, tipo_corte: str) -> list[dict]:
    """programa_contratos: por contrato y mes, del primer mes con horas (o del inicio del periodo) al ultimo mes del
    periodo (o el del corte). Las horas "compartido" no cuentan en ningun contrato. Meses posteriores al corte: solo
    el plan."""
    base = _base(p, corte, tipo_corte)
    compartidas: dict[dt.date, float] = defaultdict(float)
    for h in horas:
        if h.contrato == COMPARTIDO and h.fecha <= corte:
            compartidas[mes(h.fecha)] += h.horas
    out = []
    for c in p.contratos.values():
        por_mes: dict[dt.date, float] = defaultdict(float)
        for h in horas:
            if h.contrato == c.id and h.fecha <= corte:
                por_mes[mes(h.fecha)] += h.horas
        inicios = [x for x in (min(por_mes, default=None), c.periodo_inicio) if x]
        if not inicios:
            continue
        fin = max(x for x in (mes(corte), c.periodo_fin) if x)
        ritmo, total = c.ritmo, c.hh_total_periodo
        acum = acum_periodo = 0.0
        for m in serie_meses(min(inicios), fin):
            futuro = m > mes(corte)
            en_periodo = bool(c.periodo_inicio and c.periodo_fin and mes(c.periodo_inicio) <= m <= mes(c.periodo_fin))
            hh = None if futuro else round(por_mes.get(m, 0.0), 4)
            if not futuro:
                acum += hh
                if c.periodo_inicio and m >= mes(c.periodo_inicio):
                    acum_periodo += hh
            k = meses_entre(c.periodo_inicio, m) if c.periodo_inicio and m >= mes(c.periodo_inicio) else 0
            plan_acum = (min(k, c.meses_periodo) * ritmo) if ritmo and c.meses_periodo and k else None
            out.append({**base, "contrato": c.id, "contrato_nombre": c.nombre, "codigo": c.codigo, "mes": m,
                        "en_periodo": en_periodo, "es_futuro": futuro, "hh_mes": hh,
                        "hh_acum": None if futuro else round(acum, 4),
                        "hh_acum_periodo": None if futuro or not (c.periodo_inicio and m >= mes(c.periodo_inicio))
                        else round(acum_periodo, 4),
                        "hh_plan_mes": round(ritmo, 4) if ritmo and en_periodo else None,
                        "hh_plan_acum": round(plan_acum, 4) if plan_acum is not None else None,
                        "hh_periodo": total, "meses_periodo": c.meses_periodo, "periodo_inicio": c.periodo_inicio,
                        "periodo_fin": c.periodo_fin,
                        "pct_consumido": round(acum_periodo / total, 6) if total and not futuro
                        and c.periodo_inicio and m >= mes(c.periodo_inicio) else None,
                        "hh_compartidas_mes": None if futuro else round(compartidas.get(m, 0.0), 4),
                        "hh_compartidas_acum": None if futuro
                        else round(sum(v for k, v in compartidas.items() if k <= m), 4)})
    return out


def compartidas_por_fase(horas: Sequence[HoraPrograma], corte: dt.date) -> dict[tuple[str, str], float]:
    """(list_id, fase) -> horas "compartido" hasta el corte (origen de la advertencia de nivel programa)."""
    out: dict[tuple[str, str], float] = defaultdict(float)
    for h in horas:
        if h.contrato == COMPARTIDO and h.fecha <= corte:
            out[(h.list_id, h.fase)] += h.horas
    return dict(out)


# --- Entregables --------------------------------------------------------------------------------

def situacion(cerrada: bool, due: dt.date | None, hecho: dt.date | None, corte: dt.date) -> tuple[str, int | None]:
    """(situacion, dias de atraso) de un entregable frente a su fecha de entrega, al corte."""
    if due is None:
        return SIN_FECHA, None
    if cerrada:
        if hecho is None:
            return CERRADO_SIN_FECHA, None
        return (A_TIEMPO, 0) if hecho <= due else (ATRASADO, (hecho - due).days)
    return (VENCIDO, (corte - due).days) if due < corte else (PENDIENTE, None)


def filas_entregables(p: Programa, list_id: str, tareas: Sequence[Task], corte: dt.date, tipo_corte: str,
                      responsable: str) -> list[dict]:
    lp = p.listas[list_id]
    if lp.solo_consumo or not p.entregables or lp.linea in p.entregables_excluir_lineas:
        return []
    fases = fase_por_tarea(tareas)
    base = _base(p, corte, tipo_corte)
    por_id = {t.id: t for t in tareas}
    tipo_de = {t.id: next((k for k, rx in p.entregables.items() if rx.search(t.name or "")), None) for t in tareas}

    def dentro_de_otro(t: Task) -> bool:
        """Algun ancestro es un entregable del mismo tipo (p. ej. un RD diario dentro del paquete mensual)."""
        x, vistos = t, set()
        while x.parent in por_id and x.parent not in vistos:
            vistos.add(x.parent)
            x = por_id[x.parent]
            if tipo_de[x.id] == tipo_de[t.id]:
                return True
        return False

    out = []
    for t in tareas:
        tipo = tipo_de[t.id]
        if tipo is None or dentro_de_otro(t):
            continue
        due = t.due_date
        hecho = t.date_done.date() if t.date_done else None
        sit, atraso = situacion(t.cerrada, due, hecho, corte)
        c = p.contrato_de(list_id, fases.get(t.id))
        out.append({**base, "contrato": c, "contrato_nombre": p.nombre_contrato(c), "linea": lp.linea,
                    "linea_nombre": p.nombre_linea(lp.linea), "responsable_linea": responsable, "list_id": list_id,
                    "task_id": t.id, "tipo_entregable": tipo, "frecuencia": p.frecuencias.get(tipo, EVENTO),
                    "nombre": t.name.strip(), "fase": fases.get(t.id, ""),
                    "estado": t.status, "fecha_entrega": due, "fecha_cierre": hecho,
                    "mes": mes(due or hecho) if (due or hecho) else None, "situacion": sit, "dias_atraso": atraso,
                    "url": t.url})
    return out



@dataclass(frozen=True)
class Limpieza:
    """Un entregable que Administracion DEP debe revisar en ClickUp (run.filas_programa la convierte en advertencia)."""
    tipo: str               # plantilla / duplicado / fecha (proyecto.ADV_ENTREGABLE_*)
    list_id: str
    task_id: str
    tarea: str
    detalle: str
    datos: dict


def revisar_entregables(p: Programa, filas: Sequence[dict]) -> list[Limpieza]:
    """Plantillas sin usar (abiertas, con "N°x" en el nombre), codigos repetidos en una lista y un contrato (sin
    contar las plantillas) y cierres mas de dias_cierre_anticipado antes de la fecha de entrega."""
    out = []
    plantillas = {f["task_id"] for f in filas if f["situacion"] in ABIERTAS and p.patron_plantilla.search(f["nombre"])}
    for f in filas:
        if f["task_id"] in plantillas:
            out.append(Limpieza("plantilla", f["list_id"], f["task_id"], f["nombre"],
                                f"{f['nombre']}: plantilla sin usar ({f['situacion']})",
                                {"situacion": f["situacion"], "fecha_entrega": f["fecha_entrega"]}))
    grupos: dict[tuple, list[dict]] = defaultdict(list)
    for f in filas:
        m = CODIGO_ENTREGABLE.match(f["nombre"])
        if m and f["task_id"] not in plantillas:
            grupos[(f["list_id"], f["contrato"], m.group(1).upper())].append(f)
    for (lid, contrato, codigo), fs in sorted(grupos.items()):
        if len(fs) > 1:
            nombres = [x["nombre"] for x in fs]
            out.append(Limpieza("duplicado", lid, "", codigo, f"{codigo} repetido en el contrato {contrato}: "
                                + "; ".join(nombres),
                                {"codigo": codigo, "contrato": p.nombre_contrato(contrato), "nombres": nombres}))
    for f in filas:
        due, hecho = f["fecha_entrega"], f["fecha_cierre"]
        if due and hecho and (due - hecho).days > p.dias_cierre_anticipado:
            out.append(Limpieza("fecha", f["list_id"], f["task_id"], f["nombre"],
                                f"{f['nombre']}: cerrado el {hecho}, {(due - hecho).days} días antes de su entrega {due}",
                                {"fecha_cierre": hecho, "fecha_entrega": due, "dias": (due - hecho).days}))
    return out
