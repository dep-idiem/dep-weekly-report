"""Lectura del informe semanal: ClickUp (solo GET) y la planilla de ausencias de Drive."""
from __future__ import annotations

import datetime as dt
import io
import sys

from openpyxl import load_workbook

from dep_clickup import ClickUpClient

ESPACIO = "901312509139"            # Proyectos Activos
FOLDER_ADMIN = "901318508657"       # Administración (listas ADM-…)
VENTANA_DIAS = 30
DESDE = dt.date(2025, 10, 1)        # primer registro en ClickUp: las horas acumuladas parten de aquí
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CAMPOS = ["id", "name", "parent", "start_date", "due_date", "time_estimate"]


def listas_fuente(cu: ClickUpClient) -> list[dict]:
    """Listas «PJ-…» de cualquier folder de Proyectos Activos y todas las de Administración, con su JP."""
    out = []

    def agregar(lista: dict, folder_id: str | None, folder: str, archivada: bool) -> None:
        if folder_id == FOLDER_ADMIN or lista["name"].startswith("PJ-"):
            jp = lista.get("assignee") or {}
            out.append({"id": lista["id"], "name": lista["name"], "folder": folder, "archived": archivada,
                        "jp": jp.get("username")})

    for f in cu.get(f"/space/{ESPACIO}/folder", {"archived": "false"})["folders"]:
        for archived in ("false", "true"):
            for l in cu.get(f"/folder/{f['id']}/list", {"archived": archived})["lists"]:
                agregar(l, f["id"], f["name"].strip(), archived == "true")
    for l in cu.get(f"/space/{ESPACIO}/list", {"archived": "false"})["lists"]:
        agregar(l, None, "(sin folder)", False)
    return out


def bajar_tareas(cu: ClickUpClient) -> dict:
    """Tareas y subtareas, abiertas y cerradas, de las listas fuente (mismos campos que horas_asignadas)."""
    listas = listas_fuente(cu)
    tareas: dict[str, dict] = {}
    for i, l in enumerate(listas, 1):
        crudas = cu.list_tasks_raw(l["id"], include_subtasks=True, include_closed=True)
        print(f"  [{i}/{len(listas)}] {len(crudas):4d} tareas  {l['name'][:60]}", file=sys.stderr)
        for t in crudas:
            r = {k: t.get(k) for k in _CAMPOS}
            r["list"] = {"id": (t.get("list") or {}).get("id"), "name": (t.get("list") or {}).get("name")}
            r["status"] = (t.get("status") or {}).get("status")
            r["assignees"] = [{"id": a["id"], "username": a.get("username")} for a in t.get("assignees") or []]
            tareas.setdefault(r["id"], r)
    return {"listas": listas, "tareas": list(tareas.values())}


def bajar_entradas(cu: ClickUpClient, hasta: dt.date, desde: dt.date = DESDE) -> list[dict]:
    """Time entries de todos los miembros por ventanas de 30 días (el endpoint exige assignee)."""
    team = cu.get_team_id()
    ids = [m.id for m in cu.list_members(team)]
    entradas, vistos, ini = [], set(), desde
    while ini <= hasta:
        fin = min(ini + dt.timedelta(days=VENTANA_DIAS - 1), hasta)
        for e in cu.list_time_entries_raw(ini, fin, assignees=ids, team_id=team):
            if e.get("id") not in vistos:
                vistos.add(e.get("id"))
                entradas.append(e)
        ini = fin + dt.timedelta(days=1)
    return entradas


def miembros(cu: ClickUpClient) -> list[dict]:
    """id, nombre, correo y fecha de ingreso al workspace (date_joined; si no hay, date_invited)."""
    team = cu.get_team_id()
    for t in cu._teams()["teams"]:
        if str(t["id"]) == str(team):
            return [{"id": int(m["user"]["id"]), "nombre": m["user"].get("username") or "",
                     "email": (m["user"].get("email") or "").lower(),
                     "ingreso_ms": m["user"].get("date_joined") or m["user"].get("date_invited")}
                    for m in t.get("members", [])]
    raise RuntimeError(f"Workspace {team} no visible con este token")


# --- Drive -------------------------------------------------------------------------------------

def planilla_ausencias(file_id: str):
    """Exporta la planilla (hoja de Google) a xlsx y devuelve la primera hoja, solo valores."""
    from .drive import API, cliente
    r = cliente().s.get(f"{API}/files/{file_id}/export", params={"mimeType": XLSX, "supportsAllDrives": "true"}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"Drive {r.status_code} al exportar la planilla de ausencias: {r.text[:300]}")
    return load_workbook(io.BytesIO(r.content), data_only=True).worksheets[0]


def planilla_local(ruta):
    return load_workbook(ruta, data_only=True).worksheets[0]
