"""Migracion del programa CMP-SHM, etapa 2: dry-run de las operaciones, con la inversa de cada una.

Lee plan.csv (etapa 1, con las decisiones) y el estado actual de ClickUp, y arma la secuencia de operaciones en el
orden de propuesta.md. Comprueba cada precondicion contra el estado actual (lista, padre, estado, horas).

Uso:
    python scripts/migracion_cmp_ejecutar.py                 # dry-run: solo lectura
    python scripts/migracion_cmp_ejecutar.py --prueba-padre  # prueba de cambio de padre con una tarea sin horas, y
                                                             # vuelta atras (unica escritura de este script)

    python scripts/migracion_cmp_ejecutar.py --ejecutar      # ejecuta (autorizado por Ale el 06-10-2026)
    python scripts/migracion_cmp_ejecutar.py --verificar     # verificacion 1: horas por tarea contra la foto

--ejecutar vuelve a leer ClickUp, arma el dry-run y se niega si hay operaciones bloqueadas. Cada operacion comprueba
el estado de la tarea justo antes de escribir y el resultado justo despues; ante lo inesperado se detiene. Todo queda
en ejecucion.log (una linea JSON por operacion, con su inversa). Las operaciones manuales se registran como pendientes.

Genera en reportes/migracion_cmp/:
    dry_run_<fecha>.md / operaciones_<fecha>.csv   las operaciones, en orden, con su inversa
    estado_<fecha>.json                            la foto de ClickUp usada (respaldo de lo que se borra)
    prueba_padre_<fecha>.json                      el resultado de la prueba (con --prueba-padre)
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import migracion_cmp_plan as PLAN  # noqa: E402
from dep_clickup import ClickUpClient, config  # noqa: E402
from dep_clickup.naming import list_code  # noqa: E402

SALIDA = PLAN.SALIDA
LISTA_ID = {PLAN.GENERAL: PLAN.L0019, PLAN.INFORMES: PLAN.LINF, PLAN.MODELOS: PLAN.LMOD}
# Fases de contrato existentes (Informes y Modelos); las de General se crean en el paso 2.
FASE_ID = {(PLAN.LINF, PLAN.MLC): "86ajeuyv1", (PLAN.LINF, PLAN.APILADOR): "86ajeuyyx",
           (PLAN.LMOD, PLAN.MLC): "86ajfuy8z", (PLAN.LMOD, PLAN.APILADOR): "86ajfuy94",
           (PLAN.LMOD, PLAN.DESARROLLO): "86ajfv5tw"}
NUEVA = "<nueva: {fase} en General>"
RENOMBRAR_FASES = {"86ajeuyv1": PLAN.MLC, "86ajeuyyx": PLAN.APILADOR, "86ajfuy8z": PLAN.MLC, "86ajfuy94": PLAN.APILADOR,
                   "86ajfv5tw": PLAN.DESARROLLO}
# Paso 1 (Ale, 06-10): cada lista conserva su codigo, porque el reporte saca el codigo del nombre
# (dep_clickup.naming.list_code) y con el asocia el saldo del Timetracker. 0147 no se archiva: queda vacia, solo_consumo.
NOMBRES_LISTA = {
    PLAN.L0019: "PJ-2025.0019 | CMP-SHM General | CMP",
    PLAN.LINF: "PJ-2025.0019-0147 | CMP-SHM Informes | CMP",
    PLAN.LMOD: "PJ-2025.0019-0147 | CMP-SHM Modelos | CMP",
    PLAN.L0147: "PJ-2025.0147 | CMP-SHM Apilador (histórico) | CMP",
}

# Prueba de cambio de padre: subtarea de plantilla sin horas, en una fase que se archiva, a otra fase que se archiva.
PRUEBA = {"task_id": "86agx8x9b", "nombre": "2.1 Hitos y Estados de Pago", "lista": PLAN.L0019,
          "padre_original": "86agx8x86", "padre_prueba": "86agx8xm2"}   # 02 Contrato y Comercial -> 99 Cierre

API = "API v2"
MANUAL = "manual (interfaz)"
SIN_PROBAR = " · sin probar"


@dataclass
class Op:
    paso: str
    tipo: str
    task_id: str
    objeto: str
    lista: str
    antes: str
    despues: str
    via: str
    inversa: str
    via_inversa: str
    horas: str = ""
    precondicion: str = ""
    estado: str = "ok"          # ok / aviso / bloqueado
    nota: str = ""
    n: int = field(default=0)
    params: dict = field(default_factory=dict)   # lo que ejecuta --ejecutar (vacio: manual o solo lectura)


def leer_plan() -> list[dict]:
    with (SALIDA / "plan.csv").open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def construir(plan: list[dict], L: dict[str, PLAN.Lista], info: dict[str, dict]) -> list[Op]:
    ops: list[Op] = []
    por_tid = {t.id: (lid, t) for lid, x in L.items() for t in x.tareas}
    fila = {r["task_id"]: r for r in plan}

    def actual(tid: str):
        return por_tid.get(tid, (None, None))

    def chequear(op: Op, r: dict | None, horas_max: float | None = None) -> Op:
        """Precondicion: la tarea sigue en la lista, con el padre y el estado de la foto del plan."""
        lid, t = actual(op.task_id)
        if t is None:
            op.estado, op.nota = "bloqueado", "la tarea ya no está en las 4 listas"
            return op
        if r:
            dif = []
            if lid != r["list_id"]:
                dif.append(f"lista {r['list_id']}→{lid}")
            if (t.parent or "") != r["padre_id"]:
                dif.append(f"padre {r['padre_id'] or '(nivel 0)'}→{t.parent or '(nivel 0)'}")
            if t.status != r["estado"]:
                dif.append(f"estado '{r['estado']}'→'{t.status}'")
            h_ahora = L[lid].sub(t.id)
            if abs(h_ahora - float(r["horas_con_subtareas"])) >= 0.005:     # el plan guarda 2 decimales
                dif.append(f"horas {r['horas_con_subtareas']}→{h_ahora:.2f}")
            if dif:
                op.estado, op.nota = "aviso", "cambió desde el plan: " + "; ".join(dif)
            op.horas = f"{h_ahora:.2f}"
            if horas_max is not None and h_ahora > horas_max:
                op.estado, op.nota = "bloqueado", f"tiene {h_ahora:.2f} h (se esperaban {horas_max:g})"
        return op

    # Paso 0: respaldo
    ops.append(Op("0 respaldo", "respaldo", "", "estado completo de las 4 listas", "", "", "estado_<fecha>.json",
                  "lectura", "—", "—", precondicion="antes de cualquier escritura"))

    # Paso 1: renombrar listas
    for lid, nuevo in NOMBRES_LISTA.items():
        conserva = list_code(nuevo) == list_code(info[lid]["name"])
        ops.append(Op("1 renombrar listas", "renombrar lista", lid, info[lid]["name"], lid, info[lid]["name"],
                      nuevo, f"{API} PUT /list/{{id}} name", f"renombrar a '{info[lid]['name']}'",
                      f"{API} PUT /list/{{id}} name", estado="ok" if conserva else "bloqueado",
                      nota=f"conserva el código {list_code(nuevo)}" if conserva else "cambia el código de la lista",
                      params={"kind": "rename_list", "list_id": lid, "name": nuevo, "prev": info[lid]["name"]}))

    # Paso 2: crear fases en General y renombrar las de Informes y Modelos
    for fase in (PLAN.MLC, PLAN.APILADOR):
        ya = [t for t in L[PLAN.L0019].raices if t.name.strip() == fase]
        ops.append(Op("2 fases", "crear fase", "", fase, PLAN.L0019, "(no existe)", NUEVA.format(fase=fase),
                      f"{API} POST /list/{{id}}/task", "eliminar la fase (solo si quedó vacía)",
                      f"{API} DELETE /task/{{id}}",
                      nota=f"ya existe: {ya[0].id} (se usa esa)" if ya else "",
                      params={"kind": "create_phase", "list_id": PLAN.L0019, "name": fase, "ref": "@" + fase}))
    for tid, nuevo in RENOMBRAR_FASES.items():
        lid, t = actual(tid)
        op = Op("2 fases", "renombrar fase", tid, t.name if t else "?", lid or "", t.name if t else "?", nuevo,
                f"{API} PUT /task/{{id}} name", f"renombrar a '{t.name if t else '?'}'", f"{API} PUT /task/{{id}} name",
                params={"kind": "rename_task", "task_id": tid, "name": nuevo, "prev": t.name if t else ""})
        ops.append(chequear(op, fila.get(tid)))

    # Paso 3: movimientos (solo la tarea mas alta de cada rama; las subtareas van con ella)
    mover = [r for r in plan if r["accion"] == "mover" and not r["motivo"].startswith("va con su")]
    # primero las subtareas que salen de una rama que tambien se mueve (4.6 antes que 05 Instalacion)
    mover.sort(key=lambda r: -int(r["nivel"]))
    # Pruebas del 06-10: v2 "parent" cambia el padre dentro de la lista (prueba 1), lleva una subtarea a otra lista si
    # el padre nuevo esta en ella (prueba 2) y convierte una tarea de nivel 0 en subtarea (prueba 3). v3 home_list
    # rechaza subtareas ("Only root tasks..."); solo se usa si una tarea de nivel 0 no cambia de lista con v2.
    for r in mover:
        destino = LISTA_ID[r["lista_destino"]]
        fase_id = FASE_ID.get((destino, r["fase_destino"])) or NUEVA.format(fase=r["fase_destino"])
        padre_orig = r["padre_id"] or "(nivel 0)"
        otra_lista = r["list_id"] != destino
        lid, t = actual(r["task_id"])
        if t is not None and lid == destino and t.parent == fase_id:
            ops.append(Op("3 mover", "cambiar padre", r["task_id"], r["nombre"], destino, f"padre {padre_orig}",
                          f"subtarea de {r['fase_destino']} ({fase_id})", "hecha en la prueba 2", f"padre {padre_orig}",
                          f"{API} PUT /task/{{id}} parent", horas=f"{L[lid].sub(t.id):.2f}",
                          nota="ya está en su destino (prueba 2, 06-10)"))
            continue
        params = {"kind": "set_parent", "task_id": r["task_id"], "parent": FASE_ID.get((destino, r["fase_destino"]))
                  or "@" + r["fase_destino"], "list": destino, "prev_parent": r["padre_id"] or None,
                  "prev_list": r["list_id"], "root": r["nivel"] == "0"}
        if r["nivel"] == "0":
            op = Op("3 mover", "convertir en subtarea", r["task_id"], r["nombre"], destino,
                    f"nivel 0 en {PLAN.LISTAS[r['list_id']]}",
                    f"subtarea de {r['fase_destino']} ({fase_id})" + (f" en {r['lista_destino']}" if otra_lista else ""),
                    f"{API} PUT /task/{{id}} parent",
                    "convertir en tarea de nivel 0" + (f" y volver a {PLAN.LISTAS[r['list_id']]}" if otra_lista else ""),
                    MANUAL, params=params)
            chequear(op, r)
            if op.estado == "ok":
                op.nota = ("probado (prueba 3); a otra lista combina las pruebas 2 y 3: se verifica lista y padre, y "
                           "si la lista no cambia se usa v3 home_list" if otra_lista else "probado (prueba 3)")
            ops.append(op)
        else:
            op = Op("3 mover", "cambiar padre" + (" (a otra lista)" if otra_lista else ""), r["task_id"], r["nombre"],
                    destino, f"padre {padre_orig}" + (f" en {PLAN.LISTAS[r['list_id']]}" if otra_lista else ""),
                    f"subtarea de {r['fase_destino']} ({fase_id})" + (f" en {r['lista_destino']}" if otra_lista else ""),
                    f"{API} PUT /task/{{id}} parent", f"padre {padre_orig}", f"{API} PUT /task/{{id}} parent",
                    params=params)
            chequear(op, r)
            if op.estado == "ok":
                op.nota = ("probado (prueba 2); la vuelta entre listas usa el mismo mecanismo" if otra_lista
                           else "probado (prueba 1, ida y vuelta)")
            ops.append(op)

    # Paso 4: cierres
    cerrar = [r for r in plan if r["accion"] == "cerrar"]
    for r in cerrar:
        lid, t = actual(r["task_id"])
        if t and t.cerrada:
            ops.append(chequear(Op("4 cerrar", "sin cambio", r["task_id"], r["nombre"], lid, t.status, t.status,
                                   "—", "—", "—", nota="ya está cerrada"), r))
            # subtareas abiertas de una tarea ya cerrada (Desarrollo de Superacion de Umbrales)
            for d in L[lid].desc(t.id):
                if not d.cerrada:
                    destino = "cancelado" if L[lid].sub(d.id) == 0 and d.status == "to do" else "completado"
                    ops.append(Op("4 cerrar", "cambiar estado", d.id, d.name, lid, d.status, destino,
                                  f"{API} PUT /task/{{id}} status", f"estado '{d.status}'",
                                  f"{API} PUT /task/{{id}} status", horas=f"{L[lid].sub(d.id):.2f}",
                                  nota=f"subtarea abierta de '{t.name}' (cerrada)",
                                  params={"kind": "set_status", "task_id": d.id, "status": destino, "prev": d.status}))
            continue
        destino = "completado" if r["nivel"] == "0" or float(r["horas_con_subtareas"]) > 0 or r["estado"] != "to do" \
            else "cancelado"
        op = Op("4 cerrar", "cambiar estado", r["task_id"], r["nombre"], r["list_id"], r["estado"], destino,
                f"{API} PUT /task/{{id}} status", f"estado '{r['estado']}'", f"{API} PUT /task/{{id}} status",
                precondicion="después del paso 3 (las tareas que salen de la fase ya salieron)",
                params={"kind": "set_status", "task_id": r["task_id"], "status": destino, "prev": r["estado"]})
        ops.append(chequear(op, r))

    # Paso 5: eliminaciones (las 4 plantillas VT)
    for r in [r for r in plan if r["accion"] == "eliminar"]:
        lid, t = actual(r["task_id"])
        n = len(list(L[lid].desc(t.id))) if t else 0
        op = Op("5 eliminar", "eliminar", r["task_id"], r["nombre"], r["list_id"], f"existe ({n} subtareas)",
                "eliminada", f"{API} DELETE /task/{{id}}", "restaurar desde la papelera de ClickUp", MANUAL,
                precondicion="0 h en la tarea y sus subtareas; respaldo JSON del paso 0",
                nota="irreversible por API", params={"kind": "delete", "task_id": r["task_id"]})
        ops.append(chequear(op, r, horas_max=0))

    # Paso 6: manuales
    for r in [r for r in plan if r["accion"] == "archivar" and (r["nivel"] == "0" or r["task_id"] == "86ajenaam")]:
        op = Op("6 manual", "archivar fase", r["task_id"], r["nombre"], r["list_id"], r["estado"], "archivada",
                MANUAL, "desarchivar", MANUAL, precondicion="después de los pasos 3 a 5")
        chequear(op, r, horas_max=0)
        lid_t, t = actual(r["task_id"])
        if r["task_id"] == PRUEBA_N0["task_id"] and t is not None and t.parent == PRUEBA_N0["padre_nuevo"]:
            op.estado, op.despues = "ok", "archivada con 99 Cierre"
            op.nota = "desde la prueba 3 está dentro de 99 Cierre: se archiva con ella"
        elif r["list_id"] == PLAN.L0147 and op.estado == "ok":
            op.nota = "en 0147 se archivan las fases; la lista queda activa y vacía (solo_consumo)"
        ops.append(op)
    for lid, orden in ((PLAN.L0019, f"00 Administración · {PLAN.MLC} · {PLAN.APILADOR}"),
                       (PLAN.LINF, f"{PLAN.MLC} · {PLAN.APILADOR}"),
                       (PLAN.LMOD, f"{PLAN.MLC} · {PLAN.APILADOR} · {PLAN.DESARROLLO}")):
        ops.append(Op("6 manual", "ordenar fases", lid, PLAN.LISTAS[lid], lid, "orden actual", orden, MANUAL,
                      "orden anterior (queda en el respaldo)", MANUAL))

    # Paso 7: configuracion (en el repo, ya preparada) y verificacion
    ops.append(Op("7 config", "config/programas.json", "", "General por fase, 0147 solo_consumo, RD/RA (RE alias)",
                  "", "contrato fijo 0019 en General; 0147 en la vista", "contrato_por_defecto 0019; 0147 solo_consumo",
                  "commit en el repo y publicación", "git revert", "git", estado="aviso",
                  nota="hecho en el repo, sin commit. Publicarlo después de los pasos 3 a 6: antes, solo_consumo sacaría "
                       "de la vista las tareas que 0147 todavía tiene", params={"kind": "publicar"}))
    ops.append(Op("8 verificar", "verificar horas", "", "horas_por_tarea.csv y totales.csv", "", "", "sin diferencias",
                  "lectura", "—", "—", precondicion="después de ejecutar: --verificar", params={"kind": "verificar"}))
    for i, op in enumerate(ops, 1):
        op.n = i
    return ops


def escribir(ops: list[Op], fecha: str, generado: str) -> Path:
    cols = list(asdict(ops[0]).keys())
    cols.remove("n")
    with (SALIDA / f"operaciones_{fecha}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["n", *cols])
        w.writeheader()
        w.writerows({**asdict(o), "params": json.dumps(o.params, ensure_ascii=False)} for o in ops)
    cuenta = collections.Counter(o.estado for o in ops)
    md = [f"# Migración CMP-SHM: dry-run de la etapa 2", "",
          f"Estado de ClickUp leído el {generado}. El dry-run no escribe nada (las pruebas de abajo se "
          f"corrieron aparte). {len(ops)} operaciones: {cuenta['ok']} ok, {cuenta['aviso']} con aviso, "
          f"{cuenta['bloqueado']} bloqueadas.", ""]
    prueba = SALIDA / f"prueba_padre_{fecha}.json"
    if prueba.exists():
        p = json.loads(prueba.read_text(encoding="utf-8"))
        md += [f"- **Prueba 1, cambio de padre dentro de la lista** ({p['tarea']['nombre']} "
               f"`{p['tarea']['task_id']}`, 0 h: 02 Contrato y Comercial → 99 Cierre → 02 Contrato y Comercial): "
               f"{p['resultado']}; sin efectos laterales: {'sí' if p['sin_efectos_laterales'] else 'NO'}."]
    prueba2 = SALIDA / f"prueba_subtarea_{fecha}.json"
    if prueba2.exists():
        p = json.loads(prueba2.read_text(encoding="utf-8"))
        md += [f"- **Prueba 2, subtarea a otra lista** ({p['tarea']['nombre']} `{p['tarea']['task_id']}`, 0 h, "
               f"0019 → Modelos / MLC 0019): v3 home_list responde 400 \"Only root tasks can be moved to a new home "
               f"list\" y no cambia nada; v2 parent con la fase de la otra lista la mueve. {p['resultado']}; sin "
               f"efectos laterales: {'sí' if p.get('sin_efectos_laterales') else 'NO'}. Queda en su destino del plan.",
               ""]
    prueba3 = SALIDA / f"prueba_nivel0_{fecha}.json"
    if prueba3.exists():
        p = json.loads(prueba3.read_text(encoding="utf-8"))
        md.insert(-1, f"- **Prueba 3, tarea de nivel 0 → subtarea** ({p['tarea']['nombre']} de 0147 `{p['tarea']['task_id']}`, "
                      f"0 h, bajo 99 Cierre de 0147; las dos se archivan): {p['resultado']}; sin efectos laterales: "
                      f"{'sí' if p.get('sin_efectos_laterales') else 'NO'}.")
    for paso, grupo in _agrupar(ops):
        md += [f"## Paso {paso}", "", "| # | Operación | Tarea | Antes → después | Vía | Inversa (vía) | h | Estado |",
               "|---|---|---|---|---|---|---:|---|"]
        for o in grupo:
            est = o.estado if not o.nota else f"{o.estado}: {o.nota}"
            md.append(f"| {o.n} | {o.tipo} | {o.objeto} `{o.task_id}` | {o.antes} → {o.despues} | {o.via} | "
                      f"{o.inversa} ({o.via_inversa}) | {o.horas} | {est} |".replace("\n", " "))
        md.append("")
    ruta = SALIDA / f"dry_run_{fecha}.md"
    ruta.write_text("\n".join(md), encoding="utf-8")
    return ruta


def _agrupar(ops: list[Op]):
    grupos: dict[str, list[Op]] = {}
    for o in ops:
        grupos.setdefault(o.paso, []).append(o)
    return grupos.items()


# --- Prueba de cambio de padre (unica escritura) ---------------------------------------------------

def prueba_padre(cu: ClickUpClient, fecha: str) -> dict:
    tid, ida, vuelta = PRUEBA["task_id"], PRUEBA["padre_prueba"], PRUEBA["padre_original"]
    s = requests.Session()
    s.headers.update({"Authorization": config.api_token(), "Content-Type": "application/json"})

    def leer() -> dict:
        t = cu.get(f"/task/{tid}")
        return {"parent": t.get("parent"), "list": (t.get("list") or {}).get("id"), "status": t["status"]["status"],
                "time_spent": t.get("time_spent"), "date_updated": t.get("date_updated"), "name": t["name"]}

    def poner_padre(padre: str) -> dict:
        assert padre in (ida, vuelta)            # la prueba no puede escribir otra cosa
        r = s.put(f"{config.API_BASE}/task/{tid}", json={"parent": padre}, timeout=30)
        return {"status_http": r.status_code, "cuerpo": r.text[:300]}

    out = {"tarea": PRUEBA, "pasos": []}
    antes = leer()
    out["pasos"].append({"paso": "antes", **antes})
    if antes["parent"] != vuelta or antes["list"] != PRUEBA["lista"] or antes["name"] != PRUEBA["nombre"]:
        out["resultado"] = "no se ejecutó: la tarea no está como se esperaba"
        return out
    out["pasos"].append({"paso": "PUT parent → 99 Cierre", **poner_padre(ida)})
    medio = leer()
    out["pasos"].append({"paso": "después de la ida", **medio})
    out["pasos"].append({"paso": "PUT parent → 02 Contrato y Comercial", **poner_padre(vuelta)})
    final = leer()
    out["pasos"].append({"paso": "después de la vuelta", **final})
    ok_ida, ok_vuelta = medio["parent"] == ida, final["parent"] == vuelta
    out["resultado"] = ("ok: cambia de padre y vuelve" if ok_ida and ok_vuelta else
                        f"falla: ida {'ok' if ok_ida else 'no'}, vuelta {'ok' if ok_vuelta else 'NO: revisar a mano'}")
    out["sin_efectos_laterales"] = all(final[k] == antes[k] for k in ("list", "status", "time_spent", "name"))
    (SALIDA / f"prueba_padre_{fecha}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# Pruebas 2 y 3 (Ale, 06-10): 8.1.b, 0 h y sin subtareas, va a su destino del plan (Modelos -> MLC 0019).
# 2: mover la subtarea a otra lista. 3: convertir en subtarea (si al moverla quedo en nivel 0). Queda en su lugar final.
PRUEBA_SUB = {"task_id": "86ahr82ux", "nombre": "8.1.b Informe de Calibración del Modelo Inicial",
              "lista_origen": PLAN.L0019, "padre_origen": "86agx8xgr", "lista_destino": PLAN.LMOD,
              "fase_destino": "86ajfuy8z"}
API_V3 = "https://api.clickup.com/api/v3"


def prueba_subtarea(cu: ClickUpClient, fecha: str) -> dict:
    P = PRUEBA_SUB
    tid = P["task_id"]
    s = requests.Session()
    s.headers.update({"Authorization": config.api_token(), "Content-Type": "application/json"})

    def leer() -> dict:
        t = cu.get(f"/task/{tid}", {"include_subtasks": "true"})
        return {"parent": t.get("parent"), "list": (t.get("list") or {}).get("id"), "status": t["status"]["status"],
                "time_spent": t.get("time_spent"), "subtareas": len(t.get("subtasks") or []), "name": t["name"],
                "date_updated": t.get("date_updated")}

    out: dict = {"tarea": P, "pasos": []}
    antes = leer()
    out["pasos"].append({"paso": "antes", **antes})
    if (antes["parent"], antes["list"], antes["name"], antes["subtareas"]) != (P["padre_origen"], P["lista_origen"],
                                                                                P["nombre"], 0) or antes["time_spent"]:
        out["resultado"] = "no se ejecutó: la tarea no está como se esperaba"
        return out
    team = cu.get_team_id()
    r = s.put(f"{API_V3}/workspaces/{team}/tasks/{tid}/home_list/{P['lista_destino']}", timeout=30)
    out["pasos"].append({"paso": "prueba 2: PUT v3 home_list → Modelos", "status_http": r.status_code,
                         "cuerpo": r.text[:300]})
    medio = leer()
    out["pasos"].append({"paso": "después de mover", **medio})
    if r.status_code >= 300 or medio["list"] != P["lista_destino"]:
        # v3 solo mueve tareas raiz ("Only root tasks can be moved to a new home list"): se prueba el cambio de padre
        # a la fase de la otra lista (v2). Si queda en un estado raro, se devuelve a su padre original.
        r = s.put(f"{config.API_BASE}/task/{tid}", json={"parent": P["fase_destino"]}, timeout=30)
        out["pasos"].append({"paso": "prueba 2b: PUT v2 parent → MLC 0019 de Modelos", "status_http": r.status_code,
                             "cuerpo": r.text[:300]})
        final = leer()
        out["pasos"].append({"paso": "después del cambio de padre", **final})
        ok = final["parent"] == P["fase_destino"] and final["list"] == P["lista_destino"]
        if not ok and final["parent"] != P["padre_origen"]:
            r = s.put(f"{config.API_BASE}/task/{tid}", json={"parent": P["padre_origen"]}, timeout=30)
            out["pasos"].append({"paso": "vuelta al padre original", "status_http": r.status_code})
            out["pasos"].append({"paso": "después de la vuelta", **leer()})
        out["prueba_2"] = ("ok vía v2 parent: queda en Modelos como subtarea de MLC 0019" if ok
                           else "falla: ni v3 home_list ni v2 parent la llevan a la otra lista")
        out["resultado"] = out["prueba_2"]
        out["sin_efectos_laterales"] = all(final[k] == antes[k] for k in ("status", "time_spent", "name", "subtareas"))
        return out
    out["prueba_2"] = f"ok: cambia de lista; queda {'en nivel 0' if not medio['parent'] else 'con padre ' + medio['parent']}"
    if medio["parent"]:
        out["resultado"] = "prueba 2 ok; prueba 3 no se hizo: la subtarea conservó su padre al moverse"
        return out
    r = s.put(f"{config.API_BASE}/task/{tid}", json={"parent": P["fase_destino"]}, timeout=30)
    out["pasos"].append({"paso": "prueba 3: PUT v2 parent → MLC 0019 (Modelos)", "status_http": r.status_code,
                         "cuerpo": r.text[:300]})
    final = leer()
    out["pasos"].append({"paso": "después de colgar", **final})
    out["prueba_3"] = ("ok: la tarea de nivel 0 queda como subtarea" if final["parent"] == P["fase_destino"]
                       else "falla: sigue sin padre")
    out["resultado"] = f"{out['prueba_2']} · {out['prueba_3']}"
    out["sin_efectos_laterales"] = all(final[k] == antes[k] for k in ("status", "time_spent", "name", "subtareas"))
    return out


# Prueba 3 (Ale, 06-10, opcion b): tarea de nivel 0 -> subtarea con "00 Administracion" de 0147 (0 h, sin subtareas)
# bajo "99 Cierre" de 0147. Las dos se archivan a mano: el resultado final es el mismo y no se revierte.
PRUEBA_N0 = {"task_id": "86ahaa2tn", "nombre": "00 Administración", "lista": PLAN.L0147, "padre_nuevo": "86ahaa3cg"}


def prueba_nivel0(cu: ClickUpClient) -> dict:
    P = PRUEBA_N0
    tid = P["task_id"]
    s = requests.Session()
    s.headers.update({"Authorization": config.api_token(), "Content-Type": "application/json"})

    def leer() -> dict:
        t = cu.get(f"/task/{tid}", {"include_subtasks": "true"})
        return {"parent": t.get("parent"), "list": (t.get("list") or {}).get("id"), "status": t["status"]["status"],
                "time_spent": t.get("time_spent"), "subtareas": len(t.get("subtasks") or []), "name": t["name"],
                "date_updated": t.get("date_updated")}

    out: dict = {"tarea": P, "pasos": []}
    antes = leer()
    out["pasos"].append({"paso": "antes", **antes})
    if antes["parent"] or antes["list"] != P["lista"] or antes["name"] != P["nombre"] or antes["subtareas"] \
            or antes["time_spent"]:
        out["resultado"] = "no se ejecutó: la tarea no está como se esperaba"
        return out
    r = s.put(f"{config.API_BASE}/task/{tid}", json={"parent": P["padre_nuevo"]}, timeout=30)
    out["pasos"].append({"paso": "prueba 3: PUT v2 parent → 99 Cierre (0147)", "status_http": r.status_code,
                         "cuerpo": r.text[:300]})
    final = leer()
    out["pasos"].append({"paso": "después", **final})
    out["ok"] = final["parent"] == P["padre_nuevo"]
    out["resultado"] = "ok: la tarea de nivel 0 queda como subtarea" if out["ok"] else "falla: sigue en nivel 0"
    out["sin_efectos_laterales"] = all(final[k] == antes[k] for k in ("list", "status", "time_spent", "name", "subtareas"))
    return out


# --- Ejecucion (autorizada por Ale el 06-10-2026) ---------------------------------------------------

LOG = SALIDA / "ejecucion.log"
PUBLICAR = ["config/programas.json", "dep_reportes/programas.py", "dep_reportes/esquema.py", "tests/test_programas.py",
            "docs/looker_programas.md"]


class Detener(RuntimeError):
    pass


class Ejecutor:
    def __init__(self, cu: ClickUpClient):
        self.cu = cu
        self.s = requests.Session()
        self.s.headers.update({"Authorization": config.api_token(), "Content-Type": "application/json"})
        self.refs: dict[str, str] = {}          # "@MLC 0019" -> id de la fase creada
        self.team = cu.get_team_id()

    def log(self, **x) -> None:
        x = {"ts": dt.datetime.now().isoformat(timespec="seconds"), **x}
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(x, ensure_ascii=False, default=str) + "\n")

    def tarea(self, tid: str) -> dict:
        t = self.cu.get(f"/task/{tid}", {"include_subtasks": "true"})
        return {"id": t["id"], "name": t["name"], "parent": t.get("parent"), "list": (t.get("list") or {}).get("id"),
                "status": t["status"]["status"], "time_spent": t.get("time_spent") or 0,
                "subtareas": [x["id"] for x in t.get("subtasks") or []]}

    def http(self, metodo: str, url: str, body: dict | None = None) -> requests.Response:
        self.cu._throttle()
        r = self.s.request(metodo, url, json=body, timeout=30)
        if r.status_code >= 300:
            raise Detener(f"{metodo} {url} -> HTTP {r.status_code}: {r.text[:300]}")
        return r

    def ref(self, x: str | None) -> str | None:
        if x and x.startswith("@"):
            if x not in self.refs:
                raise Detener(f"la fase {x[1:]} no fue creada")
            return self.refs[x]
        return x

    def correr(self, op: Op) -> dict:
        p = op.params
        k = p["kind"]
        v2 = config.API_BASE
        if k == "rename_list":
            antes = self.cu.get(f"/list/{p['list_id']}")["name"]
            if antes == p["name"]:
                return {"resultado": "ya estaba hecha", "antes": antes}
            if antes != p["prev"]:
                raise Detener(f"la lista se llama '{antes}', se esperaba '{p['prev']}'")
            self.http("PUT", f"{v2}/list/{p['list_id']}", {"name": p["name"]})
            despues = self.cu.get(f"/list/{p['list_id']}")["name"]
            if despues != p["name"]:
                raise Detener(f"después del cambio se llama '{despues}'")
            return {"resultado": "ok", "antes": antes, "despues": despues,
                    "inversa": {"PUT": f"/list/{p['list_id']}", "body": {"name": antes}}}
        if k == "create_phase":
            lista = self.cu.list_tasks_raw(p["list_id"], include_subtasks=False)
            ya = [t for t in lista if not t.get("parent") and t["name"].strip() == p["name"]]
            if ya:
                self.refs[p["ref"]] = ya[0]["id"]
                return {"resultado": "ya existía", "fase_id": ya[0]["id"]}
            r = self.http("POST", f"{v2}/list/{p['list_id']}/task", {"name": p["name"]})
            nuevo = r.json()["id"]
            self.refs[p["ref"]] = nuevo
            return {"resultado": "ok", "fase_id": nuevo, "inversa": {"DELETE": f"/task/{nuevo}",
                                                                     "condicion": "solo si quedó vacía"}}
        if k == "rename_task":
            a = self.tarea(p["task_id"])
            if a["name"] == p["name"]:
                return {"resultado": "ya estaba hecha", "antes": a}
            if a["name"] != p["prev"]:
                raise Detener(f"la tarea se llama '{a['name']}', se esperaba '{p['prev']}'")
            self.http("PUT", f"{v2}/task/{p['task_id']}", {"name": p["name"]})
            d = self.tarea(p["task_id"])
            if d["name"] != p["name"]:
                raise Detener(f"después del cambio se llama '{d['name']}'")
            return {"resultado": "ok", "antes": a, "despues": d,
                    "inversa": {"PUT": f"/task/{p['task_id']}", "body": {"name": a["name"]}}}
        if k == "set_parent":
            padre = self.ref(p["parent"])
            a = self.tarea(p["task_id"])
            if a["parent"] == padre and a["list"] == p["list"]:
                return {"resultado": "ya estaba hecha", "antes": a}
            if a["parent"] != p["prev_parent"] or a["list"] != p["prev_list"]:
                raise Detener(f"la tarea está en lista {a['list']} con padre {a['parent']}; se esperaba "
                              f"{p['prev_list']} / {p['prev_parent']}")
            llamadas = [f"PUT v2 /task/{p['task_id']} parent={padre}"]
            self.http("PUT", f"{v2}/task/{p['task_id']}", {"parent": padre})
            d = self.tarea(p["task_id"])
            if d["list"] != p["list"] and p["root"] and d["parent"] is None:
                # nivel 0 que no cambio de lista con v2: v3 home_list (acepta tareas raiz) y luego el padre
                self.http("PUT", f"{API_V3}/workspaces/{self.team}/tasks/{p['task_id']}/home_list/{p['list']}")
                self.http("PUT", f"{v2}/task/{p['task_id']}", {"parent": padre})
                llamadas += [f"PUT v3 home_list {p['list']}", f"PUT v2 /task/{p['task_id']} parent={padre}"]
                d = self.tarea(p["task_id"])
            if d["parent"] != padre or d["list"] != p["list"]:
                raise Detener(f"después quedó en lista {d['list']} con padre {d['parent']}")
            if d["status"] != a["status"] or d["time_spent"] != a["time_spent"] or set(d["subtareas"]) != set(a["subtareas"]):
                raise Detener(f"efecto lateral: antes {a}, después {d}")
            inv = ({"PUT": f"/task/{p['task_id']}", "body": {"parent": a["parent"]}} if a["parent"] else
                   {"manual": f"convertir en tarea de nivel 0 en la lista {a['list']}"})
            return {"resultado": "ok", "llamadas": llamadas, "antes": a, "despues": d, "inversa": inv}
        if k == "set_status":
            a = self.tarea(p["task_id"])
            if a["status"] == p["status"]:
                return {"resultado": "ya estaba hecha", "antes": a}
            if a["status"] != p["prev"]:
                raise Detener(f"estado '{a['status']}', se esperaba '{p['prev']}'")
            self.http("PUT", f"{v2}/task/{p['task_id']}", {"status": p["status"]})
            d = self.tarea(p["task_id"])
            if d["status"] != p["status"]:
                raise Detener(f"después quedó en '{d['status']}'")
            return {"resultado": "ok", "antes": a, "despues": d,
                    "inversa": {"PUT": f"/task/{p['task_id']}", "body": {"status": a["status"]}}}
        if k == "delete":
            t = self.cu.get(f"/task/{p['task_id']}", {"include_subtasks": "true"})
            sub = [self.cu.get(f"/task/{x['id']}") for x in t.get("subtasks") or []]
            horas = sum(int(x.get("time_spent") or 0) for x in [t, *sub])
            if horas:
                raise Detener(f"tiene {horas / 3_600_000:.2f} h registradas")
            self.http("DELETE", f"{v2}/task/{p['task_id']}")
            return {"resultado": "ok", "respaldo": {"tarea": t, "subtareas": sub},
                    "inversa": {"manual": "restaurar desde la papelera de ClickUp (tarea y subtareas)"}}
        raise Detener(f"operación desconocida: {k}")


def publicar() -> dict:
    import subprocess
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    t = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_programas.py"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    if t.returncode:
        raise Detener("las pruebas de programas fallan: " + t.stdout[-500:])
    git("add", *PUBLICAR)
    msg = ("Programa CMP-SHM: General por fase (0019 por defecto), 0147 solo_consumo y entregables RD/RA\n\n"
           "Migración de ClickUp del 06-10-2026: la lista General asigna el contrato por fase (00 Administración, "
           "05 Reportes y las fases compartidas históricas van a 0019, también su saldo del Timetracker); la lista "
           "0147 queda vacía y solo cuenta en el consumo; entregables con frecuencia mensual (IM, RD) o por evento "
           "(VT, RA, con RE como alias). Nueva columna frecuencia en programa_entregables.\n\n"
           "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>")
    c = git("commit", "-m", msg)
    if c.returncode:
        raise Detener("git commit: " + c.stdout + c.stderr)
    sha = git("rev-parse", "HEAD").stdout.strip()
    ps = git("push", "origin", "main")
    if ps.returncode:
        raise Detener(f"commit {sha} hecho, pero git push falló: " + ps.stderr[-500:])
    return {"resultado": "ok", "commit": sha, "archivos": PUBLICAR, "inversa": {"git": f"git revert {sha}"}}


def ejecutar(cu: ClickUpClient, ops: list[Op]) -> None:
    bloqueadas = [o for o in ops if o.estado == "bloqueado"]
    if bloqueadas:
        raise SystemExit("Hay operaciones bloqueadas; no se ejecuta: " + "; ".join(f"{o.n} {o.objeto}" for o in bloqueadas))
    ex = Ejecutor(cu)
    ex.log(evento="inicio", operaciones=len(ops))
    for o in ops:
        base = {"n": o.n, "paso": o.paso, "tipo": o.tipo, "task_id": o.task_id, "objeto": o.objeto,
                "inversa_plan": f"{o.inversa} ({o.via_inversa})"}
        k = o.params.get("kind")
        if not k or k == "verificar":
            ex.log(**base, resultado="pendiente (manual)" if o.via == MANUAL or o.via.startswith(MANUAL) else "omitida",
                   via=o.via)
            continue
        try:
            res = publicar() if k == "publicar" else ex.correr(o)
        except Detener as e:
            ex.log(**base, resultado="DETENIDA", error=str(e), params=o.params)
            print(f"DETENIDA en la operación {o.n} ({o.tipo}: {o.objeto}): {e}")
            raise SystemExit(1)
        ex.log(**base, params={**o.params, **({"parent": ex.ref(o.params["parent"])} if k == "set_parent" else {})},
               **res)
        print(f"{o.n:3} {res['resultado']:16} {o.tipo}: {o.objeto}")
    ex.log(evento="fin", fases_creadas=ex.refs)
    print("Fases creadas:", ex.refs)


# --- Verificaciones 1 y 2 ---------------------------------------------------------------------------

FOTO = SALIDA / "crudo_2026-10-06.json"          # foto de la etapa 1 (la de plan.csv y horas_por_tarea.csv)


# Fases que Ale archivo a mano (verificacion 2): 8 de General, 6 de 0147 (00 Administracion va dentro de 99 Cierre)
# y 00 Administracion de Modelos.
ARCHIVADAS = {"86agx8x86", "86agx8xc7", "86agx8x83", "86agx8xf2", "86agx8xav", "86agx8xej", "86agx8xm2", "86agx8x82",
              "86ahaa358", "86ahaa2hc", "86ahaa2jg", "86ahaa38r", "86ahaa3cg", "86ajev1up", "86ajenaam"}


def tareas_archivadas(cu: ClickUpClient, list_id: str) -> list[dict]:
    out, page = [], 0
    while True:
        data = cu.get(f"/list/{list_id}/task", {"page": page, "subtasks": "true", "include_closed": "true",
                                                "archived": "true"})
        out += data.get("tasks", [])
        if data.get("last_page", True) or not data.get("tasks"):
            return out
        page += 1


def verificar(cu: ClickUpClient, fecha: str, n: int = 1) -> None:
    """Cada entrada de tiempo de la foto sigue existiendo, en la misma tarea y con la misma duracion; las horas por
    tarea coinciden con horas_por_tarea.csv; el total de las 4 listas (incluida 0147) es el de la foto; cada lista
    tiene las horas esperadas; y cada tarea movida esta en su lista de destino. La 2 suma las tareas archivadas: las
    15 fases archivadas a mano lo estan, con sus subtareas, sin horas, y 0147 no tiene tareas activas."""
    foto = json.loads(FOTO.read_text(encoding="utf-8"))
    ahora = PLAN.descargar()
    archivadas: dict[str, dict] = {}
    if n >= 2:
        for lid, x in ahora["listas"].items():
            for t in tareas_archivadas(cu, lid):
                archivadas[t["id"]] = {**t, "_lista": lid}
            x["tasks_archivadas"] = [t for t in archivadas.values() if t["_lista"] == lid]
    (SALIDA / f"estado_post{n if n > 1 else ''}_{fecha}.json").write_text(json.dumps(ahora, ensure_ascii=False),
                                                                          encoding="utf-8")
    ent_foto = {e["id"]: e for x in foto["listas"].values() for e in x["time_entries"] if int(e["duration"]) >= 0}
    ent_ahora: dict[str, dict] = {}
    lista_de_entrada: dict[str, str] = {}
    for lid, x in ahora["listas"].items():
        for e in x["time_entries"]:
            if int(e["duration"]) >= 0 and e["id"] not in ent_ahora:
                ent_ahora[e["id"]] = e
                lista_de_entrada[e["id"]] = lid
    lista_de_tarea = {t["id"]: lid for lid, x in ahora["listas"].items() for t in x["tasks"]}
    lista_de_tarea.update({i: t["_lista"] for i, t in archivadas.items()})
    h = lambda ms: int(ms) / 3_600_000
    tid = lambda e: (e.get("task") or {}).get("id", "")

    faltan = [e for i, e in ent_foto.items() if i not in ent_ahora]
    cambian = [(e, ent_ahora[i]) for i, e in ent_foto.items() if i in ent_ahora
               and (tid(e) != tid(ent_ahora[i]) or int(e["duration"]) != int(ent_ahora[i]["duration"]))]
    nuevas = [e for i, e in ent_ahora.items() if i not in ent_foto]

    por_tarea_ahora: collections.Counter[str] = collections.Counter()
    for i in ent_foto:
        if i in ent_ahora:
            por_tarea_ahora[tid(ent_ahora[i])] += h(ent_ahora[i]["duration"])
    with (SALIDA / "horas_por_tarea.csv").open(encoding="utf-8-sig") as fh:
        esperado = {r["task_id"]: r for r in csv.DictReader(fh)}
    filas, dif_tareas = [], 0
    for t_id in sorted(set(esperado) | set(por_tarea_ahora)):
        e = float(esperado[t_id]["horas"]) if t_id in esperado else 0.0
        a = por_tarea_ahora.get(t_id, 0.0)
        ok = abs(a - e) < 0.005
        dif_tareas += not ok
        filas.append({"task_id": t_id, "nombre": esperado.get(t_id, {}).get("nombre", ""),
                      "lista_antes": esperado.get(t_id, {}).get("lista_actual", ""),
                      "lista_ahora": PLAN.LISTAS.get(lista_de_tarea.get(t_id, ""), "(no está en las 4 listas)"),
                      "horas_foto": f"{e:.2f}", "horas_ahora": f"{a:.2f}", "ok": "sí" if ok else "NO"})
    for f in filas:
        f["archivada"] = "sí" if f["task_id"] in archivadas else ""
    with (SALIDA / f"verificacion_{n}_{fecha}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)

    total_foto = sum(h(e["duration"]) for e in ent_foto.values())
    total_ahora = sum(por_tarea_ahora.values())
    por_lista: collections.Counter[str] = collections.Counter()
    for i in ent_foto:
        if i in ent_ahora:
            por_lista[lista_de_tarea.get(tid(ent_ahora[i]), "?")] += h(ent_ahora[i]["duration"])
    with (SALIDA / "totales.csv").open(encoding="utf-8-sig") as fh:
        esp_lista = {r["list_id"]: float(r["horas"]) for r in csv.DictReader(fh) if r["momento"] == "despues_esperado"}
    mal_ubicadas = []
    for r in leer_plan():
        if r["accion"] == "mover":
            destino = LISTA_ID[r["lista_destino"]]
            if lista_de_tarea.get(r["task_id"]) != destino:
                mal_ubicadas.append(f"{r['task_id']} {r['nombre']}: en {lista_de_tarea.get(r['task_id'], '?')}, "
                                    f"se esperaba {destino}")
    eliminadas_presentes = [r["task_id"] for r in leer_plan() if r["accion"] == "eliminar"
                            and r["task_id"] in lista_de_tarea]
    # Cambios de estado fuera del plan: estado leido al iniciar --ejecutar contra el de ahora.
    pre = json.loads((SALIDA / f"estado_{fecha}.json").read_text(encoding="utf-8"))
    st_pre = {t["id"]: (t["name"], t["status"]["status"]) for x in pre["listas"].values() for t in x["tasks"]}
    st_ahora = {t["id"]: t["status"]["status"] for x in ahora["listas"].values() for t in x["tasks"]}
    st_ahora.update({i: t["status"]["status"] for i, t in archivadas.items()})
    with (SALIDA / f"operaciones_{fecha}.csv").open(encoding="utf-8-sig") as fh:
        planeados = {json.loads(r["params"]).get("task_id"): json.loads(r["params"]).get("status")
                     for r in csv.DictReader(fh) if json.loads(r["params"] or "{}").get("kind") == "set_status"}
    estados_fuera = [f"{i} {n}: '{a}' → '{st_ahora[i]}'" + (" (estaba en el plan)" if planeados.get(i) == st_ahora[i]
                                                            else "")
                     for i, (n, a) in st_pre.items() if i in st_ahora and st_ahora[i] != a and i not in planeados]
    estados_plan_mal = [f"{i}: se esperaba '{s}', está '{st_ahora.get(i)}'" for i, s in planeados.items()
                        if i in st_ahora and st_ahora[i] != s]

    extra = []
    if n >= 2:
        activas = {t["id"] for x in ahora["listas"].values() for t in x["tasks"]}
        no_archivadas = sorted(ARCHIVADAS - set(archivadas))
        siguen_activas = sorted(ARCHIVADAS & activas)
        hijas_activas = []
        por_padre = collections.defaultdict(list)
        for x in ahora["listas"].values():
            for t in x["tasks"]:
                por_padre[t.get("parent")].append(t)
        for i in ARCHIVADAS:
            hijas_activas += [f"{t['id']} {t['name']} (de {i})" for t in por_padre.get(i, [])]
        h_archivadas = sum(h(e["duration"]) for i, e in ent_ahora.items() if tid(e) in archivadas)
        h_archivadas_foto = sum(float(r["horas"]) for i, r in esperado.items() if i in archivadas)
        activas_0147 = [f"{t['id']} {t['name']}" for t in ahora["listas"][PLAN.L0147]["tasks"]]
        extra = [f"| Fases archivadas (de {len(ARCHIVADAS)}) | {len(ARCHIVADAS) - len(no_archivadas)}"
                 + (f"; faltan: {', '.join(no_archivadas)}" if no_archivadas else "") + " |",
                 f"| Tareas archivadas en total (fases y subtareas) | {len(archivadas)} |",
                 f"| Fases que deberían estar archivadas y siguen activas | {len(siguen_activas)} |",
                 f"| Subtareas activas bajo una fase archivada | {len(hijas_activas)} |",
                 f"| Horas en tareas archivadas (foto / ahora) | {h_archivadas_foto:.2f} / {h_archivadas:.2f} h |",
                 f"| Tareas activas en la lista 0147 | {len(activas_0147)} |"]
        extra_det = (("Fases sin archivar", no_archivadas), ("Subtareas activas bajo fases archivadas", hijas_activas),
                     ("Tareas activas en 0147", activas_0147))
    md = [f"# Migración CMP-SHM: verificación {n}", "", f"Leído el {ahora['generado']}. Foto: {FOTO.name}."
          + (" Incluye tareas archivadas." if n >= 2 else ""), "",
          "| Control | Resultado |", "|---|---|",
          f"| Entradas de la foto | {len(ent_foto)} |",
          f"| Faltan | {len(faltan)} |",
          f"| Cambiaron de tarea o de duración | {len(cambian)} |",
          f"| Total de la foto / ahora (mismas entradas) | {total_foto:,.2f} / {total_ahora:,.2f} h |",
          f"| Tareas con horas distintas de horas_por_tarea.csv | {dif_tareas} de {len(filas)} |",
          f"| Tareas movidas fuera de su lista de destino | {len(mal_ubicadas)} |",
          f"| Plantillas VT eliminadas que siguen apareciendo | {len(eliminadas_presentes)} |",
          f"| Estados del plan que no quedaron | {len(estados_plan_mal)} |",
          f"| Cambios de estado fuera del plan | {len(estados_fuera)} |",
          *extra,
          f"| Entradas nuevas después de la foto (no entran en la comparación) | {len(nuevas)} "
          f"({sum(h(e['duration']) for e in nuevas):.2f} h) |", "",
          "| Lista | Esperado | Ahora (entradas de la foto) |", "|---|---:|---:|"]
    for lid, nombre in ((PLAN.L0019, "General"), (PLAN.LINF, "Informes"), (PLAN.LMOD, "Modelos"),
                        (PLAN.L0147, "0147 (histórico)")):
        md.append(f"| {nombre} | {esp_lista.get(lid, 0):,.2f} | {por_lista.get(lid, 0):,.2f} |")
    for titulo, xs in (("Entradas que faltan", [f"{e['id']} {tid(e)} {h(e['duration']):.2f} h" for e in faltan]),
                       ("Entradas que cambiaron", [f"{a['id']}: {tid(a)} {h(a['duration']):.2f} h → {tid(b)} "
                                                   f"{h(b['duration']):.2f} h" for a, b in cambian]),
                       ("Tareas fuera de su destino", mal_ubicadas),
                       ("Estados del plan que no quedaron", estados_plan_mal),
                       ("Cambios de estado fuera del plan", estados_fuera),
                       *(extra_det if n >= 2 else ()),
                       ("Entradas nuevas", [f"{e['id']} {tid(e)} {(e.get('task') or {}).get('name', '')} "
                                            f"{h(e['duration']):.2f} h ({e['user'].get('username', '')})"
                                            for e in nuevas])):
        if xs:
            md += ["", f"## {titulo}", "", *[f"- {x}" for x in xs]]
    md += ["", f"Detalle tarea por tarea: verificacion_{n}_{fecha}.csv"]
    (SALIDA / f"verificacion_{n}_{fecha}.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:20]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prueba-padre", action="store_true", help="cambia el padre de una tarea sin horas y lo devuelve")
    ap.add_argument("--prueba-subtarea", action="store_true",
                    help="pruebas 2 y 3: mueve 8.1.b a Modelos y la cuelga de MLC 0019 (su destino del plan)")
    ap.add_argument("--prueba-nivel0", action="store_true",
                    help="prueba 3: cuelga '00 Administración' de 0147 de su '99 Cierre' (las dos se archivan)")
    ap.add_argument("--ejecutar", action="store_true", help="ejecuta la migración (autorizada el 06-10-2026)")
    ap.add_argument("--verificar", type=int, nargs="?", const=1, choices=[1, 2],
                    help="verificación 1 (horas por tarea contra la foto) o 2 (además, tareas archivadas)")
    a = ap.parse_args()
    fecha = dt.date.today().isoformat()
    cu = ClickUpClient()
    if a.verificar:
        verificar(cu, fecha, a.verificar)
        return
    if a.prueba_nivel0:
        out = prueba_nivel0(cu)
        (SALIDA / f"prueba_nivel0_{fecha}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if a.prueba_padre:
        print(json.dumps(prueba_padre(cu, fecha), ensure_ascii=False, indent=1))
        return
    if a.prueba_subtarea:
        out = prueba_subtarea(cu, fecha)
        (SALIDA / f"prueba_subtarea_{fecha}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                              encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    crudo = PLAN.descargar()
    (SALIDA / f"estado_{fecha}.json").write_text(json.dumps(crudo, ensure_ascii=False), encoding="utf-8")
    L = {lid: PLAN.Lista(lid, crudo["listas"][lid]) for lid in PLAN.LISTAS}
    info = {lid: crudo["listas"][lid]["info"] for lid in PLAN.LISTAS}
    ops = construir(leer_plan(), L, info)
    ruta = escribir(ops, fecha, crudo["generado"])
    print(f"{len(ops)} operaciones en {ruta}")
    if a.ejecutar:
        ejecutar(cu, ops)
        return
    for o in ops:
        if o.estado != "ok":
            print(f"  {o.n:3} [{o.estado}] {o.tipo}: {o.objeto} — {o.nota}")


if __name__ == "__main__":
    main()
