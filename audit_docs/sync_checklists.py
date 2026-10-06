"""Bloque B de la Fase 2: checklist "Documentos", campo `Docs OK` y pestaña docs_propuestas.

    python -m audit_docs.sync_checklists --dry-run [--recon out/recon_YYYY-MM-DD.csv]
        -> out/sync_YYYY-MM-DD.csv (por tarea: checklist, ítems y Docs OK actual/nuevo) y
           out/docs_propuestas_YYYY-MM-DD.csv (lo que iría a la pestaña). Ninguna escritura.
    python -m audit_docs.sync_checklists --apply --solo 2026.0152,2026.0239   (piloto)
    python -m audit_docs.sync_checklists --apply                            (todas + pestaña)

Lee la evaluación del CSV de recon.py (por defecto el del día) y el estado vivo de ClickUp. Escribe
solo lo que cambia; dos corridas seguidas sin cambios en Drive no escriben nada. Antes de la primera
escritura respalda los valores vigentes en out/sync_YYYY-MM-DD_backup.json; log por escritura en
out/sync_YYYY-MM-DD_log.csv.

- Checklist "Documentos" (nunca una segunda con ese nombre): un ítem por regla aplicable,
  "[etiqueta] texto", resuelto si la regla se cumple. Se identifican por el prefijo [etiqueta]; los
  ítems sin ese prefijo (agregados a mano) no se tocan, y los de reglas que ya no aplican tampoco.
- Docs OK: Completo / Incompleto / Sin carpeta; vacío para NO_APLICA, HISTORICA y FUERA_DE_ALCANCE.
- Pestaña docs_propuestas en la hoja del worker (SHEETS_REPORTES_ID): reemplazo completo, solo con
  --apply sin --solo.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from dep_clickup.client import ClickUpClient, ClickUpError
from dep_clickup.config import TZ
from dep_clickup.fields import resolve_value

from .recon import OUT, SS_REGISTRO
from .reglas import Reglas

log = logging.getLogger("audit_docs.sync")

CHECKLIST = "Documentos"
CAMPO_DOCS = "Docs OK"
DOCS_OK = {"COMPLETO": "Completo", "INCOMPLETO": "Incompleto", "SIN_CARPETA": "Sin carpeta"}
CON_CHECKLIST = ("COMPLETO", "INCOMPLETO")
PESTANA = "docs_propuestas"
COLUMNAS_PESTANA = ["ss_code", "nombre", "estado", "jp", "docs_ok", "reglas_no_cumplidas", "causa_oferta", "link_pr",
                    "fecha_corrida"]
RE_PREFIJO = re.compile(r"^\[([^\]]+)\]")


# --- Evaluación (desde el CSV de recon) --------------------------------------------------------

@dataclass
class Evaluacion:
    task_id: str
    ss_code: str
    nombre: str
    estado: str
    jp: str
    resultado: str
    carpeta_pr_id: str
    reglas: list[dict] = field(default_factory=list)   # {id, aplica, cumple, causa, pista_codigo}

    @property
    def docs_ok(self) -> str | None:
        return DOCS_OK.get(self.resultado)

    @property
    def no_cumplidas(self) -> list[str]:
        return [r["id"] for r in self.reglas if r["aplica"] and not r["cumple"]]

    @property
    def causa_oferta(self) -> str:
        return next((r["causa"] for r in self.reglas if r["aplica"] and r["causa"]), "")


def leer_recon(path: Path) -> dict[str, Evaluacion]:
    out: dict[str, Evaluacion] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            ev = out.setdefault(r["task_id"], Evaluacion(r["task_id"], r["ss_code"], r["nombre"], r["estado"], r["jp"],
                                                         r["resultado_tarea"], r["carpeta_pr_id"]))
            ev.reglas.append({"id": r["regla"], "aplica": r["aplica"] == "True", "cumple": r["cumple"] == "True",
                              "causa": r.get("causa", ""), "pista_codigo": r.get("pista_codigo", "")})
    return out


def recon_del_dia(fecha: dt.date) -> Path:
    p = OUT / f"recon_{fecha.isoformat()}.csv"
    if not p.exists():
        raise SystemExit(f"No existe {p}: correr antes `python -m audit_docs.recon`")
    return p


def texto_item(regla, r: dict) -> str:
    """Texto del ítem (sin el prefijo). Si no se cumple, el de la causa o pista si la regla lo define."""
    if not r["cumple"]:
        for clave in (r["causa"], r["pista_codigo"]):
            if clave and clave in regla.textos:
                return regla.textos[clave]
    return regla.descripcion


def items_deseados(ev: Evaluacion, reglas: Reglas) -> list[dict]:
    por_id = {r.id: r for r in reglas.reglas}
    return [{"etiqueta": por_id[r["id"]].etiqueta, "nombre": f"[{por_id[r['id']].etiqueta}] {texto_item(por_id[r['id']], r)}",
             "resolved": r["cumple"]}
            for r in ev.reglas if r["aplica"] and r["id"] in por_id]


# --- Plan (función pura: estado vivo + evaluación -> acciones) ---------------------------------

@dataclass
class Plan:
    task_id: str
    ss_code: str
    resultado: str
    checklist_id: str | None = None
    crear_checklist: bool = False
    items: list[dict] = field(default_factory=list)       # {accion, item_id, nombre, resolved, antes}
    docs_ok_actual: str | None = None
    docs_ok_nuevo: str | None = None
    avisos: list[str] = field(default_factory=list)

    @property
    def cambia_docs_ok(self) -> bool:
        return self.docs_ok_actual != self.docs_ok_nuevo

    @property
    def escrituras(self) -> int:
        n = int(self.crear_checklist) + int(self.cambia_docs_ok)
        for i in self.items:
            n += {"crear": 1 + int(i["resolved"]), "editar": 1}.get(i["accion"], 0)
        return n


def planificar(ev: Evaluacion, tarea: dict, reglas: Reglas, docs_ok_actual: str | None) -> Plan:
    p = Plan(ev.task_id, ev.ss_code, ev.resultado, docs_ok_actual=docs_ok_actual, docs_ok_nuevo=ev.docs_ok)
    if ev.resultado not in CON_CHECKLIST:
        return p
    existentes = [c for c in tarea.get("checklists") or [] if c.get("name") == CHECKLIST]
    if len(existentes) > 1:
        p.avisos.append(f"{len(existentes)} checklists «{CHECKLIST}»: se usa la primera")
    actual = existentes[0] if existentes else None
    p.checklist_id = actual["id"] if actual else None
    p.crear_checklist = actual is None
    por_etiqueta: dict[str, dict] = {}
    for it in (actual or {}).get("items") or []:
        m = RE_PREFIJO.match(it.get("name") or "")
        if m and m.group(1) not in por_etiqueta:
            por_etiqueta[m.group(1)] = it
    for d in items_deseados(ev, reglas):
        it = por_etiqueta.get(d["etiqueta"])
        if it is None:
            p.items.append({"accion": "crear", "item_id": None, "nombre": d["nombre"], "resolved": d["resolved"], "antes": None})
        elif it.get("name") != d["nombre"] or bool(it.get("resolved")) != d["resolved"]:
            p.items.append({"accion": "editar", "item_id": it["id"], "nombre": d["nombre"], "resolved": d["resolved"],
                            "antes": {"name": it.get("name"), "resolved": bool(it.get("resolved"))}})
        else:
            p.items.append({"accion": "igual", "item_id": it["id"], "nombre": d["nombre"], "resolved": d["resolved"], "antes": None})
    return p


def aplicar_plan(cu, p: Plan, field_id: str, opciones: dict[str, str], registrar) -> None:
    """Ejecuta el plan. `registrar(accion, detalle, http)` deja una línea de log por escritura."""
    if p.crear_checklist:
        ch = cu.crear_checklist(p.task_id, CHECKLIST)
        p.checklist_id = ch["id"]
        registrar("crear_checklist", CHECKLIST, 200)
    for i in p.items:
        if i["accion"] == "crear":
            ch = cu.crear_item(p.checklist_id, i["nombre"])
            nuevo = next(x for x in ch["items"] if x["name"] == i["nombre"])
            registrar("crear_item", i["nombre"], 200)
            if i["resolved"]:
                cu.editar_item(p.checklist_id, nuevo["id"], resolved=True)
                registrar("resolver_item", i["nombre"], 200)
        elif i["accion"] == "editar":
            cu.editar_item(p.checklist_id, i["item_id"], name=i["nombre"], resolved=i["resolved"])
            registrar("editar_item", f"{i['nombre']} (resuelto={i['resolved']})", 200)
    if p.cambia_docs_ok:
        if p.docs_ok_nuevo:
            registrar("docs_ok", p.docs_ok_nuevo, cu.set_campo(p.task_id, field_id, opciones[p.docs_ok_nuevo]))
        else:
            registrar("docs_ok", "(limpiar)", cu.borrar_campo(p.task_id, field_id))


# --- Estado vivo de ClickUp --------------------------------------------------------------------

def campo_docs(cu: ClickUpClient) -> tuple[dict, dict[str, str]]:
    for f in cu.get(f"/list/{SS_REGISTRO}/field").get("fields", []):
        if f["name"] == CAMPO_DOCS:
            opciones = {o["name"]: o["id"] for o in (f.get("type_config") or {}).get("options", [])}
            faltan = set(DOCS_OK.values()) - set(opciones)
            if faltan:
                raise RuntimeError(f"Al campo «{CAMPO_DOCS}» le faltan opciones: {sorted(faltan)}")
            return f, opciones
    raise RuntimeError(f"No existe el campo «{CAMPO_DOCS}» en SS_REGISTRO")


def valor_docs(tarea: dict, campo: dict) -> str | None:
    for f in tarea.get("custom_fields") or []:
        if f.get("id") == campo["id"]:
            return resolve_value(campo["type"], campo.get("type_config") or {}, f.get("value"))
    return None


# --- Pestaña docs_propuestas -------------------------------------------------------------------

def filas_pestana(evs: list[Evaluacion], fecha: str) -> list[list]:
    filas = []
    for e in sorted(evs, key=lambda e: e.ss_code):
        if e.resultado not in DOCS_OK:
            continue
        filas.append([e.ss_code, e.nombre, e.estado, e.jp, e.docs_ok, ";".join(e.no_cumplidas), e.causa_oferta,
                      f"https://drive.google.com/drive/folders/{e.carpeta_pr_id}" if e.carpeta_pr_id else "", fecha])
    return filas


def escribir_pestana(filas: list[list]) -> int:
    """Reemplazo completo de la pestaña (la crea si no existe). Devuelve las filas escritas."""
    from dep_reportes.google_auth import sesion
    sid = os.getenv("SHEETS_REPORTES_ID")
    if not sid:
        raise RuntimeError("Falta SHEETS_REPORTES_ID")
    s, api = sesion(interactivo=False), f"https://sheets.googleapis.com/v4/spreadsheets/{sid}"

    def req(metodo, url, **kw):
        r = s.request(metodo, url, timeout=120, **kw)
        if r.status_code != 200:
            raise RuntimeError(f"Sheets {r.status_code}: {r.text[:300]}")
        return r.json()

    meta = req("GET", api, params={"fields": "sheets(properties(sheetId,title))"})
    if PESTANA not in {x["properties"]["title"] for x in meta.get("sheets", [])}:
        req("POST", f"{api}:batchUpdate", json={"requests": [{"addSheet": {"properties": {"title": PESTANA}}}]})
    req("POST", f"{api}/values/'{PESTANA}':clear")
    req("PUT", f"{api}/values/'{PESTANA}'!A1", params={"valueInputOption": "RAW"},
        json={"values": [COLUMNAS_PESTANA] + filas})
    return len(filas)


# --- CLI -----------------------------------------------------------------------------------------

def _escribir_csv(p: Path, columnas: list[str], filas: list[list]) -> None:
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(columnas)
        w.writerows(filas)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--recon", type=Path, help="CSV de recon.py (por defecto el del día)")
    ap.add_argument("--solo", default="", help="ss_codes separados por coma (piloto)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    ahora = dt.datetime.now(TZ)
    hoy = ahora.date().isoformat()
    solo = {x.strip() for x in a.solo.split(",") if x.strip()}

    reglas = Reglas.cargar()
    evs = leer_recon(a.recon or recon_del_dia(ahora.date()))
    if solo:
        faltan = solo - {e.ss_code for e in evs.values()}
        if faltan:
            raise SystemExit(f"Códigos que no están en el recon: {sorted(faltan)}")
    if a.apply:
        from .clickup_escritura import ClickUpEscritura
        cu = ClickUpEscritura()
    else:
        cu = ClickUpClient()
    campo, opciones = campo_docs(cu)
    vivas = {t["id"]: t for t in cu.list_tasks_raw(SS_REGISTRO) if not t.get("parent")}

    planes = []
    for ev in evs.values():
        if solo and ev.ss_code not in solo:
            continue
        t = vivas.get(ev.task_id)
        if t is None:
            log.warning("%s no está en SS_REGISTRO (¿borrada?): se omite", ev.ss_code)
            continue
        planes.append(planificar(ev, t, reglas, valor_docs(t, campo)))

    OUT.mkdir(parents=True, exist_ok=True)
    filas_sync = []
    for p in sorted(planes, key=lambda p: p.ss_code):
        base = [p.ss_code, p.task_id, p.resultado]
        acc_ch = "crear" if p.crear_checklist else ("existe" if p.checklist_id else "")
        for i in p.items:
            filas_sync.append(base + [acc_ch, i["accion"], i["nombre"], i["resolved"],
                                      json.dumps(i["antes"], ensure_ascii=False) if i["antes"] else "",
                                      p.docs_ok_actual or "", p.docs_ok_nuevo or "", "; ".join(p.avisos)])
        if not p.items:
            filas_sync.append(base + ["", "", "", "", "", p.docs_ok_actual or "", p.docs_ok_nuevo or "", "; ".join(p.avisos)])
    sufijo = "_piloto" if solo else ""
    p_sync = OUT / f"sync_{hoy}{sufijo}.csv"
    _escribir_csv(p_sync, ["ss_code", "task_id", "resultado", "checklist", "accion_item", "item", "resuelto",
                           "item_antes", "docs_ok_actual", "docs_ok_nuevo", "avisos"], filas_sync)
    filas_p = filas_pestana(list(evs.values()), ahora.isoformat(timespec="seconds"))
    _escribir_csv(OUT / f"docs_propuestas_{hoy}.csv", COLUMNAS_PESTANA, filas_p)

    r = Counter()
    for p in planes:
        r["checklists_nuevas"] += p.crear_checklist
        r["items_nuevos"] += sum(i["accion"] == "crear" for i in p.items)
        r["items_que_cambian"] += sum(i["accion"] == "editar" for i in p.items)
        r["items_sin_cambio"] += sum(i["accion"] == "igual" for i in p.items)
        r["docs_ok_que_cambian"] += p.cambia_docs_ok
        r["escrituras"] += p.escrituras
    trans = Counter((p.docs_ok_actual or "(vacío)", p.docs_ok_nuevo or "(vacío)") for p in planes if p.cambia_docs_ok)
    print(f"{'Dry-run' if a.dry_run else 'Apply'}: {len(planes)} tareas | " + ", ".join(f"{k} {v}" for k, v in r.items()))
    print("Docs OK: " + (", ".join(f"{x} → {y}: {n}" for (x, y), n in sorted(trans.items())) or "sin cambios"))
    for p in planes:
        for av in p.avisos:
            print(f"  aviso {p.ss_code}: {av}")
    print(f"Detalle: {p_sync}\nPestaña ({len(filas_p)} filas): {OUT / f'docs_propuestas_{hoy}.csv'}")
    if a.dry_run:
        print(f"(ClickUp: {cu.request_count} GET; ninguna escritura)")
        return 0

    # --- Apply: respaldo, escrituras, pestaña ---
    pendientes = [p for p in planes if p.escrituras]
    p_backup, p_log = OUT / f"sync_{hoy}_backup.json", OUT / f"sync_{hoy}_log.csv"
    if pendientes:
        previo = json.loads(p_backup.read_text(encoding="utf-8")) if p_backup.exists() else []
        previo.append({"respaldado_en": ahora.isoformat(timespec="seconds"), "tareas": [
            {"task_id": p.task_id, "ss_code": p.ss_code, "docs_ok": p.docs_ok_actual,
             "checklists": [c for c in vivas[p.task_id].get("checklists") or [] if c.get("name") == CHECKLIST]}
            for p in pendientes]})
        p_backup.write_text(json.dumps(previo, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Respaldo: {p_backup}")
    nuevo_log = not p_log.exists()
    errores = 0
    with p_log.open("a", encoding="utf-8-sig" if nuevo_log else "utf-8", newline="") as fh:
        w = csv.writer(fh)
        if nuevo_log:
            w.writerow(["escrito_en", "ss_code", "task_id", "accion", "detalle", "http"])
        for p in pendientes:
            def registrar(accion, detalle, http, p=p):
                w.writerow([dt.datetime.now(TZ).isoformat(timespec="seconds"), p.ss_code, p.task_id, accion, detalle, http])
            try:
                aplicar_plan(cu, p, campo["id"], opciones, registrar)
            except ClickUpError as e:
                errores += 1
                registrar("ERROR", e.body[:200], e.status)
                print(f"  ERROR {p.ss_code}: HTTP {e.status}")
            fh.flush()
    print(f"Escritas {len(pendientes) - errores} tareas ({errores} con error). Log: {p_log}")
    if not solo:
        print(f"Pestaña {PESTANA}: {escribir_pestana(filas_p)} filas")
    print(f"(ClickUp: {cu.request_count} peticiones)")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
