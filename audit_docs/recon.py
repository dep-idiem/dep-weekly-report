"""Reconocimiento documental Drive <-> SS_REGISTRO (Fase 1, solo lectura).

    python -m audit_docs.recon --paso0        # descubrimiento: campos, estados y acceso a Drive
    python -m audit_docs.recon                # inventario + reglas + reporte (Pasos 1 a 3)

Salida en audit_docs/out/ (fuera de git: contiene nombres de personas). Ningun PUT/POST a ClickUp,
ninguna escritura en Drive ni en Sheets: los dos clientes solo tienen GET.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import itertools
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dep_clickup.client import ClickUpClient, ClickUpError, parse_task
from dep_clickup.config import TZ
from dep_clickup.dates import ms_to_local

from google.auth.transport.requests import AuthorizedSession

from .drive import FOLDER, SHORTCUT, DriveClient, DriveError, cargar_credenciales, id_desde_url
from .reglas import Reglas, buscar_subcarpeta, codigo_archivo, extension, normalizar

log = logging.getLogger("audit_docs")

SS_REGISTRO = "901324495476"           # Propuestas / MAESTRO / SS_REGISTRO
CAMPO_PR, CAMPO_PJ, CAMPO_JP = "Drive PR URL", "Drive PJ URL", "JP Responsable"
OUT = Path(__file__).resolve().parent / "out"
RUTA_PROPUESTAS = "DEP - CENTRAL / 01 Propuestas"   # ubicacion esperada (unidad compartida / carpeta)


# --- ClickUp ------------------------------------------------------------------------------------

def descubrir_clickup(cu: ClickUpClient, list_id: str = SS_REGISTRO) -> dict:
    info = cu.get_list(list_id)
    campos = cu.get(f"/list/{list_id}/field").get("fields", [])
    raw = cu.list_tasks_raw(list_id, include_subtasks=True, include_closed=True)
    principales = [t for t in raw if not t.get("parent")]
    # Campos con link de Drive: tipo url o cualquier texto que contenga drive.google.com.
    con_drive: dict[str, dict] = {}
    for f in campos:
        con_drive.setdefault(f["name"], {"tipo": f["type"], "con_drive": 0, "con_valor": 0, "id": f["id"]})
    for t in principales:
        for f in t.get("custom_fields", []):
            v = f.get("value")
            if v not in (None, "", []):
                con_drive[f["name"]]["con_valor"] += 1
                if isinstance(v, str) and "drive.google.com" in v:
                    con_drive[f["name"]]["con_drive"] += 1
    campos_drive = {k: v for k, v in con_drive.items() if v["con_drive"] or (v["tipo"] == "url" and "drive" in k.lower())}
    dropdowns = {f["name"]: [o.get("name") for o in (f.get("type_config") or {}).get("options", [])]
                 for f in campos if f["type"] == "drop_down" and any(w in f["name"].lower() for w in ("estado", "status"))}
    return {
        "lista": info.get("name"), "list_id": list_id,
        "estados": [(s["status"], s.get("type"), s.get("orderindex")) for s in info.get("statuses", [])],
        "campos": campos, "campos_drive": campos_drive, "dropdowns_estado": dropdowns,
        "raw": raw, "principales": principales, "n_subtareas": len(raw) - len(principales),
    }


def fechas_estado_actual(cu: ClickUpClient, task_ids: list[str]) -> tuple[dict[str, dt.datetime], str | None]:
    """task_id -> desde cuando esta en su estado actual (Time in Status). Error si la API no lo da."""
    out: dict[str, dt.datetime] = {}
    try:
        for i in range(0, len(task_ids), 100):
            data = cu.get("/task/bulk_time_in_status/task_ids", [("task_ids", t) for t in task_ids[i:i + 100]])
            for tid, d in data.items():
                since = ((d or {}).get("current_status") or {}).get("since")
                if since:
                    out[tid] = ms_to_local(since)
    except ClickUpError as e:
        return {}, f"HTTP {e.status}: {e.body[:200]}"
    return out, None


# --- Drive ---------------------------------------------------------------------------------------

RE_SUBCARPETA = re.compile(r"^\d{2}\s")
RE_PROPUESTA = re.compile(r"^(PR-)?\d{4}\.\d{4}")


def carpeta_propuesta(dr: DriveClient, fid: str) -> tuple[dict, str]:
    """Carpeta de la propuesta a la que apunta el link y como apunta: 'carpeta' o 'subcarpeta «06 Backup»'.

    Parte de los links de Make guardan el ID de una subcarpeta (06 Backup) en vez de la carpeta PR:
    si la carpeta enlazada se llama '0N ...' y su padre parece una propuesta, se usa el padre.
    """
    m = dr.resolver_carpeta(fid)
    padres = m.get("parents") or []
    if RE_SUBCARPETA.match(m.get("name", "")) and padres:
        try:
            p = dr.meta(padres[0])
            if RE_PROPUESTA.match(p.get("name", "")):
                return p, f"subcarpeta «{m['name']}»"
        except DriveError:
            pass
    return m, "carpeta"


def ruta(dr: DriveClient, folder_id: str | None, _drives: dict = {}) -> str:
    """'Unidad / carpeta / ...' hasta la raiz (sin incluir la carpeta de la unidad)."""
    partes = []
    while folder_id:
        try:
            m = dr.meta(folder_id)
        except DriveError as e:
            partes.append(f"<{e.status}>")
            break
        padres = m.get("parents") or []
        if not padres:
            did = m.get("driveId")
            if did:
                if did not in _drives:
                    try:
                        _drives[did] = dr._get(f"/drives/{did}", {"fields": "name"})["name"]
                    except DriveError:
                        _drives[did] = f"unidad {did}"
                partes.append(_drives[did])
            else:
                partes.append(m.get("name", "Mi unidad"))
            break
        partes.append(m["name"])
        folder_id = padres[0]
    return " / ".join(reversed(partes))


def descubrir_drive(dr: DriveClient | None, principales: list[dict], error_auth: str | None) -> dict:
    res = {"error_auth": error_auth, "usuario": None, "links_pr": 0, "resueltos": 0, "errores": [],
           "enlaces": collections.Counter(), "ubicaciones": collections.Counter(), "raices": {}}
    if dr is None:
        return res
    try:
        res["usuario"] = dr.about().get("user")
    except DriveError as e:
        res["error_auth"] = str(e)
        return res
    for t in principales:
        fid = id_desde_url(_valor(t, CAMPO_PR))
        if not fid:
            continue
        res["links_pr"] += 1
        try:
            m, enlace = carpeta_propuesta(dr, fid)
        except DriveError as e:
            res["errores"].append((e.status, _valor(t, "SS_CODE") or t["name"][:9], t["status"]["status"]))
            continue
        res["resueltos"] += 1
        res["enlaces"][enlace] += 1
        padre = (m.get("parents") or [None])[0]
        if padre:
            r = ruta(dr, padre)
            res["ubicaciones"][r] += 1
            res["raices"][r] = padre
    res["visibles"] = {r: sum(1 for f in dr.hijos(pid) if f.get("mimeType") in (FOLDER, SHORTCUT)
                              and RE_PROPUESTA.match(f.get("name", ""))) for r, pid in res["raices"].items()}
    return res


def _valor(t: dict, nombre: str):
    for f in t.get("custom_fields", []):
        if f.get("name") == nombre:
            return f.get("value")
    return None


# --- Inventario y reglas -------------------------------------------------------------------------

RE_CODIGO = re.compile(r"(\d{4}\.\d{4})")
RESULTADOS = ["INCOMPLETO", "SIN_CARPETA", "COMPLETO", "NO_APLICA", "FUERA_DE_ALCANCE", "HISTORICA"]


@dataclass
class Sub:
    clave: str
    esperado: str
    carpeta: dict | None = None
    modo: str | None = None
    archivos: list[dict] = field(default_factory=list)       # incluye los de subcarpetas leídas (clave "_en")
    subcarpetas: list[str] = field(default_factory=list)     # subcarpetas leídas (hasta reglas.recursivo)
    ignoradas: list[str] = field(default_factory=list)       # subcarpetas no leídas (OLD, Antiguo...)


@dataclass
class Fila:
    task_id: str
    ss_code: str
    codigo: str | None              # 2026.0157, para buscar la carpeta por nombre
    nombre: str
    estado: str
    estado_pipeline: str | None
    tipo_dep: str
    jp: str
    fecha_creada: dt.datetime | None
    fecha_estado: dt.datetime | None
    fecha_fuente: str
    link_pr: str | None
    link_pj: str | None
    carpeta_encontrada: str = "sin link"        # si / no / sin link
    carpeta_pr: dict | None = None
    enlace: str = ""                            # carpeta / subcarpeta «06 Backup» / por código
    link_obsoleto: bool = False
    encontrada_por_codigo: dict | None = None    # sin link, pero la carpeta existe (informativo)
    ubicacion: str = ""
    error: str | None = None
    subs: dict[str, Sub] = field(default_factory=dict)
    subcarpetas_pr: list[str] = field(default_factory=list)   # primer nivel de la carpeta PR
    otras_subcarpetas: list[str] = field(default_factory=list)
    evaluacion: list[dict] = field(default_factory=list)
    resultado: str = ""
    motivo: str = ""
    observaciones: list[str] = field(default_factory=list)

    @property
    def causa_oferta(self) -> str:
        return next((e["causa"] for e in self.evaluacion if e["aplica"] and e["causa"]), "")

    @property
    def carpetas_vacias(self) -> bool:
        """03 y 04 existen y no tienen ningún archivo (incluidas las subcarpetas leídas)."""
        return bool(self.subs) and all(s.carpeta and not s.archivos for s in self.subs.values())


def indice_por_codigo(dr: DriveClient, raices: dict[str, str]) -> dict[str, list[tuple[str, dict]]]:
    """codigo (2026.0157) -> [(ubicacion, carpeta)] entre los hijos de las ubicaciones conocidas."""
    idx: dict[str, list[tuple[str, dict]]] = collections.defaultdict(list)
    for r, pid in sorted(raices.items()):
        for c in dr.hijos(pid):
            m = RE_CODIGO.search(c.get("name", "")) if c.get("mimeType") in (FOLDER, SHORTCUT) else None
            if m:
                idx[m.group(1)].append((r, c))
    return idx


def _por_codigo(dr: DriveClient, idx: dict, codigo: str | None, reglas: Reglas) -> tuple[dict, str] | None:
    """Carpeta con ese codigo; si hay varias, primero las de ubicaciones en alcance y con prefijo PR-."""
    cand = idx.get(codigo or "", [])
    if not cand:
        return None
    cand = sorted(cand, key=lambda x: (not reglas.ubicacion_en_alcance(x[0]), not x[1]["name"].startswith("PR-")))
    r, c = cand[0]
    try:
        return dr.resolver_carpeta(c["id"]), r
    except DriveError:
        return None


def inventariar(principales: list[dict], dr: DriveClient, reglas: Reglas, fechas: dict,
                idx: dict) -> list[Fila]:
    filas = []
    for t in principales:
        tk = parse_task(t, SS_REGISTRO)
        cf = tk.custom_fields
        val = lambda n: cf[n].value if n in cf else None  # noqa: E731
        ss = val("SS_CODE") or tk.name.split("|")[0].strip()
        m = RE_CODIGO.search(f"{val('PR_CODE') or ''} {ss} {tk.name}")
        f = Fila(task_id=tk.id, ss_code=str(ss), codigo=m.group(1) if m else None, nombre=tk.name,
                 estado=tk.status, estado_pipeline=reglas.estado_pipeline(tk.status), tipo_dep=val("Tipo DEP") or "",
                 jp=", ".join(val(CAMPO_JP) or []), fecha_creada=tk.date_created,
                 fecha_estado=fechas.get(tk.id) or tk.date_updated,
                 fecha_fuente="time_in_status" if tk.id in fechas else "date_updated",
                 link_pr=_valor(t, CAMPO_PR), link_pj=_valor(t, CAMPO_PJ))
        filas.append(f)
        fid = id_desde_url(f.link_pr)
        if not f.link_pr:
            f.carpeta_encontrada = "sin link"
            hallada = _por_codigo(dr, idx, f.codigo, reglas)
            if hallada:
                f.encontrada_por_codigo = {"carpeta": hallada[0], "ubicacion": hallada[1]}
        elif not fid:
            f.carpeta_encontrada, f.error = "no", "link sin ID de Drive"
        else:
            try:
                f.carpeta_pr, f.enlace = carpeta_propuesta(dr, fid)
                if f.carpeta_pr.get("mimeType") != FOLDER:
                    f.carpeta_encontrada, f.error = "no", f"el link apunta a {f.carpeta_pr.get('mimeType')}"
                    f.carpeta_pr = None
                elif f.carpeta_pr.get("trashed"):
                    f.carpeta_encontrada, f.error = "no", "carpeta en la papelera"
                    f.carpeta_pr = None
                else:
                    f.carpeta_encontrada = "si"
            except DriveError as e:
                f.carpeta_encontrada, f.error = "no", f"Drive {e.status}"
            if f.carpeta_encontrada == "no":
                hallada = _por_codigo(dr, idx, f.codigo, reglas)
                if hallada:
                    f.carpeta_pr, f.enlace, f.link_obsoleto = hallada[0], "por código", True
                    f.carpeta_encontrada = "si"
        if f.carpeta_pr:
            f.ubicacion = ruta(dr, (f.carpeta_pr.get("parents") or [None])[0])
            _subcarpetas(f, dr, reglas)
        _clasificar(f, reglas)
    return filas


def _subcarpetas(f: Fila, dr: DriveClient, reglas: Reglas) -> None:
    carpetas = [h for h in dr.hijos(f.carpeta_pr["id"]) if h.get("mimeType") == FOLDER]
    f.subcarpetas_pr = [c["name"] for c in carpetas]
    usadas = set()
    for clave, esperado in reglas.subcarpetas.items():
        s = Sub(clave, esperado)
        s.carpeta, s.modo = buscar_subcarpeta(esperado, carpetas)
        if s.carpeta:
            usadas.add(s.carpeta["id"])
            _leer(s, dr, reglas, s.carpeta["id"], "", reglas.recursivo)
        f.subs[clave] = s
    f.otras_subcarpetas = [c["name"] for c in carpetas if c["id"] not in usadas]


def _leer(s: Sub, dr: DriveClient, reglas: Reglas, folder_id: str, prefijo: str, niveles: int) -> None:
    for h in dr.hijos(folder_id):
        if h.get("mimeType") != FOLDER:
            s.archivos.append({**h, "_en": prefijo} if prefijo else h)
            continue
        nombre = f"{prefijo}/{h['name']}" if prefijo else h["name"]
        if reglas.ignorada(h["name"]):
            s.ignoradas.append(nombre)
        elif niveles > 0:
            s.subcarpetas.append(nombre)
            _leer(s, dr, reglas, h["id"], nombre, niveles - 1)
        else:
            s.subcarpetas.append(nombre + " (no leída)")


def _clasificar(f: Fila, reglas: Reglas) -> None:
    aplicables = {r.id for r in reglas.aplicables(f.estado)}
    for r in reglas.reglas:
        s = f.subs.get(r.subcarpeta)
        ev = r.evaluar(s.archivos if s else [], f.codigo)
        pista = []
        if not (ev["coincidencias"] or ev["por_revisar"]) and r.pista_subcarpeta and f.subs.get(r.pista_subcarpeta):
            # La pista siempre exige el código de la tarea: un PDF cualquiera en 03 no es la oferta.
            pista = [n for n in r.coincidencias(f.subs[r.pista_subcarpeta].archivos) if codigo_archivo(n) == f.codigo]
        cumple = bool(ev["coincidencias"] or ev["por_revisar"])
        # Causa (solo reglas con pista, hoy oferta_enviada): oferta_mal_ubicada / sin_oferta / por_revisar.
        causa = ""
        if r.pista_subcarpeta:
            causa = ("por_revisar" if not ev["coincidencias"] and ev["por_revisar"] else
                     "" if cumple else "oferta_mal_ubicada" if pista else "sin_oferta")
        f.evaluacion.append({"regla": r, "aplica": r.id in aplicables, "nivel": r.nivel,
                             "cumple": cumple, **ev, "pista": pista, "causa": causa})

    # Orden de decision: alcance por tipo -> sin link (historica / sin carpeta) -> link roto -> ubicacion
    # -> estado sin reglas -> reglas.
    if not reglas.tipo_en_alcance(f.tipo_dep):
        f.resultado, f.motivo = "FUERA_DE_ALCANCE", f"Tipo DEP {f.tipo_dep or '(vacío)'}"
    elif f.carpeta_encontrada == "sin link":
        corte, corte_cod = reglas.fecha_inicio_make, reglas.codigo_inicio_make
        if corte and f.fecha_creada and f.fecha_creada.date() < corte:
            f.resultado, f.motivo = "HISTORICA", f"creada antes de {corte.isoformat()}"
        elif corte_cod and f.codigo and f.codigo < corte_cod:
            f.resultado, f.motivo = "HISTORICA", f"código anterior a {corte_cod}"
        else:
            f.resultado, f.motivo = "SIN_CARPETA", "sin link"
    elif f.carpeta_encontrada == "no":
        f.resultado, f.motivo = "SIN_CARPETA", f.error or "link no resuelve"
    elif not reglas.ubicacion_en_alcance(f.ubicacion):
        f.resultado, f.motivo = "FUERA_DE_ALCANCE", f.ubicacion
    elif not aplicables:
        f.resultado = "NO_APLICA"
        f.motivo = f"estado «{f.estado}» sin reglas" if reglas.estado_conocido(f.estado) else f"estado «{f.estado}» sin mapear"
    elif any(e["aplica"] and e["nivel"] == "faltante" and not e["cumple"] for e in f.evaluacion):
        f.resultado = "INCOMPLETO"
    else:
        f.resultado = "COMPLETO"
    for e in f.evaluacion:   # fuera de la evaluacion, ninguna regla "aplica"
        if f.resultado not in ("COMPLETO", "INCOMPLETO"):
            e["aplica"] = False

    if f.link_obsoleto:
        f.observaciones.append(f"LINK_OBSOLETO ({f.error}); carpeta hallada por código")
    elif f.error:
        f.observaciones.append(f.error)
    if f.enlace.startswith("subcarpeta"):
        f.observaciones.append(f"el link apunta a la {f.enlace}")
    if f.encontrada_por_codigo:
        f.observaciones.append(f"sin link, pero existe la carpeta «{f.encontrada_por_codigo['carpeta']['name']}»")
    if f.resultado in ("FUERA_DE_ALCANCE", "HISTORICA"):
        return
    for s in f.subs.values():
        if s.carpeta is None:
            f.observaciones.append(f"falta subcarpeta «{s.esperado}»")
        elif s.modo not in ("exacto", "normalizado"):
            f.observaciones.append(f"subcarpeta «{s.carpeta['name']}» ({s.modo})")
        if s.subcarpetas:
            f.observaciones.append(f"{s.esperado[:2]} con subcarpetas: {', '.join(s.subcarpetas)}")
        if s.ignoradas:
            f.observaciones.append(f"{s.esperado[:2]} ignoradas: {', '.join(s.ignoradas)}")
        nativos = [a["name"] for a in s.archivos if extension(a["name"], a.get("mimeType", "")).startswith("(g")]
        if nativos:
            f.observaciones.append(f"{s.esperado[:2]} con {len(nativos)} archivo(s) nativo(s) de Google (sin extensión)")
    for e in f.evaluacion:
        if not e["aplica"]:
            continue
        if e["por_revisar"]:
            f.observaciones.append(f"{e['regla'].id} por revisar: {', '.join(e['por_revisar'])}")
        if not e["cumple"] and e["nivel"] == "advertencia":
            f.observaciones.append(f"advertencia: {e['regla'].id}")
        if e["pista"]:
            f.observaciones.append(f"{e['regla'].id}: hay {len(e['pista'])} archivo(s) con el código en "
                                   f"{reglas.subcarpetas[e['regla'].pista_subcarpeta][:2]}")
        if e["otro_codigo"] and not e["coincidencias"]:
            f.observaciones.append(f"{e['regla'].id}: solo archivos con otro código: {', '.join(e['otro_codigo'])}")


def huerfanas(dr: DriveClient, raices: dict[str, str], filas: list[Fila]) -> list[tuple[str, dict]]:
    """Carpetas de propuesta (nombre PR-/codigo) en las ubicaciones conocidas que ninguna tarea referencia
    (ni por link ni por codigo)."""
    referenciadas = ({f.carpeta_pr["id"] for f in filas if f.carpeta_pr} | {id_desde_url(f.link_pr) for f in filas}
                     | {f.encontrada_por_codigo["carpeta"]["id"] for f in filas if f.encontrada_por_codigo})
    return [(r, c) for r, pid in sorted(raices.items()) for c in dr.hijos(pid)
            if c.get("mimeType") in (FOLDER, SHORTCUT) and RE_PROPUESTA.match(c.get("name", ""))
            and c["id"] not in referenciadas and (c.get("shortcutDetails") or {}).get("targetId") not in referenciadas]


# --- Reporte -------------------------------------------------------------------------------------

def _md(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def seccion_paso0(cu: dict, drv: dict, reglas: Reglas, error_tis: str | None) -> list[str]:
    L = ["## 1. Paso 0 — Descubrimiento", "",
         f"Lista: **{cu['lista']}** (`{cu['list_id']}`). Tareas leídas: {len(cu['raw'])}, "
         f"de ellas {cu['n_subtareas']} subtareas (ignoradas) → **{len(cu['principales'])} tareas principales**.", "",
         "### Campos con link de Drive", "", "| Campo | Tipo | Con link drive.google.com | Con valor |", "|---|---|---|---|"]
    for k, v in sorted(cu["campos_drive"].items()):
        L.append(f"| {_md(k)} | `{v['tipo']}` | {v['con_drive']} | {v['con_valor']} |")
    L += ["", f"Carpeta de propuesta (PR) = **{CAMPO_PR}**; carpeta de proyecto (PJ) = **{CAMPO_PJ}**.", "",
          "### Estados reales de SS_REGISTRO", "", "| # | Estado | Tipo | Tareas | Mapeado a (rules.yaml) |", "|---|---|---|---|---|"]
    cnt = collections.Counter(t["status"]["status"] for t in cu["principales"])
    for nombre, tipo, oi in cu["estados"]:
        mapeo = reglas.estado_pipeline(nombre) or ("sin reglas" if reglas.estado_conocido(nombre) else "— (sin mapear)")
        L.append(f"| {oi} | `{nombre}` | {tipo} | {cnt.get(nombre, 0)} | {mapeo} |")
    for nombre, opciones in cu["dropdowns_estado"].items():
        L += ["", f"Campo desplegable **{_md(nombre)}** (sub-estado, no es el status): " + ", ".join(f"`{o}`" for o in opciones)]
    L += ["", "Fecha de cambio al estado actual: " + (
        "disponible (Time in Status)." if not error_tis else f"**no disponible** ({_md(error_tis)}); se usa `date_updated`."), "",
          "### Acceso a Drive", ""]
    if drv["error_auth"]:
        L.append(f"**Sin acceso:** {_md(drv['error_auth'])}")
        return L
    u = drv["usuario"] or {}
    L.append(f"Cuenta: {_md(u.get('displayName'))} ({_md(u.get('emailAddress'))}).")
    L.append(f"Links PR con ID: {drv['links_pr']}; resueltos: {drv['resueltos']}; no resuelven: {len(drv['errores'])}.")
    L += ["", "A qué apunta el link (resueltos):", ""] + [f"- {_md(k)}: {v}" for k, v in drv["enlaces"].most_common()]
    L += ["", "Dónde están las carpetas PR:", "", "| Ubicación | Carpetas PR enlazadas | Carpetas de propuesta visibles |", "|---|---|---|"]
    for r, v in drv["ubicaciones"].most_common():
        L.append(f"| {_md(r)} | {v} | {drv['visibles'].get(r, '')} |")
    if drv["errores"]:
        L += ["", "Links que no resuelven: " + ", ".join(f"{_md(ss)} ({est}, HTTP {st})" for st, ss, est in drv["errores"])]
    return L


def escribir_vacias(filas: list[Fila], fecha: dt.date) -> Path:
    """Tareas evaluadas con 03 y 04 vacías, por JP y estado: lista para la reunión."""
    v = sorted((f for f in filas if f.resultado in ("COMPLETO", "INCOMPLETO") and f.carpetas_vacias),
               key=lambda f: (f.jp or "(sin JP)", f.estado, f.ss_code))
    L = [f"# Propuestas con las carpetas 03 y 04 vacías ({fecha.isoformat()})", "",
         f"{len(v)} propuestas de Ingeniería en DEP - CENTRAL / 01 Propuestas, en estados con reglas, sin ningún archivo "
         "en «03 Propuesta Técnica y Económica» ni en «04 Oferta Enviada».", ""]
    for jp, grupo in itertools.groupby(v, key=lambda f: f.jp or "(sin JP)"):
        grupo = list(grupo)
        L += [f"## {_md(jp)} ({len(grupo)})", "", "| Estado | Código | Nombre | Desde |", "|---|---|---|---|"]
        for f in grupo:
            nombre = f.nombre.split("|", 1)[1].strip() if "|" in f.nombre else f.nombre
            L.append(f"| {_md(f.estado)} | {_md(f.ss_code)} | {_md(nombre)} | "
                     f"{f.fecha_estado.date().isoformat() if f.fecha_estado else ''} |")
        L.append("")
    p = OUT / f"vacias_{fecha.isoformat()}.md"
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return p


def escribir_paso0(cu, drv, reglas, error_tis, fecha: dt.date) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"paso0_{fecha.isoformat()}.md"
    L = [f"# Auditoría documental — Paso 0 ({fecha.isoformat()})", ""] + seccion_paso0(cu, drv, reglas, error_tis)
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return p


def _link(fid: str) -> str:
    return f"https://drive.google.com/drive/folders/{fid}"


def _tabla_cruzada(filas: list[Fila], fila_de, col_de, titulo_fila: str) -> list[str]:
    c = collections.Counter((fila_de(f), col_de(f)) for f in filas)
    cols = sorted({k[1] for k in c}, key=str)
    L = [f"| {titulo_fila} | " + " | ".join(_md(x) for x in cols) + " | Total |", "|---" * (len(cols) + 2) + "|"]
    for r in sorted({k[0] for k in c}, key=str):
        L.append(f"| {_md(r)} | " + " | ".join(str(c[(r, x)] or "") for x in cols) + f" | {sum(c[(r, x)] for x in cols)} |")
    return L


def escribir_reporte(cu, drv, reglas, error_tis, filas: list[Fila], orfs: list, fecha: dt.date) -> tuple[Path, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    md, cs = OUT / f"recon_{fecha.isoformat()}.md", OUT / f"recon_{fecha.isoformat()}.csv"
    res = collections.Counter(f.resultado for f in filas)
    evaluadas = [f for f in filas if f.resultado in ("COMPLETO", "INCOMPLETO")]
    en_alcance = [f for f in filas if f.resultado not in ("FUERA_DE_ALCANCE", "HISTORICA")]
    L = [f"# Auditoría documental Drive ↔ SS_REGISTRO — Reconocimiento ({fecha.isoformat()})", "",
         "Solo lectura: ninguna escritura en ClickUp, Drive ni Sheets.", ""]
    L += seccion_paso0(cu, drv, reglas, error_tis)

    # 2. Totales
    L += ["", "## 2. Totales", "",
          f"- Tareas leídas (principales): **{len(filas)}**",
          f"- Con carpeta PR encontrada: {sum(f.carpeta_encontrada == 'si' for f in filas)} "
          f"(de ellas {sum(f.link_obsoleto for f in filas)} por código, con LINK_OBSOLETO)",
          f"- Link que apunta a una subcarpeta en vez de la carpeta PR: {sum(f.enlace.startswith('subcarpeta') for f in filas)}",
          f"- Sin link PR: {sum(f.carpeta_encontrada == 'sin link' for f in filas)}; link que no resuelve y sin carpeta por código: "
          f"{sum(f.carpeta_encontrada == 'no' for f in filas)}",
          f"- Carpetas huérfanas: {len(orfs)}", "",
          "Resultado: " + ", ".join(f"**{r}** {res[r]}" for r in RESULTADOS if res[r]), ""]
    causas = collections.Counter()
    for f in (f for f in filas if f.resultado == "INCOMPLETO"):
        partes = []
        for e in f.evaluacion:
            if e["aplica"] and e["nivel"] == "faltante" and not e["cumple"]:
                partes.append(e["causa"] or e["regla"].id + (f"[{e['pista_codigo']}]" if e["pista_codigo"] else ""))
        causas[" + ".join(partes) + (" (03 y 04 vacías)" if f.carpetas_vacias else "")] += 1
    L += ["INCOMPLETO por causa (reglas de nivel faltante no cumplidas):", "", "| Causa | Tareas |", "|---|---|"]
    L += [f"| {_md(k)} | {v} |" for k, v in causas.most_common()]
    adv = collections.Counter(e["regla"].id for f in evaluadas for e in f.evaluacion
                              if e["aplica"] and e["nivel"] == "advertencia" and not e["cumple"])
    L += ["", "Advertencias (no cuentan para INCOMPLETO): " + (", ".join(f"{k} {v}" for k, v in adv.items()) or "ninguna"),
          f"Por revisar (calzan con patron_revisar): {sum(1 for f in evaluadas for e in f.evaluacion if e['aplica'] and e['por_revisar'] and not e['coincidencias'])}", "",
          "Resultado por Tipo DEP:", ""]
    L += _tabla_cruzada(filas, lambda f: f.resultado, lambda f: f.tipo_dep or "(vacío)", "Resultado")
    L += ["", "Resultado por estado (solo Tipo DEP en alcance):", ""]
    L += _tabla_cruzada([f for f in filas if reglas.tipo_en_alcance(f.tipo_dep)], lambda f: f.estado, lambda f: f.resultado, "Estado")
    sin_link = [f for f in filas if f.carpeta_encontrada == "sin link"]
    L += ["", f"### Tareas sin link ({len(sin_link)}): mes de creación × Tipo DEP", "",
          "Para elegir `fecha_inicio_make`. " + (f"Corte vigente: {reglas.fecha_inicio_make.isoformat()}." if reglas.fecha_inicio_make
                                                 else "Sin corte (`fecha_inicio_make: null`)."), ""]
    L += _tabla_cruzada(sin_link, lambda f: f.fecha_creada.strftime("%Y-%m") if f.fecha_creada else "?",
                        lambda f: f.tipo_dep or "(vacío)", "Mes de creación")
    con_link = [f for f in filas if f.link_pr]
    L += ["", "Como referencia, tareas con link por mes de creación × Tipo DEP:", ""]
    L += _tabla_cruzada(con_link, lambda f: f.fecha_creada.strftime("%Y-%m") if f.fecha_creada else "?",
                        lambda f: f.tipo_dep or "(vacío)", "Mes de creación")

    # 3. Detalle
    L += ["", "## 3. Detalle por tarea (en alcance)", "",
          "Las FUERA_DE_ALCANCE están en la sección 8 y en el CSV.", "",
          "| ss_code | Estado | JP | Desde | Resultado | Reglas no cumplidas | Observaciones |", "|---|---|---|---|---|---|---|"]
    orden = {r: i for i, r in enumerate(RESULTADOS)}
    for f in sorted(en_alcance, key=lambda f: (orden[f.resultado], f.ss_code)):
        nc = ", ".join(e["regla"].id for e in f.evaluacion if e["aplica"] and e["nivel"] == "faltante" and not e["cumple"])
        obs = "; ".join(([f.motivo] if f.motivo else []) + f.observaciones)
        desde = f.fecha_estado.date().isoformat() if f.fecha_estado else ""
        L.append(f"| {_md(f.ss_code)} | {_md(f.estado)} | {_md(f.jp)} | {desde} | {f.resultado} | {nc} | {_md(obs)} |")

    # 4. Subcarpetas
    raros, faltan, otras = collections.Counter(), collections.Counter(), collections.Counter()
    for f in evaluadas + [f for f in filas if f.resultado == "NO_APLICA"]:
        for s in f.subs.values():
            if s.carpeta is not None and s.modo != "exacto":
                raros[(s.esperado, s.carpeta["name"], s.modo)] += 1
            elif s.carpeta is None:
                faltan[s.esperado] += 1
        otras.update(f.otras_subcarpetas)
    L += ["", "## 4. Nombres de subcarpeta (DEP - CENTRAL)", "", "| Esperado | Nombre real | Cómo se reconoció | Carpetas |", "|---|---|---|---|"]
    for (e, n, m), v in raros.most_common():
        L.append(f"| {_md(e)} | {_md(n)} | {m} | {v} |")
    L += ["", "Subcarpeta no encontrada: " + (", ".join(f"«{k}» en {v} carpetas" for k, v in faltan.items()) or "ninguna"), "",
          "Resto de subcarpetas de primer nivel:", "", "| Nombre | Carpetas |", "|---|---|"]
    for n, v in otras.most_common(40):
        L.append(f"| {_md(n)} | {v} |")

    # 5. Extensiones
    L += ["", "## 5. Extensiones por subcarpeta (DEP - CENTRAL, en alcance)", ""]
    base = [f for f in en_alcance if f.subs]
    for clave, esperado in reglas.subcarpetas.items():
        ext = collections.Counter(extension(a["name"], a.get("mimeType", "")) for f in base for a in f.subs[clave].archivos)
        vacias = sum(1 for f in base if f.subs[clave].carpeta and not f.subs[clave].archivos)
        L += [f"**{_md(esperado)}** ({sum(ext.values())} archivos; {vacias} subcarpetas vacías): "
              + (", ".join(f"`{k}` {v}" for k, v in ext.most_common()) or "—"), ""]
    s03 = [f for f in base if f.subs["tecnica_economica"].carpeta]
    multi = [f for f in s03 if sum(extension(a["name"]) == ".pdf" for a in f.subs["tecnica_economica"].archivos) > 1]
    L.append(f"- Carpetas 03 con más de un PDF: **{len(multi)}** de {len(s03)}.")
    canc = [f for f in base if f.estado == "cancelada"]
    canc04 = [f for f in canc if f.subs["oferta_enviada"].archivos]
    L.append(f"- Canceladas con archivos en 04: **{len(canc04)}** de {len(canc)} con carpeta"
             + (f" ({', '.join(f.ss_code for f in canc04)})" if canc04 else "") + ".")

    # 6. Falsos faltantes
    L += ["", "## 6. Posibles falsos faltantes", "",
          "Reglas aplicables no cumplidas donde la subcarpeta sí tiene archivos (ninguno calza con el patrón).", "",
          "| ss_code | Estado | Regla | Patrón | Archivos en la subcarpeta |", "|---|---|---|---|---|"]
    for f in evaluadas:
        for e in f.evaluacion:
            s = f.subs.get(e["regla"].subcarpeta)
            if e["aplica"] and e["nivel"] == "faltante" and not e["cumple"] and s and s.archivos:
                L.append(f"| {_md(f.ss_code)} | {_md(f.estado)} | {e['regla'].id} | `{_md(e['regla'].patron)}` | "
                         f"{_md('; '.join(a['name'] for a in s.archivos))} |")
    L += ["", "Faltantes con la subcarpeta vacía, por regla: " + ", ".join(
        f"{r.id} {sum(1 for f in evaluadas for e in f.evaluacion if e['regla'] is r and e['aplica'] and not e['cumple'] and not f.subs[r.subcarpeta].archivos)}"
        for r in reglas.reglas)]
    L += ["", "### Archivos que calzan con el patrón pero llevan el código de otra propuesta", "",
          "| ss_code | Regla | Archivos con otro código (o sin código) |", "|---|---|---|"]
    for f in evaluadas:
        for e in f.evaluacion:
            if e["aplica"] and e["otro_codigo"]:
                L.append(f"| {_md(f.ss_code)} | {e['regla'].id} | {_md('; '.join(e['otro_codigo']))} |")
    L += ["", "### Reglas que calzan con varios archivos", "", "| ss_code | Regla | N | Archivos |", "|---|---|---|---|"]
    for f in evaluadas:
        for e in f.evaluacion:
            if len(e["coincidencias"]) > 1:
                L.append(f"| {_md(f.ss_code)} | {e['regla'].id} | {len(e['coincidencias'])} | {_md('; '.join(e['coincidencias']))} |")

    # 7. Lista de correccion para la Fase 2
    L += ["", "## 7. Lista de corrección de links (insumo Fase 2)", "", "### 7.1 LINK_OBSOLETO: el link no resuelve, la carpeta existe", "",
          "| Código | Estado | Link viejo | Carpeta encontrada | Ubicación | Link nuevo |", "|---|---|---|---|---|---|"]
    for f in sorted((f for f in filas if f.link_obsoleto), key=lambda f: f.ss_code):
        L.append(f"| {_md(f.ss_code)} | {_md(f.estado)} | {_md(f.link_pr)} | {_md(f.carpeta_pr['name'])} | {_md(f.ubicacion)} | {_link(f.carpeta_pr['id'])} |")
    rotos = [f for f in filas if f.carpeta_encontrada == "no"]
    if rotos:
        L += ["", "Link que no resuelve y sin carpeta por código: " + ", ".join(f"{_md(f.ss_code)} ({f.estado})" for f in rotos)]
    L += ["", "### 7.2 El link apunta a una subcarpeta (06 Backup) en vez de la carpeta PR", "",
          "| Código | Estado | Subcarpeta enlazada | Link actual | Link de la carpeta PR |", "|---|---|---|---|---|"]
    for f in sorted((f for f in filas if f.enlace.startswith("subcarpeta")), key=lambda f: f.ss_code):
        L.append(f"| {_md(f.ss_code)} | {_md(f.estado)} | {_md(f.enlace[len('subcarpeta '):])} | {_md(f.link_pr)} | {_link(f.carpeta_pr['id'])} |")
    L += ["", "### 7.3 Sin link, pero la carpeta existe (hallada por código)", "",
          "| Código | Estado | Tipo DEP | Carpeta | Ubicación | Link |", "|---|---|---|---|---|---|"]
    for f in sorted((f for f in filas if f.encontrada_por_codigo), key=lambda f: f.ss_code):
        c = f.encontrada_por_codigo
        L.append(f"| {_md(f.ss_code)} | {_md(f.estado)} | {_md(f.tipo_dep)} | {_md(c['carpeta']['name'])} | {_md(c['ubicacion'])} | {_link(c['carpeta']['id'])} |")

    # Carpetas compartidas por más de una tarea
    por_carpeta = collections.defaultdict(list)
    for f in filas:
        if f.carpeta_pr:
            por_carpeta[f.carpeta_pr["id"]].append(f)
    dup = {k: v for k, v in por_carpeta.items() if len(v) > 1}
    L += ["", "### 7.4 Carpetas PR enlazadas desde más de una tarea", ""]
    L += [f"- {', '.join(f'{x.ss_code} ({x.estado})' for x in v)} → {_md(v[0].carpeta_pr['name'])}" for v in dup.values()] or ["Ninguna."]

    # 8. Fuera de alcance
    fuera = [f for f in filas if f.resultado == "FUERA_DE_ALCANCE"]
    L += ["", f"## 8. Fuera de alcance ({len(fuera)})", "", "Ubicación de la carpeta × Tipo DEP (todas las tareas):", ""]
    L += _tabla_cruzada(filas, lambda f: f.ubicacion or f"({f.carpeta_encontrada})", lambda f: f.tipo_dep or "(vacío)", "Ubicación")
    L += ["", "Subcarpetas de primer nivel en las ubicaciones fuera de alcance:", "", "| Ubicación | Subcarpeta | Carpetas |", "|---|---|---|"]
    sub_fuera = collections.Counter((f.ubicacion, n) for f in filas if f.ubicacion and not reglas.ubicacion_en_alcance(f.ubicacion)
                                    for n in f.subcarpetas_pr)
    for (u, n), v in sorted(sub_fuera.items(), key=lambda x: (x[0][0], -x[1], x[0][1])):
        L.append(f"| {_md(u)} | {_md(n)} | {v} |")
    L += ["", "| ss_code | Estado | Tipo DEP | Motivo | Carpeta |", "|---|---|---|---|---|"]
    for f in sorted(fuera, key=lambda f: (f.motivo, f.ss_code)):
        L.append(f"| {_md(f.ss_code)} | {_md(f.estado)} | {_md(f.tipo_dep)} | {_md(f.motivo)} | {_md(f.carpeta_encontrada)} |")

    # 9. Huerfanas
    L += ["", "## 9. Carpetas huérfanas (ninguna tarea las referencia, ni por link ni por código)", "",
          "| Ubicación | Carpeta | Modificada | Link |", "|---|---|---|---|"]
    for r, c in sorted(orfs, key=lambda x: (x[0], x[1]["name"])):
        L.append(f"| {_md(r)} | {_md(c['name'])} | {(c.get('modifiedTime') or '')[:10]} | {_link(c['id'])} |")
    md.write_text("\n".join(L) + "\n", encoding="utf-8")

    with cs.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["task_id", "ss_code", "nombre", "estado", "estado_pipeline", "tipo_dep", "jp", "fecha_creada", "fecha_estado",
                    "fecha_fuente", "carpeta_encontrada", "enlace", "link_obsoleto", "carpeta_pr_id", "ubicacion", "regla",
                    "subcarpeta_esperada", "subcarpeta_real", "modo_subcarpeta", "n_archivos_subcarpeta", "aplica", "cumple",
                    "n_coincidencias", "coincidencias", "nivel", "por_revisar", "otro_codigo", "pista", "causa", "pista_codigo",
                    "resultado_tarea", "motivo", "observaciones"])
        for f in filas:
            for e in f.evaluacion:
                s = f.subs.get(e["regla"].subcarpeta)
                w.writerow([f.task_id, f.ss_code, f.nombre, f.estado, f.estado_pipeline or "", f.tipo_dep, f.jp,
                            f.fecha_creada.date().isoformat() if f.fecha_creada else "",
                            f.fecha_estado.isoformat() if f.fecha_estado else "", f.fecha_fuente, f.carpeta_encontrada,
                            f.enlace, f.link_obsoleto, (f.carpeta_pr or {}).get("id", ""), f.ubicacion, e["regla"].id,
                            reglas.subcarpetas[e["regla"].subcarpeta], (s.carpeta or {}).get("name", "") if s else "",
                            (s.modo or "") if s else "", len(s.archivos) if s else "", e["aplica"], e["cumple"],
                            len(e["coincidencias"]), "; ".join(e["coincidencias"]), e["nivel"], "; ".join(e["por_revisar"]),
                            "; ".join(e["otro_codigo"]), "; ".join(e["pista"]), e["causa"], e["pista_codigo"], f.resultado, f.motivo,
                            "; ".join(f.observaciones)])
    # Inventario de archivos (una fila por archivo) en un CSV aparte para no mezclar granularidades.
    inv = OUT / f"recon_{fecha.isoformat()}_archivos.csv"
    with inv.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ss_code", "resultado_tarea", "ubicacion", "subcarpeta", "archivo", "extension", "tamano_bytes",
                    "modifiedTime", "lastModifyingUser"])
        for f in filas:
            for s in f.subs.values():
                for a in s.archivos:
                    u = a.get("lastModifyingUser") or {}
                    sub = (s.carpeta or {}).get("name", "") + (f"/{a['_en']}" if a.get("_en") else "")
                    w.writerow([f.ss_code, f.resultado, f.ubicacion, sub, a["name"],
                                extension(a["name"], a.get("mimeType", "")), a.get("size", ""), a.get("modifiedTime", ""),
                                u.get("displayName") or u.get("emailAddress") or ""])
    return md, cs


# --- CLI -----------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paso0", action="store_true", help="solo descubrimiento (campos, estados, acceso a Drive)")
    ap.add_argument("--no-interactivo", action="store_true", help="no abrir el navegador si falta el token de Drive")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    fecha = dt.datetime.now(TZ).date()
    reglas = Reglas.cargar()

    cu = ClickUpClient()
    d_cu = descubrir_clickup(cu)
    ids = [t["id"] for t in d_cu["principales"]]
    fechas, error_tis = fechas_estado_actual(cu, ids[:1] if a.paso0 else ids)
    dr, error_auth = None, None
    try:
        dr = DriveClient(AuthorizedSession(cargar_credenciales(interactivo=not a.no_interactivo)))
    except Exception as e:  # sin token, consentimiento rechazado, API deshabilitada...
        error_auth = f"{type(e).__name__}: {e}"
    d_dr = descubrir_drive(dr, d_cu["principales"], error_auth)

    if a.paso0:
        p = escribir_paso0(d_cu, d_dr, reglas, error_tis, fecha)
        print(f"Paso 0 escrito en {p}  (ClickUp: {cu.request_count} GET; Drive: {dr.request_count if dr else 0} GET)")
        return 0
    if d_dr["error_auth"]:
        print(f"Sin acceso a Drive: {d_dr['error_auth']}", file=sys.stderr)
        return 1
    filas = inventariar(d_cu["principales"], dr, reglas, fechas, indice_por_codigo(dr, d_dr["raices"]))
    orfs = huerfanas(dr, d_dr["raices"], filas)
    md, cs = escribir_reporte(d_cu, d_dr, reglas, error_tis, filas, orfs, fecha)
    print(f"Vacías: {escribir_vacias(filas, fecha)}")
    print(f"Reporte: {md}\nCSV: {cs}\n(ClickUp: {cu.request_count} GET; Drive: {dr.request_count} GET)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
