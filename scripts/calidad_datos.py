"""Detector de problemas de datos sobre todas las listas de un folder de ClickUp. Solo lectura.

Uso:
    python scripts/calidad_datos.py [--folder 901316452800] [--space 901312509139]

Genera reportes/validacion/calidad_datos.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dep_clickup import ClickUpClient  # noqa: E402
from dep_clickup.config import TZ  # noqa: E402
from dep_clickup.dates import ms_to_local  # noqa: E402
from dep_clickup.naming import list_code  # noqa: E402
from dep_reportes import calidad, metricas as m  # noqa: E402
from dep_reportes.adaptador_clickup import a_horas, a_tareas_metrica, horas_por_tarea  # noqa: E402
from dep_reportes.inspeccion import fmt_ubicacion, ubicacion_campos  # noqa: E402

SALIDA = ROOT / "reportes" / "validacion"
TIPOS = [calidad.DOBLE_CONTEO, calidad.HH_EN_PADRE, calidad.SIN_FECHAS, calidad.DUE_ANTES_START,
         calidad.HH_VS_ESTIMATE, calidad.AVANCE_SIN_HORAS, calidad.HORAS_SIN_AVANCE]
CORTO = {calidad.DOBLE_CONTEO: "doble conteo", calidad.HH_EN_PADRE: "HH en no-hoja",
         calidad.SIN_FECHAS: "HH sin fechas", calidad.DUE_ANTES_START: "due<start",
         calidad.HH_VS_ESTIMATE: "HH≠estimate", calidad.AVANCE_SIN_HORAS: "avance sin horas",
         calidad.HORAS_SIN_AVANCE: "horas sin avance"}
CAMPOS_PROYECTO = ["Fecha Entrega Contractual", "Fecha Límite Interna", "Fecha Revisión Director",
                   "Fecha Entrega Real", "JP Responsable"]


def md_tabla(cab, filas) -> str:
    out = ["| " + " | ".join(cab) + " |", "|" + "|".join("---" for _ in cab) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in f) + " |" for f in filas]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", default="901316452800", help="folder PJ Ingeniería")
    ap.add_argument("--space", default="901312509139", help="space Proyectos Activos (para estimar peticiones)")
    ap.add_argument("--desde", type=dt.date.fromisoformat, default=dt.date(2025, 1, 1))
    a = ap.parse_args()
    hoy = dt.datetime.now(TZ)

    cu = ClickUpClient()
    team_id = cu.get_team_id()
    miembros = cu.list_members(team_id)
    listas = cu.list_lists(a.folder)
    entradas = cu.list_time_entries(a.desde, hoy.date(), folder_id=a.folder,
                                    assignees=[x.id for x in miembros], team_id=team_id)
    horas_lista: dict[str, list] = {}
    for e in entradas:
        horas_lista.setdefault(e.list_id, []).append(e)

    filas, detalle, ubic_filas = [], [], []
    incumplen, con_errores = [], []
    paginas_total = 0
    for li in sorted(listas, key=lambda x: x.name):
        antes = cu.request_log.get("/list/{id}/task", 0)
        raw = cu.get_list(li.id)
        defs = cu.get_list_custom_fields(li.id)
        tareas = cu.list_tasks(li.id)
        paginas_total += cu.request_log.get("/list/{id}/task", 0) - antes
        tm = a_tareas_metrica(tareas)
        padres = {t.id: t.parent for t in tm}
        hpt = horas_por_tarea(a_horas(horas_lista.get(li.id, [])), padres, acumular_en_ancestros=True)
        adv = calidad.detectar(tm, hpt, {t.id: t.time_estimate_h for t in tareas})
        cnt = Counter(x.tipo for x in adv)
        codigo = list_code(li.name) or li.id
        if calidad.incumple_hh_en_hojas(adv):
            incumplen.append(codigo)
        if any(x.severidad == "error" for x in adv):
            con_errores.append(codigo)
        u = m.universo(tm)
        filas.append([codigo, li.status or "", len(tareas), len(u), f"{m.total_hh(tm):g}"] +
                     [cnt.get(t, 0) or "" for t in TIPOS])
        asig = (raw.get("assignee") or {}).get("username") or "(vacío)"
        due = ms_to_local(raw.get("due_date")).date() if raw.get("due_date") else "(vacío)"
        ub = {x.nombre: fmt_ubicacion(x) for x in ubicacion_campos(defs, tareas, CAMPOS_PROYECTO)}
        ubic_filas.append([codigo, asig, due] + [ub[c] for c in CAMPOS_PROYECTO])
        relevantes = [x for x in adv if x.tipo != calidad.HH_VS_ESTIMATE]
        if relevantes:
            detalle.append(f"\n### {codigo}\n\n{li.name}\n")
            detalle.append(md_tabla(["Severidad", "Tipo", "Tarea", "Detalle"],
                                    [[x.severidad, x.tipo, x.tarea, x.detalle]
                                     for x in sorted(relevantes, key=lambda x: (x.severidad, x.tipo, x.tarea))]))
    req_folder = cu.request_count

    # Estimacion para el Space completo: los folders del space traen sus listas y task_count.
    folders = cu.get(f"/space/{a.space}/folder", {"archived": "false"}).get("folders", [])
    sueltas = cu.get(f"/space/{a.space}/list", {"archived": "false"}).get("lists", [])
    listas_space = [l for f in folders for l in f.get("lists", [])] + sueltas
    paginas_tc = sum(max(1, math.ceil((l.get("task_count") or 0) / 100)) for l in listas_space)
    # task_count no cuenta subtareas: se corrige con la razon paginas reales / paginas segun task_count del folder.
    tc_folder = sum(max(1, math.ceil((li.task_count or 0) / 100)) for li in listas)
    paginas_est = math.ceil(paginas_tc * paginas_total / tc_folder) if tc_folder else paginas_tc
    req_space = 1 + 2 + len(listas_space) * 2 + paginas_est + 1   # team + folders/listas + (lista+campos) + tareas + time entries

    n = len(listas)
    L = [f"# Calidad de datos — folder PJ Ingeniería ({a.folder})\n",
         f"Corrida {hoy:%Y-%m-%d %H:%M} (America/Santiago). Solo lectura; el detector no corrige nada.\n",
         "## Resumen\n",
         f"- Listas (proyectos) revisadas: **{n}** (no archivadas).",
         f"- Incumplen la convención \"HH Presupuestadas solo en tareas hoja\": **{len(incumplen)} de {n}**"
         + (f" ({', '.join(incumplen)})." if incumplen else "."),
         f"- Con doble conteo (HH en un padre **y** en alguna subtarea): "
         f"**{sum(1 for f in filas if f[5])}** proyectos.",
         f"- Con algún error (doble conteo, HH sin fechas o due < start): **{len(con_errores)}**.",
         f"- Time entries leídas para el folder: {len(entradas)} de {len({e.user_id for e in entradas})} personas "
         f"(una sola petición con `folder_id` y los {len(miembros)} miembros como `assignee`).",
         "",
         "Tipos: *doble conteo* = HH en un padre y en alguna subtarea (error: el TotalHH lo suma dos veces); "
         "*HH en no-hoja* = HH en una tarea con subtareas sin HH (no duplica, pero incumple la convención); "
         "*HH≠estimate* = HH Presupuestadas distinta del time estimate (informativo; detalle omitido abajo); "
         "*avance sin horas* / *horas sin avance* comparan el avance real con las horas registradas en la tarea "
         "y sus subtareas.\n",
         md_tabla(["Proyecto", "Estado", "Tareas", "Tareas con HH", "TotalHH"] + [CORTO[t] for t in TIPOS], filas),
         "\n## Dónde viven JP y fechas del proyecto\n",
         "Responsable y due de la **lista** (atributos propios de ClickUp), y en qué nivel tienen valor los custom fields "
         "de fecha y de \"JP Responsable\".\n",
         md_tabla(["Proyecto", "Responsable de la lista", "Due de la lista"] + CAMPOS_PROYECTO, ubic_filas),
         "\n## Peticiones a la API\n",
         f"- Este folder ({n} listas): **{req_folder} peticiones** medidas "
         f"({', '.join(f'{k}: {v}' for k, v in sorted(cu.request_log.items()) if not k.startswith('/space'))}); "
         f"{paginas_total} páginas de tareas.",
         f"- Space Proyectos Activos: {len(folders)} folders y {len(listas_space)} listas "
         f"({len(sueltas)} sin folder). Estimación para procesarlo completo: **~{req_space} peticiones** "
         f"(1 `/team` + 2 para descubrir folders y listas + 2 por lista [lista y campos] + ~{paginas_est} páginas de "
         f"tareas + 1 de time entries con `space_id`). Las páginas salen de `task_count` ({paginas_tc}), que no cuenta "
         f"subtareas, corregido por la razón medida en este folder ({paginas_total} páginas reales vs {tc_folder} según "
         f"`task_count`). Con el tope de 90/min del cliente son ~{math.ceil(req_space / 90)} min.",
         "\n## Detalle por proyecto\n",
         ] + detalle
    SALIDA.mkdir(parents=True, exist_ok=True)
    out = SALIDA / "calidad_datos.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{n} listas; incumplen HH-en-hojas: {len(incumplen)}; con errores: {len(con_errores)}; "
          f"peticiones folder={req_folder}, space estimado={req_space}")
    print(f"informe: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
