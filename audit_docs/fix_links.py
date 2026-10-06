"""Bloque A de la Fase 2: corrige `Drive PR URL` en SS_REGISTRO.

    python -m audit_docs.fix_links --dry-run
        -> out/fix_links_YYYY-MM-DD.csv (una fila por corrección; revisarla)
    python -m audit_docs.fix_links --apply out/fix_links_YYYY-MM-DD.csv --motivos A1
        -> escribe solo las filas de ese CSV con esos motivos; antes de la primera escritura agrega
           los valores vigentes a out/fix_links_YYYY-MM-DD_backup.csv; log por fila en ..._log.csv
    python -m audit_docs.fix_links --revert out/fix_links_YYYY-MM-DD_backup.csv [--solo 2026.0304]

Motivos: A1 el link apunta a una subcarpeta (06 Backup) -> link de la carpeta PR; A2 el link no
resuelve y la carpeta aparece por código; A3 sin link, código >= codigo_inicio_make y la carpeta existe.
Alcance: el de rules.yaml (Tipo DEP y ubicación de la carpeta). Drive solo se lee. No toca Drive PJ URL.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import sys
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession

from dep_clickup.client import ClickUpClient, ClickUpError, parse_task
from dep_clickup.config import TZ

from .drive import DriveClient, DriveError, cargar_credenciales, id_desde_url
from .recon import (CAMPO_PR, OUT, RE_CODIGO, SS_REGISTRO, _por_codigo, _valor, carpeta_propuesta, descubrir_clickup,
                    descubrir_drive, indice_por_codigo, ruta)
from .reglas import Reglas

log = logging.getLogger("audit_docs.fix_links")

COLUMNAS = ["task_id", "ss_code", "estado", "campo", "field_id", "valor_actual", "valor_nuevo", "motivo", "carpeta", "ubicacion"]
COLUMNAS_BACKUP = ["respaldado_en", "task_id", "ss_code", "campo", "field_id", "valor_anterior", "motivo"]
COLUMNAS_LOG = ["escrito_en", "accion", "task_id", "ss_code", "field_id", "valor", "http", "detalle"]


def link_carpeta(fid: str) -> str:
    return f"https://drive.google.com/drive/folders/{fid}"


def _id_campo(cu: ClickUpClient, nombre: str) -> str:
    for f in cu.get(f"/list/{SS_REGISTRO}/field").get("fields", []):
        if f["name"] == nombre:
            return f["id"]
    raise RuntimeError(f"No existe el campo «{nombre}» en SS_REGISTRO")


def correcciones(cu: ClickUpClient, dr: DriveClient, reglas: Reglas) -> tuple[list[dict], list[dict]]:
    """(filas a corregir, excluidas con su razón). Solo lectura."""
    d_cu = descubrir_clickup(cu)
    d_dr = descubrir_drive(dr, d_cu["principales"], None)
    idx = indice_por_codigo(dr, d_dr["raices"])
    field_id = d_cu["campos_drive"][CAMPO_PR]["id"]
    filas, excluidas = [], []
    for t in d_cu["principales"]:
        tk = parse_task(t, SS_REGISTRO)
        ss = _valor(t, "SS_CODE") or tk.name.split("|")[0].strip()
        m = RE_CODIGO.search(f"{_valor(t, 'PR_CODE') or ''} {ss} {tk.name}")
        codigo = m.group(1) if m else None
        tipo = (tk.custom_fields.get("Tipo DEP").value if tk.custom_fields.get("Tipo DEP") else None) or ""
        actual = _valor(t, CAMPO_PR) or ""
        fid = id_desde_url(actual)
        motivo, carpeta = None, None
        if fid:
            try:
                c, enlace = carpeta_propuesta(dr, fid)
                if enlace.startswith("subcarpeta"):
                    motivo, carpeta = "A1", c
            except DriveError:
                hallada = _por_codigo(dr, idx, codigo, reglas)
                if hallada:
                    motivo, carpeta = "A2", hallada[0]
                else:
                    excluidas.append({"ss_code": ss, "estado": tk.status, "razon": "A2: link no resuelve y no aparece por código"})
        elif not actual:
            hallada = _por_codigo(dr, idx, codigo, reglas)
            if hallada:
                if reglas.codigo_inicio_make and (codigo or "") < reglas.codigo_inicio_make:
                    excluidas.append({"ss_code": ss, "estado": tk.status, "razon": "A3: HISTORICA (código anterior)"})
                else:
                    motivo, carpeta = "A3", hallada[0]
        if not motivo:
            continue
        ubic = ruta(dr, (carpeta.get("parents") or [None])[0])
        if not reglas.tipo_en_alcance(tipo):
            excluidas.append({"ss_code": ss, "estado": tk.status, "razon": f"{motivo}: Tipo DEP {tipo or '(vacío)'} fuera de alcance"})
        elif not reglas.ubicacion_en_alcance(ubic):
            excluidas.append({"ss_code": ss, "estado": tk.status, "razon": f"{motivo}: carpeta en {ubic}, fuera de alcance"})
        else:
            filas.append({"task_id": tk.id, "ss_code": ss, "estado": tk.status, "campo": CAMPO_PR, "field_id": field_id,
                          "valor_actual": actual, "valor_nuevo": link_carpeta(carpeta["id"]), "motivo": motivo,
                          "carpeta": carpeta["name"], "ubicacion": ubic})
    return sorted(filas, key=lambda f: (f["motivo"], f["ss_code"])), excluidas


def _leer_csv(p: Path) -> list[dict]:
    with p.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _agregar_csv(p: Path, columnas: list[str], filas: list[dict]) -> None:
    nuevo = not p.exists()
    with p.open("a", encoding="utf-8-sig" if nuevo else "utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas)
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def _valor_vivo(cu: ClickUpClient, task_id: str, field_id: str) -> str:
    t = cu.get(f"/task/{task_id}")
    return next((f.get("value") or "" for f in t.get("custom_fields", []) if f.get("id") == field_id), "")


def aplicar(cu, entrada: Path, motivos: set[str], solo: set[str] | None, ahora: str) -> int:
    filas = [f for f in _leer_csv(entrada) if f["motivo"] in motivos and (not solo or f["ss_code"] in solo)]
    if not filas:
        print("Nada que aplicar con esos motivos.")
        return 0
    base = entrada.with_suffix("")
    backup, log_csv = Path(f"{base}_backup.csv"), Path(f"{base}_log.csv")
    # 1) Leer los valores vigentes y respaldarlos ANTES de escribir nada.
    vivos = {f["task_id"]: _valor_vivo(cu, f["task_id"], f["field_id"]) for f in filas}
    _agregar_csv(backup, COLUMNAS_BACKUP, [{"respaldado_en": ahora, "task_id": f["task_id"], "ss_code": f["ss_code"],
                                            "campo": f["campo"], "field_id": f["field_id"],
                                            "valor_anterior": vivos[f["task_id"]], "motivo": f["motivo"]} for f in filas])
    print(f"Respaldo: {backup} ({len(filas)} filas)")
    # 2) Escribir, saltando las filas cuyo valor cambió desde el dry-run.
    errores = 0
    for f in filas:
        reg = {"escrito_en": ahora, "accion": f"apply {f['motivo']}", "task_id": f["task_id"], "ss_code": f["ss_code"],
               "field_id": f["field_id"], "valor": f["valor_nuevo"], "http": "", "detalle": ""}
        if vivos[f["task_id"]] == f["valor_nuevo"]:
            reg["detalle"] = "omitida: ya tiene el valor nuevo"
        elif vivos[f["task_id"]] != f["valor_actual"]:
            reg["detalle"] = "omitida: el valor cambió desde el dry-run"
        else:
            try:
                reg["http"] = cu.set_campo(f["task_id"], f["field_id"], f["valor_nuevo"])
            except ClickUpError as e:
                reg["http"], reg["detalle"], errores = e.status, e.body[:200], errores + 1
        _agregar_csv(log_csv, COLUMNAS_LOG, [reg])
        print(f"{f['ss_code']} {f['motivo']} -> {reg['http'] or '-'} {reg['detalle']}")
    print(f"Log: {log_csv}")
    return 1 if errores else 0


def revertir(cu, backup: Path, solo: set[str] | None, ahora: str) -> int:
    filas = [f for f in _leer_csv(backup) if not solo or f["ss_code"] in solo]
    # Si una tarea se respaldó más de una vez, el valor original es el del primer respaldo.
    primero: dict[tuple[str, str], dict] = {}
    for f in filas:
        primero.setdefault((f["task_id"], f["field_id"]), f)
    log_csv = Path(str(backup).replace("_backup.csv", "_log.csv"))
    errores = 0
    for f in primero.values():
        reg = {"escrito_en": ahora, "accion": "revert", "task_id": f["task_id"], "ss_code": f["ss_code"],
               "field_id": f["field_id"], "valor": f["valor_anterior"], "http": "", "detalle": ""}
        try:
            reg["http"] = (cu.set_campo(f["task_id"], f["field_id"], f["valor_anterior"]) if f["valor_anterior"]
                           else cu.borrar_campo(f["task_id"], f["field_id"]))
        except ClickUpError as e:
            reg["http"], reg["detalle"], errores = e.status, e.body[:200], errores + 1
        _agregar_csv(log_csv, COLUMNAS_LOG, [reg])
        print(f"{f['ss_code']} revert -> {reg['http']} {reg['detalle']}")
    return 1 if errores else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", type=Path, metavar="CSV", help="CSV del dry-run, ya revisado")
    g.add_argument("--revert", type=Path, metavar="BACKUP_CSV")
    ap.add_argument("--motivos", default="", help="con --apply: A1, A2 y/o A3 separados por coma (obligatorio)")
    ap.add_argument("--solo", default="", help="ss_codes separados por coma")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    ahora = dt.datetime.now(TZ).isoformat(timespec="seconds")
    solo = {x.strip() for x in a.solo.split(",") if x.strip()} or None

    if a.dry_run:
        cu = ClickUpClient()
        dr = DriveClient(AuthorizedSession(cargar_credenciales(interactivo=False)))
        filas, excluidas = correcciones(cu, dr, Reglas.cargar())
        OUT.mkdir(parents=True, exist_ok=True)
        p = OUT / f"fix_links_{dt.datetime.now(TZ).date().isoformat()}.csv"
        with p.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNAS)
            w.writeheader()
            w.writerows(filas)
        cuenta = {m: sum(f["motivo"] == m for f in filas) for m in ("A1", "A2", "A3")}
        print(f"Dry-run: {p}\n  " + ", ".join(f"{k} {v}" for k, v in cuenta.items()))
        for e in excluidas:
            print(f"  no se toca: {e['ss_code']} ({e['estado']}) — {e['razon']}")
        print(f"(ClickUp: {cu.request_count} GET; Drive: {dr.request_count} GET; ninguna escritura)")
        return 0

    from .clickup_escritura import ClickUpEscritura
    cu = ClickUpEscritura()
    if a.apply:
        motivos = {m.strip().upper() for m in a.motivos.split(",") if m.strip()}
        if not motivos or not motivos <= {"A1", "A2", "A3"}:
            ap.error("--apply requiere --motivos con A1, A2 y/o A3")
        return aplicar(cu, a.apply, motivos, solo, ahora)
    return revertir(cu, a.revert, solo, ahora)


if __name__ == "__main__":
    sys.exit(main())
