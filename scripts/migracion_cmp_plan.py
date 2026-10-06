"""Migracion del programa CMP-SHM, etapa 1: inventario y plan. Solo lectura (no escribe en ClickUp).

Reglas: propuesta.md ("Migracion paso a paso"). Una fila por tarea de nivel 0 y 1 de las 4 listas activas, mas
las tareas de nivel >= 2 con contrato en el nombre dentro de las fases generales (se deciden una a una).

Uso:
    python scripts/migracion_cmp_plan.py                     # descarga de ClickUp
    python scripts/migracion_cmp_plan.py --desde-json X.json # reusa una descarga (lista -> info/tasks/time_entries)

Genera en reportes/migracion_cmp/:
    plan.csv                  el plan, fila por tarea
    totales.csv               horas por lista antes de la migracion y las esperadas despues
    horas_por_tarea.csv       foto de horas por tarea (para verificar despues tarea a tarea)
    operaciones_manuales.md   lo que la API no hace y el orden de la sesion
    crudo_<fecha>.json        la descarga usada
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dep_clickup import ClickUpClient  # noqa: E402
from dep_clickup.client import parse_task  # noqa: E402
from dep_reportes.adaptador_clickup import CAMPO_HH  # noqa: E402
from dep_reportes.estructura import NUMERADA, PORCION, clasificar  # noqa: E402

SALIDA = ROOT / "reportes" / "migracion_cmp"
DESDE = dt.date(2024, 1, 1)

GENERAL, INFORMES, MODELOS = "CMP-SHM General", "CMP-SHM Informes", "CMP-SHM Modelos"
MLC, APILADOR, ADMIN, DESARROLLO = "MLC 0019", "Apilador 0147", "00 Administración", "Desarrollo general"
L0019, L0147, LINF, LMOD = "901326875156", "901327109633", "901327788557", "901327789240"
LISTAS = {L0019: "0019", L0147: "0147", LINF: "Informes", LMOD: "Modelos"}
DESTINO_LISTA = {L0019: GENERAL, L0147: GENERAL, LINF: INFORMES, LMOD: MODELOS}

PLANTILLA_VT = re.compile(r"N[°º]\s*[a-z]\b")            # config/programas.json: patron_plantilla
VT = re.compile(r"^\s*VT-\d", re.I)
CONTRATO_0019 = re.compile(r"0019|MLC|Colorados", re.I)  # config/programas.json: patron_fase
CONTRATO_0147 = re.compile(r"0147|Apilador", re.I)
CERRADO = {"completado", "cancelado", "no aplica", "facturado"}
EN_CURSO = {"en progreso", "en revisión", "aceptado"}
DIAS_CIERRE_ANTICIPADO = 30                               # config/programas.json: dias_cierre_anticipado

COLUMNAS = ["list_id", "lista_actual", "task_id", "nombre", "nivel", "padre_id", "padre", "estado", "hh_presupuestadas",
            "time_estimate_h", "fecha_inicio", "fecha_entrega", "horas_propias", "horas_con_subtareas",
            "n_porciones", "lista_destino", "fase_destino", "accion", "motivo", "url"]


def descargar() -> dict:
    cu = ClickUpClient()
    out = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "listas": {}}
    for lid in LISTAS:
        out["listas"][lid] = {
            "info": cu.get_list(lid),
            "tasks": cu.list_tasks_raw(lid),
            "time_entries": cu.list_time_entries_raw(DESDE, dt.date.today() + dt.timedelta(days=366), list_id=lid),
        }
    return out


def h(x: float) -> str:
    return f"{x:.2f}"


def contrato_en(nombre: str) -> str | None:
    a, b = bool(CONTRATO_0019.search(nombre)), bool(CONTRATO_0147.search(nombre))
    return MLC if a and not b else APILADOR if b and not a else "ambos" if a and b else None


class Lista:
    def __init__(self, lid: str, crudo: dict):
        self.id, self.nombre = lid, crudo["info"]["name"]
        self.tareas = [parse_task(t, lid) for t in crudo["tasks"]]
        self.por_id = {t.id: t for t in self.tareas}
        self.hijos: dict[str, list] = collections.defaultdict(list)
        for t in self.tareas:
            if t.parent in self.por_id:
                self.hijos[t.parent].append(t)
        orden = {t["id"]: float(t.get("orderindex") or 0) for t in crudo["tasks"]}
        for k in self.hijos:
            self.hijos[k].sort(key=lambda t: orden[t.id])
        self.raices = sorted((t for t in self.tareas if t.parent not in self.por_id), key=lambda t: orden[t.id])
        self.horas: collections.Counter[str] = collections.Counter()
        self.entradas = [e for e in crudo["time_entries"] if int(e.get("duration") or 0) >= 0]
        for e in self.entradas:
            self.horas[(e.get("task") or {}).get("id", "")] += int(e["duration"]) / 3_600_000
        self.clases = clasificar(self.tareas)

    def total(self) -> float:
        return sum(self.horas.values())

    def desc(self, tid: str):
        for k in self.hijos.get(tid, []):
            yield k
            yield from self.desc(k.id)

    def sub(self, tid: str) -> float:
        return self.horas[tid] + sum(self.horas[k.id] for k in self.desc(tid))

    def porciones(self, tid: str) -> int:
        return sum(1 for k in self.desc(tid) if self.clases[k.id].tipo == PORCION)

    def nivel(self, t) -> int:
        n = 0
        while t.parent in self.por_id:
            t, n = self.por_id[t.parent], n + 1
        return n

    def en_curso(self, tid: str) -> list:
        """Subarbol (incluida la tarea) con estado en curso."""
        return [x for x in [self.por_id[tid], *self.desc(tid)] if x.status.lower() in EN_CURSO]

    def fila(self, t, lista_destino: str, fase_destino: str, accion: str, motivo: str) -> dict:
        padre = self.por_id.get(t.parent)
        return {
            "list_id": self.id, "lista_actual": LISTAS[self.id], "task_id": t.id, "nombre": t.name,
            "nivel": self.nivel(t), "padre_id": padre.id if padre else "", "padre": padre.name if padre else "",
            "estado": t.status, "hh_presupuestadas": t.cf(CAMPO_HH, ""),
            "time_estimate_h": h(t.time_estimate_h) if t.time_estimate_h else "",
            "fecha_inicio": t.start_date or "", "fecha_entrega": t.due_date or "",
            "horas_propias": h(self.horas[t.id]), "horas_con_subtareas": h(self.sub(t.id)),
            "n_porciones": self.porciones(t.id), "lista_destino": lista_destino, "fase_destino": fase_destino,
            "accion": accion, "motivo": motivo, "url": t.url,
        }


def es_plantilla_vt(t) -> bool:
    return bool(VT.match(t.name) and PLANTILLA_VT.search(t.name))


def hijo_de_fase_plantilla(L: Lista, t, fase_contrato: str, archivar_con: str) -> tuple[str, str, str, str]:
    """(lista_destino, fase_destino, accion, motivo) de un hijo de una fase de plantilla que no se mueve entera."""
    sub = L.sub(t.id)
    if es_plantilla_vt(t):
        abiertas = [x.name for x in L.desc(t.id) if x.status.lower() not in CERRADO | {"to do"}]
        cerradas = [x.name for x in L.desc(t.id) if x.status.lower() in CERRADO]
        nota = ""
        if abiertas or cerradas:
            nota = f"; ojo: se borran con ella {len(list(L.desc(t.id)))} subtareas, " \
                   f"incluidas {', '.join(sorted(set(abiertas + cerradas)))} con estado distinto de 'to do'"
        return "", "", "eliminar", f"plantilla VT sin usar ({h(sub)} h){nota}"
    if VT.match(t.name):
        return GENERAL, fase_contrato, "mover", f"visita VT ({h(sub)} h)"
    if sub > 0:
        return GENERAL, fase_contrato, "mover", f"tiene {h(sub)} h registradas"
    curso = L.en_curso(t.id)
    if curso:
        return "", "", "decidir", (f"0 h pero con trabajo en curso ({'; '.join(f'{x.name} [{x.status}]' for x in curso)}): "
                                   f"mover a {fase_contrato} o a la lista de su línea antes de archivar la fase")
    if NUMERADA.match(t.name):
        return "", "", "archivar", f"ítem de plantilla sin horas ni trabajo en curso; se archiva con {archivar_con}"
    return "", "", "decidir", f"tarea fuera de plantilla, 0 h ({t.status}); ¿{fase_contrato} o archivar?"


def plan_0019(L: Lista) -> list[dict]:
    filas = []
    for f in L.raices:
        sub = L.sub(f.id)
        if f.name.startswith("00 Administración"):
            filas.append(L.fila(f, GENERAL, ADMIN, "mantener",
                                f"gestión del programa; {h(L.horas[f.id])} h propias (incluye historial importado)"))
            for k in L.hijos.get(f.id, []):
                filas.append(L.fila(k, GENERAL, ADMIN, "mantener", "porción semanal de administración"))
        elif f.name.startswith("05 Reportes"):
            filas.append(L.fila(f, GENERAL, "", "cerrar",
                                f"propuesta paso 3: informes solo en la lista Informes; sus {h(sub)} h se quedan "
                                f"y cuentan en 0019"))
            for k in L.hijos.get(f.id, []):
                curso = [x for x in [k, *L.desc(k.id)] if x.status.lower() not in CERRADO]
                if k.status.lower() in CERRADO and not curso:
                    filas.append(L.fila(k, GENERAL, "", "cerrar", f"ya cerrada; {h(L.sub(k.id))} h se quedan"))
                elif k.status.lower() in CERRADO:
                    filas.append(L.fila(k, GENERAL, "", "cerrar",
                                        f"cerrada, con {len(curso)} subtarea(s) abiertas sin horas: cerrarlas con ella; "
                                        f"{h(L.sub(k.id))} h se quedan"))
                else:
                    ult = max((x.due_date for x in [k, *L.desc(k.id)] if x.due_date), default=None)
                    filas.append(L.fila(k, "", "", "decidir",
                                        f"trabajo abierto ({h(L.sub(k.id))} h, {L.porciones(k.id)} porciones, "
                                        f"última hasta {ult}); cerrar la fase lo corta. ¿Cerrar y seguir en Modelos/General "
                                        f"MLC 0019, o mover el pendiente?"))
        elif VT.match(f.name) and not es_plantilla_vt(f):
            filas.append(L.fila(f, GENERAL, MLC, "mover", f"visita VT de 0019 ({h(sub)} h); pasa a subtarea de {MLC}"))
            for k in L.hijos.get(f.id, []):
                filas.append(L.fila(k, GENERAL, MLC, "mover", "va con su visita"))
        else:  # fases de plantilla
            filas.extend(fase_plantilla(L, f, MLC, "la fase"))
    return filas


def fase_plantilla(L: Lista, f, fase_contrato: str, archivar_con: str) -> list[dict]:
    hijos = [(k, *hijo_de_fase_plantilla(L, k, fase_contrato, archivar_con)) for k in L.hijos.get(f.id, [])]
    sale = [k.name for k, _, _, acc, _ in hijos if acc in ("mover", "decidir", "eliminar")]
    if L.horas[f.id] > 0:
        cab = L.fila(f, GENERAL, fase_contrato, "mover",
                     f"fase de plantilla con {h(L.horas[f.id])} h propias: se mueve entera (con sus subtareas) "
                     f"para no dejar horas en una fase archivada")
        return [cab] + [L.fila(k, GENERAL, fase_contrato, "mover", "va con su fase") for k, *_ in hijos]
    if not hijos or not sale:
        motivo = "fase de plantilla sin tareas, 0 h" + (" (solo ítems de plantilla)" if hijos else "")
    else:
        motivo = f"fase de plantilla, 0 h; archivar después de resolver: {'; '.join(sale)}"
    if L.id == L0147:
        motivo += "; se archiva con la lista 0147"
    out = [L.fila(f, "", "", "archivar", motivo)]
    out += [L.fila(k, ld, fd, acc, mot) for k, ld, fd, acc, mot in hijos]
    return out


def plan_0147(L: Lista) -> list[dict]:
    filas = []
    for f in L.raices:
        sub = L.sub(f.id)
        if VT.match(f.name) and not es_plantilla_vt(f):
            filas.append(L.fila(f, GENERAL, APILADOR, "mover", f"visita VT de 0147 ({h(sub)} h); pasa a subtarea de {APILADOR}"))
            filas += [L.fila(k, GENERAL, APILADOR, "mover", "va con su visita") for k in L.hijos.get(f.id, [])]
        elif sub > 0:
            nota = {"04": "; por contenido es de Modelos (modelación), revisar si corresponde a esa lista",
                    }.get(f.name[:2], "")
            filas.append(L.fila(f, GENERAL, APILADOR, "mover",
                                f"tiene {h(sub)} h ({h(L.horas[f.id])} propias); se mueve entera{nota}"))
            for k in L.hijos.get(f.id, []):
                nota_k = ("; es un informe: según la propuesta los informes van en Informes"
                          if "Informe" in k.name and L.sub(k.id) > 0 else "")
                filas.append(L.fila(k, GENERAL, APILADOR, "mover", f"va con su fase{nota_k}"))
        else:
            filas.extend(fase_plantilla(L, f, APILADOR, "la lista 0147"))
    return filas


def fase_contrato_de(nombre: str) -> str | None:
    if nombre.startswith("PJ-2025.0019 "):
        return MLC
    if nombre.startswith("PJ-2025.0147 "):
        return APILADOR
    return None


def contratos_en_subarbol(L: Lista, f) -> list:
    """Tareas de nivel >= 2 con contrato en el nombre; solo la mas alta de cada rama (las de abajo van con ella)."""
    def ancestro_con_contrato(x) -> bool:
        p = L.por_id.get(x.parent)
        while p and L.nivel(p) >= 2:
            if contrato_en(p.name):
                return True
            p = L.por_id.get(p.parent)
        return False
    return [x for x in L.desc(f.id) if L.nivel(x) >= 2 and contrato_en(x.name) and not ancestro_con_contrato(x)]


def plan_linea(L: Lista) -> list[dict]:
    filas, lista = [], DESTINO_LISTA[L.id]
    for f in L.raices:
        sub, fc = L.sub(f.id), fase_contrato_de(f.name)
        if fc:
            filas.append(L.fila(f, lista, fc, "mantener", f"fase de contrato: renombrar a '{fc}' ({h(sub)} h)"))
            for k in L.hijos.get(f.id, []):
                filas.append(L.fila(k, lista, fc, "mantener", nota_hijo_contrato(L, k, fc)))
        elif f.name.startswith("PJ-2025.0147/.0019"):
            filas.append(L.fila(f, lista, "", "decidir",
                                f"'Visitas compartidas' ({h(sub)} h): se separa por contrato; decidir tarea por tarea y "
                                f"cerrar la fase vacía"))
            for k in L.hijos.get(f.id, []):
                filas.append(L.fila(k, lista, "", "decidir", nota_visita(k, L)))
        elif f.name.startswith("Tareas Generales") and L.id == LMOD:
            filas.append(L.fila(f, lista, DESARROLLO, "mantener",
                                f"renombrar a '{DESARROLLO}' (única fase compartida, {h(sub)} h)"))
            for k in L.hijos.get(f.id, []):
                c = contrato_en(k.name)
                if c:
                    filas.append(L.fila(k, lista, "", "decidir", f"contrato en el nombre ({c}); ¿{c} o {DESARROLLO}?"))
                else:
                    hijos_c = [x.name for x in L.desc(k.id) if contrato_en(x.name)]
                    extra = f"; tiene subtareas con contrato en el nombre: {'; '.join(hijos_c)} (filas de nivel 2)" if hijos_c else ""
                    filas.append(L.fila(k, lista, DESARROLLO, "mantener", f"sirve a ambos modelos{extra}"))
            for x in contratos_en_subarbol(L, f):
                c = contrato_en(x.name)
                filas.append(L.fila(x, lista, "", "decidir",
                                    f"contrato en el nombre ({c}, {h(L.sub(x.id))} h): ¿mover a {c} o queda en {DESARROLLO}?"))
        elif f.name.startswith("Tareas Generales"):
            filas.append(L.fila(f, lista, "", "decidir",
                                f"fase general fuera de Modelos ({h(sub)} h); la propuesta no admite tareas generales "
                                f"sin contrato fuera de Modelos"))
            for k in L.hijos.get(f.id, []):
                filas.append(L.fila(k, lista, "", "decidir",
                                    f"{h(L.sub(k.id))} h, porción {k.start_date}→{k.due_date}: ¿asignar a un contrato, "
                                    f"mover a Modelos/{DESARROLLO} o a General/{ADMIN}?"))
        elif f.name.startswith("00 Administración"):
            filas.append(L.fila(f, lista, "", "decidir",
                                f"00 Administración existe solo en General según la propuesta; esta está vacía "
                                f"({h(sub)} h, {len(L.hijos.get(f.id, []))} subtareas): sugerido archivar"))
        else:
            filas.append(L.fila(f, lista, "", "decidir", f"fase no prevista en la propuesta ({h(sub)} h)"))
            filas += [L.fila(k, lista, "", "decidir", "sigue a su fase") for k in L.hijos.get(f.id, [])]
    return filas


def nota_hijo_contrato(L: Lista, k, fc: str) -> str:
    nombres = collections.Counter(x.name.split(" Informe")[0].strip() for x in L.hijos.get(k.id, []) if x.name.startswith("IM-"))
    rep = [n for n, c in nombres.items() if c > 1]
    nota = f"agrupador en {fc} ({h(L.sub(k.id))} h)"
    if rep:
        nota += f"; código IM repetido: {', '.join(rep)} (propuesta paso 5)"
    for x in L.hijos.get(k.id, []):
        if x.cerrada and x.date_done and x.due_date and (x.due_date - x.date_done.date()).days > DIAS_CIERRE_ANTICIPADO:
            nota += (f"; {x.name} cerrado el {x.date_done.date()}, {(x.due_date - x.date_done.date()).days} días antes "
                     f"de su entrega ({x.due_date}): corregir fecha (propuesta paso 5)")
    return nota


def nota_visita(k, L: Lista) -> str:
    m = re.search(r"Fecha\s+([\d/]+)", k.name)
    base = f"{h(L.sub(k.id))} h; visita del {m.group(1) if m else '?'}"
    c = contrato_en(k.name)
    sugerida = c or ("MLC 0019 (en 0019 la visita se llama 'Levantamiento Láser MLC')" if "Láser" in k.name else None)
    if sugerida:
        return f"{base}; ¿{sugerida}? Si fue conjunta: duplicar y repartir porciones"
    return f"{base}; contrato no se deduce del nombre (en esas fechas hubo terreno en 0019 y 0147): " \
           f"¿MLC 0019, Apilador 0147 o duplicar?"


# Decisiones de la sesion (Ale con los responsables, 06-10-2026). task_id -> (lista_destino, fase_destino, accion, motivo).
# Regla general: toda tarea compartida historica va entera al contrato 0019 (sin duplicar ni editar entradas).
DECISIONES: dict[str, tuple[str, str, str, str]] = {
    "86ajfx79w": (MODELOS, MLC, "mover", "decisión 1: Definición Curvas de Fragilidad va a Modelos con sus porciones"),
    "86ak12wr5": (GENERAL, MLC, "mover", "decisión 2: Alertas de Monitoreo es operación de 0019"),
    "86ahr82ux": (MODELOS, MLC, "mover", "decisión 3: paquete con su fecha de entrega; sin HH hasta que Felipe las "
                                         "entregue"),
    "86agx8xgr": ("", "", "archivar", "consecuencia de la decisión 3: sin 8.1.b queda solo plantilla; se archiva con "
                                      "07 Entrega Cliente"),
    "86ajem9dp": (INFORMES, MLC, "mover", "decisión 4: visita de ambos contratos; compartida histórica va entera a 0019, "
                                          "con sus horas (no se duplica ni se editan entradas)"),
    "86ak0y125": (INFORMES, "", "cerrar", "decisión 5: 0 h; ya está completada, queda en la fase Informes Visitas cerrada"),
    "86ak4p75z": (INFORMES, MLC, "mover", "decisión 6: es el informe de la visita (no la visita); va a Informes, MLC 0019"),
    "86akprtvm": (INFORMES, "", "cerrar", "decisión 7: porción de 0 h, no se hizo"),
    "86akpru2k": (INFORMES, "", "cerrar", "decisión 8: porción de 0 h, no se hizo"),
    "86ajud6pq": (INFORMES, "", "cerrar", "consecuencia de las decisiones 4-6: la fase queda vacía de trabajo"),
    "86akprtrp": (INFORMES, "", "cerrar", "consecuencia de las decisiones 7-8: la fase queda solo con porciones cerradas"),
    "86ajenaam": ("", "", "archivar", "decisión 9: 00 Administración existe solo en General (archivar a mano)"),
    "86ajfv2hx": (MODELOS, APILADOR, "mover", "decisión 10: B.1 es del modelo Apilador"),
    "86ajfvf3r": (MODELOS, MLC, "mover", "decisión 11: B.2 es de los modelos MLC"),
    "86ahaa2wf": (INFORMES, APILADOR, "mover", "decisión 12: es un informe; va a Informes, Apilador 0147"),
    "86ahrpy00": (MODELOS, APILADOR, "mover", "decisión 13: modelación; va a Modelos, Apilador 0147, con sus subtareas"),
}
# Motivo nuevo de filas cuyo contexto cambio con las decisiones.
MOTIVOS = {
    "86agx8xej": "fase de plantilla, 0 h; archivar después de sacar 8.1.b (decisión 3)",
}


def aplicar_decisiones(L: dict[str, Lista], filas: list[dict]) -> list[dict]:
    por_id = {f["task_id"]: f for f in filas}
    for tid, (ld, fd, acc, mot) in DECISIONES.items():
        if tid not in por_id:      # tareas de nivel >= 2 que no estaban en el plan (8.1.b)
            x = next(x for x in L.values() if tid in x.por_id)
            por_id[tid] = x.fila(x.por_id[tid], ld, fd, acc, mot)
            padre = por_id.get(por_id[tid]["padre_id"])
            filas.insert(filas.index(padre) + 1 if padre else len(filas), por_id[tid])
        f = por_id[tid]
        f.update(lista_destino=ld, fase_destino=fd, accion=acc, motivo=mot)
    for tid, mot in MOTIVOS.items():
        por_id[tid]["motivo"] = mot
    # Las filas que "van con su padre" siguen el destino nuevo del padre.
    for f in filas:
        p = por_id.get(f["padre_id"])
        if p and f["padre_id"] in DECISIONES and f["motivo"].startswith("va con su") and p["accion"] == "mover":
            f.update(lista_destino=p["lista_destino"], fase_destino=p["fase_destino"])
    pendientes = [f for f in filas if f["accion"] == "decidir"]
    if pendientes:
        raise SystemExit("Filas 'decidir' sin decisión: " + "; ".join(f"{f['task_id']} {f['nombre']}" for f in pendientes))
    return filas


def destino_de_horas(L: dict[str, Lista], filas: list[dict]) -> dict[str, float]:
    """Horas por lista despues de migrar: cada tarea con horas va con el ancestro mas cercano que se mueve."""
    mueve = {f["task_id"]: f["lista_destino"] for f in filas if f["accion"] == "mover"}
    out: collections.Counter[str] = collections.Counter()
    for lid, x in L.items():
        for tid, hrs in x.horas.items():
            t, dest = x.por_id.get(tid), None
            while t is not None and dest is None:
                dest = mueve.get(t.id)
                t = x.por_id.get(t.parent)
            out[dest or ("0147 (archivada)" if lid == L0147 else DESTINO_LISTA[lid])] += hrs
    return out


def escribir_csv(ruta: Path, columnas: list[str], filas: list[dict]) -> None:
    with ruta.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--desde-json", type=Path)
    a = ap.parse_args()
    SALIDA.mkdir(parents=True, exist_ok=True)
    crudo = json.loads(a.desde_json.read_text(encoding="utf-8")) if a.desde_json else descargar()
    hoy = crudo.get("generado", dt.datetime.now().isoformat())[:10]
    if not a.desde_json:
        (SALIDA / f"crudo_{hoy}.json").write_text(json.dumps(crudo, ensure_ascii=False), encoding="utf-8")
    L = {lid: Lista(lid, crudo["listas"][lid]) for lid in LISTAS}

    filas = plan_0019(L[L0019]) + plan_0147(L[L0147]) + plan_linea(L[LINF]) + plan_linea(L[LMOD])
    filas = aplicar_decisiones(L, filas)
    escribir_csv(SALIDA / "plan.csv", COLUMNAS, filas)

    # Horas por tarea: cada hora de la lista pertenece a una sola tarea. Se usa para verificar despues.
    foto = []
    for lid, x in L.items():
        for tid, hrs in sorted(x.horas.items()):
            t = x.por_id.get(tid)
            foto.append({"list_id": lid, "lista_actual": LISTAS[lid], "task_id": tid, "nombre": t.name if t else "",
                         "horas": h(hrs), "entradas": sum(1 for e in x.entradas if (e.get("task") or {}).get("id") == tid)})
    escribir_csv(SALIDA / "horas_por_tarea.csv", ["list_id", "lista_actual", "task_id", "nombre", "horas", "entradas"], foto)

    # Totales: antes por lista, y esperados despues por lista destino (General = 0019 + 0147, que se archiva vacia).
    tot = []
    for lid, x in L.items():
        raices = sum(x.sub(t.id) for t in x.raices)
        assert abs(raices - x.total()) < 1e-6, f"{lid}: horas fuera del arbol de tareas"
        tot.append({"momento": "antes", "lista": LISTAS[lid], "list_id": lid, "nombre_clickup": x.nombre,
                    "horas": h(x.total()), "entradas": len(x.entradas), "tareas": len(x.tareas)})
    esperado = destino_de_horas(L, filas)
    assert abs(sum(esperado.values()) - sum(x.total() for x in L.values())) < 1e-6
    for lista, lid in ((GENERAL, L0019), (INFORMES, LINF), (MODELOS, LMOD), ("0147 (archivada)", L0147)):
        tot.append({"momento": "despues_esperado", "lista": lista, "list_id": lid,
                    "nombre_clickup": lista if lid != L0147 else "", "horas": h(esperado.get(lista, 0)),
                    "entradas": "", "tareas": ""})
    tot.append({"momento": "antes", "lista": "programa", "list_id": "", "nombre_clickup": "4 listas activas",
                "horas": h(sum(x.total() for x in L.values())), "entradas": sum(len(x.entradas) for x in L.values()),
                "tareas": sum(len(x.tareas) for x in L.values())})
    escribir_csv(SALIDA / "totales.csv", ["momento", "lista", "list_id", "nombre_clickup", "horas", "entradas", "tareas"], tot)

    cuenta = collections.Counter((f["lista_actual"], f["accion"]) for f in filas)
    print(f"{len(filas)} filas en {SALIDA / 'plan.csv'}")
    for (lista, acc), n in sorted(cuenta.items()):
        print(f"  {lista:9} {acc:9} {n}")
    for r in tot:
        print(f"  {r['momento']:17} {r['lista']:18} {r['horas']:>9} h")


if __name__ == "__main__":
    main()
