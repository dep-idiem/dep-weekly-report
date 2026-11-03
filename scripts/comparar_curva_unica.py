"""Comparación del dry-run antes/después de la curva programada única (TAREA_curva_programada_unica, 2026-11-03).

Lee dos carpetas de dry-run (CSV + resumen.json) y escribe reportes/curva_unica/: tabla por proyecto en curso y lista de
tareas que cayeron al respaldo, por JP. Con --recurrentes, calcula además (solo informativo, no va a la hoja) la
programada que tendrían las listas de los programas de servicio continuo (lee ClickUp).

Uso:
    python scripts/comparar_curva_unica.py --antes reportes/dry_run/2026-11-03_preliminar_antes \
        --despues reportes/dry_run/2026-11-03_preliminar [--recurrentes] [--titulo "..."]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PRUEBA = {"1400570000001689", "1400570000002107"}      # PJ-TEST y PJ-EJEMPLO (retenidas, no son proyectos)


def leer(d: Path, t: str) -> list[dict]:
    with (d / f"{t}.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def num(x, dec=1) -> str:
    if x in (None, ""):
        return "—"
    return f"{float(x):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x) -> str:
    return "—" if x in (None, "") else f"{float(x) * 100:.0f} %"


def fecha(x) -> str:
    return f"{x[8:10]}-{x[5:7]}-{x[:4]}" if x else "—"


def lb_txt(p: dict, ms: dict | None, lb_nuevas: set[str]) -> str:
    e = p.get("estado_linea_base") or ""
    if p["list_id"] in lb_nuevas:
        return "se congela"
    if e == "vigente":
        return f"Rev. {ms.get('rev_linea_base') or 0}" if ms else "vigente"
    return {"provisional": "provisional", "sin_linea_base": "sin LB"}.get(e, e)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--antes", type=Path, required=True)
    ap.add_argument("--despues", type=Path, required=True)
    ap.add_argument("--salida", type=Path, default=ROOT / "reportes" / "curva_unica")
    ap.add_argument("--recurrentes", action="store_true")
    ap.add_argument("--titulo", default="Curva programada única: dry-run del corte preliminar del 03-11-2026")
    a = ap.parse_args()

    pa = {p["list_id"]: p for p in leer(a.antes, "proyectos")}
    pd = {p["list_id"]: p for p in leer(a.despues, "proyectos")}
    ma = {m["list_id"]: m for m in leer(a.antes, "metricas_semanales")}
    md = {m["list_id"]: m for m in leer(a.despues, "metricas_semanales")}
    nuevas_a = {f["list_id"] for f in leer(a.antes, "linea_base")}
    nuevas_d = {f["list_id"] for f in leer(a.despues, "linea_base")}
    res = json.loads((a.despues / "resumen.json").read_text(encoding="utf-8"))["capa_porciones"]
    activos = sorted((p for p in pd.values() if p["estado_proyecto"] == "en_curso" and p["list_id"] not in PRUEBA),
                     key=lambda p: p["codigo"])

    filas, respaldo, anticipadas = [], [], []
    for p in activos:
        lid, cod = p["list_id"], p["codigo"]
        d, an, ant = md.get(lid, {}), ma.get(lid, {}), pa.get(lid, {})
        r = res.get(cod, {})
        cambios = []
        lb_a, lb_d = lb_txt(ant, an, nuevas_a), lb_txt(p, d, nuevas_d)
        if lb_a != lb_d:
            cambios.append(f"línea base: {lb_a} → {lb_d}")
        if (ant.get("programada_modo") or "") != (p.get("programada_modo") or "") and "programada_modo" in ant:
            cambios.append(f"programada_modo {ant.get('programada_modo') or '—'} → {p.get('programada_modo') or '—'}")
        if (an.get("hh_prog_acum") or "") != (d.get("hh_prog_acum") or ""):
            cambios.append(f"HH prog. al corte {num(an.get('hh_prog_acum'))} → {num(d.get('hh_prog_acum'))}")
        if (an.get("avance_prog") or "") != (d.get("avance_prog") or ""):
            cambios.append(f"avance prog. {pct(an.get('avance_prog'))} → {pct(d.get('avance_prog'))}")
        if (ant.get("programa") or "") != (p.get("programa") or ""):
            cambios.append(f"pasa al programa {p['programa']} (fuera de la curva S)")
        filas.append([cod, p["nombre_corto"][:40], fecha(p["fecha_inicio"]), fecha(p["fecha_termino_vigente"]),
                      num(r.get("presupuesto_hh"), 0) if r.get("presupuesto_hh") else num(d.get("hh_actuales_clickup"), 0),
                      p.get("programada_modo") or "—", num(d.get("hh_gastadas_acum")), p.get("estado_curva") or "",
                      "; ".join(cambios) or "sin cambios"])
        for x in r.get("respaldo", []):
            respaldo.append((p["jp_nombre"], cod, p["nombre_corto"], x))
        for x in r.get("anticipadas", []):
            anticipadas.append((p["jp_nombre"], cod, p["nombre_corto"], x))

    a.salida.mkdir(parents=True, exist_ok=True)
    enc = ["Proyecto", "Nombre", "Inicio lista", "Término lista", "Presupuesto (HH)", "programada_modo",
           "Horas registradas", "Estado", "Qué cambia respecto del reporte actual"]
    lineas = [f"# {a.titulo}", "",
              f"Antes: `{a.antes.name}`. Después: `{a.despues.name}`. "
              f"{len(activos)} listas activas (sin PJ-TEST ni PJ-EJEMPLO). Sin escrituras en Sheets.", "",
              "| " + " | ".join(enc) + " |", "|" + "---|" * len(enc)]
    lineas += ["| " + " | ".join(str(c) for c in f) + " |" for f in filas]
    (a.salida / "dry_run_2026-11-03.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    out = ["# Tareas que cayeron al respaldo (sus HH se reparten entre el inicio y el término de la lista)", "",
           "Una fila por tarea del presupuesto (HH Presupuestadas sin ancestro con HH) sin fechas, con fechas al revés o "
           "fuera del plazo de la lista. Para pasarle a cada JP.", ""]
    for jp in sorted({x[0] for x in respaldo}):
        out += [f"## {jp}", "", "| Proyecto | Tarea | HH | Inicio | Término | Motivo |", "|---|---|---|---|---|---|"]
        out += [f"| {cod} · {nom[:35]} | {x['nombre']} | {num(x['hh'], 1)} | {fecha(x['start'])} | {fecha(x['due'])} | "
                f"{x['motivo']} |" for j, cod, nom, x in respaldo if j == jp]
        out.append("")
    if anticipadas:
        out += ["## Informativo: tareas que empiezan hasta 30 días antes del inicio de la lista (usan sus fechas)", "",
                "Advertencia `inicio_anterior_contractual` (prioridad baja). No van al respaldo.", "",
                "| JP | Proyecto | Tarea | HH | Inicio | Días antes |", "|---|---|---|---|---|---|"]
        out += [f"| {j} | {cod} · {nom[:35]} | {x['nombre']} | {num(x['hh'], 1)} | {fecha(x['start'])} | {x['dias']} |"
                for j, cod, nom, x in anticipadas]
        out.append("")
    if a.recurrentes:
        out += recurrentes(pd)
    (a.salida / "respaldo_por_jp.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Escrito {a.salida}: {len(filas)} proyectos, {len(respaldo)} tareas al respaldo, "
          f"{len(anticipadas)} con inicio anticipado")
    return 0


def recurrentes(pd: dict) -> list[str]:
    """Solo informativo: la programada que tendrían las listas de programas (no se dibuja)."""
    from dep_clickup import ClickUpClient
    from dep_reportes import metricas as MT, programada as PROG
    from dep_reportes.adaptador_clickup import a_tareas_metrica
    from dep_reportes.modos import por_nombre
    cal = por_nombre("dep").cal
    cu = ClickUpClient()
    out = ["## Listas de programas (recurrentes): programada que tendrían (no se dibuja)", "",
           "| Lista | Presupuesto (HH) | Modo | Tareas al respaldo |", "|---|---|---|---|"]
    for p in sorted((p for p in pd.values() if p.get("programa") and p["estado_proyecto"] == "en_curso"),
                    key=lambda p: p["codigo"]):
        lista, ts = cu.get_list_info(p["list_id"]), cu.list_tasks(p["list_id"])
        u = [t for t in MT.universo(a_tareas_metrica(ts)) if (t.estado or "").lower() != "no aplica"]
        g = PROG.programar(u, lista.start.date() if lista.start else None, lista.due.date() if lista.due else None, cal)
        det = "; ".join(f"{x.nombre} ({x.motivo})" for x in g.respaldo[:4]) + (" …" if len(g.respaldo) > 4 else "")
        out.append(f"| {p['codigo']} · {p['nombre_corto'][:35]} | {num(g.presupuesto, 0)} | {g.modo or '—'} | "
                   f"{len(g.respaldo)}{': ' + det if det else ''} |")
    return out + [""]


if __name__ == "__main__":
    sys.exit(main())
