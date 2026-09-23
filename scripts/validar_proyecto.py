"""Metricas de un proyecto desde ClickUp y validacion contra el Excel manual (pasos 4a y 4b). Solo lectura.

Uso:
    python scripts/validar_proyecto.py --list-id 901328186343 --control 2026-09-19 --fin 2026-10-02

Genera reportes/validacion/<codigo>.md y reportes/validacion/<codigo>_curva_s.png.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dep_clickup import ClickUpClient  # noqa: E402
from dep_clickup.config import TZ  # noqa: E402
from dep_clickup.dates import ms_to_local  # noqa: E402
from dep_clickup.naming import list_code  # noqa: E402
from dep_reportes import calidad, comparacion as cmp, fixture_excel, metricas as m  # noqa: E402
from dep_reportes.adaptador_clickup import CAMPO_AVANCE, a_horas, a_tareas_metrica, horas_por_tarea  # noqa: E402
from dep_reportes.calendario import SIN_FERIADOS  # noqa: E402
from dep_reportes.grafico import curva_s_png  # noqa: E402
from dep_reportes.inspeccion import CAMPOS_INTERES, fmt_ubicacion, ubicacion_campos  # noqa: E402

SALIDA = ROOT / "reportes" / "validacion"


def f2(x: float | None, nd: int = 2) -> str:
    return "#N/A" if x is None else f"{x:,.{nd}f}".replace(",", " ")


def md_tabla(cab: list[str], filas: list[list]) -> str:
    out = ["| " + " | ".join(cab) + " |", "|" + "|".join("---" for _ in cab) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in f) + " |" for f in filas]
    return "\n".join(out)


def buscar_fixture(codigo: str) -> Path | None:
    num = codigo.split("-", 1)[-1] if codigo else ""
    for p in sorted((ROOT / "fixtures").glob("*.xlsx")):
        if num and num in p.name.replace("_", "."):
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-id", required=True)
    ap.add_argument("--control", required=True, type=dt.date.fromisoformat, help="fecha de control C")
    ap.add_argument("--fin", required=True, type=dt.date.fromisoformat, help="fecha de termino del proyecto")
    ap.add_argument("--fixture", type=Path, help="Excel de referencia (por defecto se busca en fixtures/)")
    ap.add_argument("--desde", type=dt.date.fromisoformat, default=dt.date(2025, 1, 1),
                    help="inicio del rango de time entries")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    C, fin, cal = a.control, a.fin, SIN_FERIADOS
    hoy = dt.datetime.now(TZ)

    # --- Lectura de ClickUp -------------------------------------------------------------------
    cu = ClickUpClient()
    team_id = cu.get_team_id()
    miembros = cu.list_members(team_id)
    lista = cu.get_list(a.list_id)
    codigo = list_code(lista.get("name", "")) or a.list_id
    defs = cu.get_list_custom_fields(a.list_id)
    tareas = cu.list_tasks(a.list_id)
    entradas = cu.list_time_entries(a.desde, hoy.date(), list_id=a.list_id,
                                    assignees=[x.id for x in miembros], team_id=team_id)
    req_proyecto = cu.request_count
    log_proyecto = dict(cu.request_log)
    # Contraprueba: sin assignee el endpoint devuelve solo las entradas del dueño del token.
    t0 = int(dt.datetime.combine(a.desde, dt.time(0), TZ).timestamp() * 1000)
    sin_assignee = cu.get(f"/team/{team_id}/time_entries",
                          {"start_date": t0, "end_date": int(hoy.timestamp() * 1000), "list_id": a.list_id})
    n_sin_assignee = len(sin_assignee.get("data", []))

    tm = a_tareas_metrica(tareas)
    horas = a_horas(entradas)
    padres = {t.id: t.parent for t in tm}
    nombres = {t.id: t.nombre for t in tm}

    # --- Metricas en vivo ---------------------------------------------------------------------
    fx_path = a.fixture or buscar_fixture(codigo)
    fx = fixture_excel.cargar(fx_path) if fx_path and fx_path.exists() else None
    if fx:
        grid = fx.grilla
    else:
        inicio = min((t.start for t in m.universo(tm) if t.start), default=C) - dt.timedelta(days=1)
        grid = m.grilla(inicio, fin, C)
    serie = m.serie_resumen(grid, tm, tm, horas, C, fin, cal)
    tot = m.total_hh(tm)
    ap_, ar_ = m.avance_programado(tm, C, cal), m.avance_real(tm)
    gast_c = m.hh_gastadas_a(C, horas, C)
    fases = m.agregado_por_fase(tm, horas, C, cal, padres, nombres)

    print(f"{codigo} | {lista.get('name')}")
    print(f"  TotalHH={tot:g}  avance programado={ap_:.6f}  avance real={ar_:.6f}  HH gastadas a C={gast_c:.2f}")
    print(f"  time entries: {len(entradas)} de {len({e.user_id for e in entradas})} personas; peticiones={req_proyecto}")

    L: list[str] = []
    L.append(f"# Validación {codigo}\n")
    L.append(f"{lista.get('name')}  \nList ID `{a.list_id}` · fecha de control **{C}** · fecha de término **{fin}** · "
             f"corrida {hoy:%Y-%m-%d %H:%M} (America/Santiago)\n")
    L.append("Solo lectura: ninguna escritura en ClickUp ni en Google Sheets.\n")

    L.append("## Métricas desde ClickUp (en vivo)\n")
    L.append(md_tabla(["Indicador", "Valor"], [
        ["TotalHH (tareas con HH Presupuestadas > 0)", f"{tot:g} ({len(m.universo(tm))} tareas)"],
        ["Avance programado a C", f"{ap_:.6f}"],
        ["Avance real", f"{ar_:.6f}"],
        ["HH gastadas a C (fecha < C)", f2(gast_c)],
        ["HH pendientes (1 − avance) × HH", f2(m.hh_pendientes_total(tm))],
        ["HH proyectadas al término", f2(next((p.proyectadas for p in reversed(serie) if p.proyectadas is not None), None))],
    ]))
    L.append("\n### Por fase\n")
    L.append(md_tabla(["Fase", "HH programadas", "HH programadas a C", "HH gastadas a C"],
                      [[f.fase, f2(f.hh_programadas), f2(f.hh_programadas_a_control), f2(f.hh_gastadas_a_control)]
                       for f in fases] +
                      [["**Total**", f2(sum(f.hh_programadas for f in fases)),
                        f2(sum(f.hh_programadas_a_control for f in fases)),
                        f2(sum(f.hh_gastadas_a_control for f in fases))]]))
    L.append("\n### Curva S" + (" (grilla de fechas del Excel)" if fx else "") + "\n")
    L.append(md_tabla(["Fecha", "HH programadas", "HH gastadas", "HH proyectadas"],
                      [[p.fecha, f2(p.programadas), f2(p.gastadas), f2(p.proyectadas)] for p in serie]))
    png = curva_s_png(serie, C, fin, f"Curva S {codigo} (ClickUp en vivo, control {C})",
                      SALIDA / f"{codigo}_curva_s.png", total_hh=tot, referencia=fx.serie if fx else None)
    L.append(f"\n![Curva S]({png.name})\n")
    L.append("En el gráfico, las cruces son los valores del Excel de referencia.\n")

    # --- 4a -----------------------------------------------------------------------------------
    if fx:
        ch = cmp.validar_4a(fx, cal)
        malos = [c for c in ch if not c.ok]
        L.append("## 4a. Lógica contra el Excel\n")
        L.append(f"Insumos leídos del Excel `{fx.ruta.name}` (fecha de control del Excel: {fx.control}; "
                 f"término `Avance!M2`: {fx.fin}). **{len(ch)} chequeos, {len(malos)} fallan.** "
                 "Incluye cada celda diaria por tarea de `Programado!P:DC` y `Avance!W:DJ`, las filas acumuladas 208 "
                 "y los valores por tarea de las columnas N y U.\n")
        principales = [c for c in ch if not c.nombre.startswith(("Programado ", "Avance ", "Programado!fila",
                                                                   "Avance!fila", "Programado!N "))]
        L.append(md_tabla(["Chequeo", "Excel", "Cálculo", "Tolerancia", "OK"],
                          [[c.nombre, f2(c.esperado, 6), f2(c.obtenido, 6), f"{c.tol:g}", "sí" if c.ok else "**NO**"]
                           for c in principales]))
        if malos:
            L.append("\n**Fallas:**\n")
            L += [f"- {c.nombre}: Excel {c.esperado}, cálculo {c.obtenido}" for c in malos]
        print(f"  4a: {len(ch)} chequeos, {len(malos)} fallan")
        L.append("""
Notas de traducción (comportamiento del Excel replicado a propósito):
- El Excel mezcla **dos exports**: el programa (fechas y HH) sale de la hoja `Programado` y el avance real y las fechas de la proyección salen de la hoja `Avance`. En `Programado` casi todos los avances están en 0 y la tarea "7.0 Esquemas de Informes" tiene otras fechas. Para calzar, 4a usa cada hoja para lo que el Excel la usa. Con ClickUp ambas son la misma lista.
- La base de la proyección es `VLOOKUP(C; D54:F75; 3)`: las HH gastadas en el **último punto de la grilla ≤ C** (aquí 17-09, horas con fecha < 17-09), no las gastadas a C. Si hubiera horas el 17 o 18-09 quedarían fuera de la proyección.
- La grilla de `Resumen!D` parte en `min(start) − 1` y avanza de a 3 o 2 días con fórmulas fijas por fila (las filas 66 y 71–74 suman 2). El sistema usará una grilla paramétrica (`metricas.grilla`, semanal más C y término).
- `Resumen!F68:F75` compara con `TODAY()` en vez de con la fecha de control (`F54:F67` usa `Programado!K2`). Con C = 19-09 no cambia valores; en el sistema se usa siempre C.
- La "fecha de término del proyecto" es `Avance!M2 = M13`, el due del hito "Entrega Nube de Puntos" (una referencia fija a una fila). Ver la respuesta 3 sobre la fuente correcta.
- Universo = toda tarea con HH > 0, sea padre u hoja (ver `calidad_datos.md` por el riesgo de doble conteo).
""")

    # --- 4b -----------------------------------------------------------------------------------
    if fx:
        export = fixture_excel.fecha_export(fx.ruta)
        res = cmp.comparar_tareas(fx, tm, cal)
        cmp.comparar_entradas(res, fx.entradas, entradas, export)
        L.append("## 4b. ClickUp en vivo contra el Excel\n")
        L.append(f"Momento de referencia del export: fecha de modificación del archivo ({export:%Y-%m-%d %H:%M}); "
                 f"`TODAY()−3` del Excel = {fx.control}, o sea el Excel se recalculó el {fx.control + dt.timedelta(days=3)}.\n")
        serie_ex_vivo = m.serie_resumen(fx.grilla, tm, tm, horas, fx.control, fx.fin, cal)
        L.append(md_tabla(["Indicador", "Excel", "ClickUp en vivo", "Diferencia"], [
            ["TotalHH", f"{fx.total_hh:g}", f"{tot:g}", f"{tot - fx.total_hh:+g}"],
            ["Avance programado", f"{fx.avance_programado:.6f}", f"{ap_:.6f}", f"{ap_ - fx.avance_programado:+.6f}"],
            ["Avance real", f"{fx.avance_real:.6f}", f"{ar_:.6f}", f"{ar_ - fx.avance_real:+.6f}"],
            ["Entradas de tiempo", len(fx.entradas), len(entradas), f"{len(entradas) - len(fx.entradas):+d}"],
            ["Horas registradas (todas)", f2(sum(e.horas for e in fx.entradas)), f2(sum(e.hours for e in entradas)),
             f2(sum(e.hours for e in entradas) - sum(e.horas for e in fx.entradas))],
        ]))
        L.append("\nSerie `Resumen!D55:G75` con datos en vivo:\n")
        L.append(md_tabla(["Fecha", "Prog. Excel", "Prog. vivo", "Gast. Excel", "Gast. vivo", "Proy. Excel", "Proy. vivo"],
                          [[a_.fecha, f2(b.programadas), f2(a_.programadas), f2(b.gastadas), f2(a_.gastadas),
                            f2(b.proyectadas), f2(a_.proyectadas)] for a_, b in zip(serie_ex_vivo, fx.serie)]))
        n_post = sum(d.clase == cmp.POSTERIOR for d in res.tareas + res.entradas)
        n_rev = sum(d.clase == cmp.REVISAR for d in res.tareas + res.entradas)
        L.append(f"\n**Diferencias de lógica: {res.n_logica}.** Cambios posteriores al export: {n_post}. "
                 f"Por revisar: {n_rev}. Tareas con insumo idéntico cuyo resultado por tarea se verificó contra las "
                 f"celdas del Excel: {res.tareas_logica_verificadas} (hoja × tarea). "
                 f"Entradas de tiempo idénticas: {res.entradas_coinciden}.\n")
        L.append("### Diferencias por tarea\n")
        por_hoja = {h: sum(d.hoja == h for d in res.tareas) for h in ("Programado", "Avance")}
        L.append(f"Contra la hoja `Programado`: {por_hoja['Programado']} diferencias; contra la hoja `Avance`: "
                 f"{por_hoja['Avance']}. " + ("ClickUp hoy coincide con el export de la hoja `Avance`; la hoja "
                 "`Programado` es un export anterior (fechas vacías en tareas sin HH y la tarea \"7.0 Esquemas de "
                 "Informes\" movida una semana), lo que explica las diferencias de HH programadas entre 31-08 y 09-09.\n"
                 if por_hoja["Avance"] == 0 and por_hoja["Programado"] else "\n"))
        L.append(md_tabla(["Tarea", "ID", "Hoja Excel", "Campo", "Excel", "ClickUp", "Clasificación"],
                          [[d.tarea, d.tarea_id, d.hoja, d.campo, d.excel, d.clickup, d.clase] for d in res.tareas])
                 if res.tareas else "Sin diferencias.")
        L.append("\n### Diferencias por entrada de tiempo\n")
        L.append("Cruce por (usuario, start en ms): el Time Entry ID del Excel se guardó como número y perdió precisión.\n")
        L.append(md_tabla(["Tipo", "User ID", "Tarea", "Fecha", "Horas", "Detalle", "Clasificación"],
                          [[d.tipo, d.user_id, d.tarea, d.fecha, f2(d.horas), d.detalle, d.clase] for d in res.entradas])
                 if res.entradas else "Sin diferencias.")
        print(f"  4b: diferencias de logica={res.n_logica}, posteriores={n_post}, revisar={n_rev}")

    # --- Calidad del proyecto -----------------------------------------------------------------
    hpt = horas_por_tarea(horas, padres, acumular_en_ancestros=True)
    est = {t.id: t.time_estimate_h for t in tareas}
    adv = calidad.detectar(tm, hpt, est)
    L.append("\n## Detector de problemas de datos (este proyecto)\n")
    L.append(md_tabla(["Severidad", "Tipo", "Tarea", "Detalle"],
                      [[x.severidad, x.tipo, x.tarea, x.detalle] for x in sorted(adv, key=lambda x: (x.tipo, x.tarea))])
             if adv else "Sin advertencias.")

    # --- Respuestas ---------------------------------------------------------------------------
    personas = {e.user_id for e in entradas}
    avance_def = next((d for d in defs if d.name == CAMPO_AVANCE), None)
    ejemplos = sorted({str(t.custom_fields[CAMPO_AVANCE].raw) for t in tareas if CAMPO_AVANCE in t.custom_fields})
    ubic = ubicacion_campos(defs, tareas, list(CAMPOS_INTERES))
    asignado = lista.get("assignee") or {}
    L.append("\n## Respuestas\n")
    L.append(f"""**1. Time entries de todos los miembros.** Consulta `GET /team/{team_id}/time_entries` con `assignee` = los {len(miembros)} miembros del workspace y `list_id={a.list_id}`, rango {a.desde} → {hoy.date()}: **{len(entradas)} entradas de {len(personas)} personas** ({f2(sum(e.hours for e in entradas))} h). La misma consulta sin `assignee` devuelve {n_sin_assignee} entradas (solo las del dueño del token), lo que confirma que el parámetro es necesario y que el token tiene permiso para leer las de todos. No hubo error de la API.

**2. Escala de "Avance Real".** Tipo `{avance_def.type if avance_def else '?'}`, `type_config = {avance_def.type_config if avance_def else '?'}`. La API entrega un objeto; valores observados: {', '.join(f'`{x}`' for x in ejemplos)}. Es decir, `current` va en **0–100** (como texto o número) y `percent_completed` ya es **fracción 0–1**. El export a Excel lo muestra como 0–1 (hojas `Programado`/`Avance`) y como 0–100 (hoja `Horas Cargadas`, columna AR). `dep_clickup.fields.progress_fraction` convierte a fracción con `(current − start)/(end − start)`.

**3. Custom fields de fechas y JP.** Campos de la lista (nombres exactos) y en qué nivel tienen valor:

""")
    L.append(md_tabla(["Campo buscado", "Tipo y ubicación"], [[u.nombre, fmt_ubicacion(u)] for u in ubic]))
    L.append(f"""
Datos propios de la lista (no son custom fields): responsable (`assignee`) = **{asignado.get('username') or '(vacío)'}**, `start_date` = {ms_to_local(lista.get('start_date')).date() if lista.get('start_date') else '(vacío)'}, `due_date` = {ms_to_local(lista.get('due_date')).date() if lista.get('due_date') else '(vacío)'}. Los datos del proyecto (Cliente, PJ_CODE, PR_CODE, URLs) viven en la tarea "00 Administración". **"JP Responsable" no existe como custom field en esta lista** (en otras 4 listas del folder existe, tipo `users`, pero sin valores): el candidato es el responsable de la lista. La fecha de término del Excel (`Avance!M2`) es el due del hito "Entrega Nube de Puntos" (2026-10-02); "Fecha Entrega Contractual" existe pero no tiene valor en ninguna tarea de este proyecto, así que hoy no sirve como fuente; el `due_date` de la lista es el mejor candidato. Resumen del folder completo en `calidad_datos.md`.

**4. Peticiones a la API.** Este proyecto: **{req_proyecto} peticiones** ({', '.join(f'{k}: {v}' for k, v in sorted(log_proyecto.items()))}; sin contar la contraprueba sin assignee). Las tareas se paginan de a 100, así que un proyecto con ≤100 tareas cuesta 1 petición de tareas + 1 de campos + 1 de lista; `/team` y las time entries (filtradas por folder o space) se piden una vez por corrida y no por proyecto. El total del Space está en `calidad_datos.md`.
""")
    SALIDA.mkdir(parents=True, exist_ok=True)
    out = SALIDA / f"{codigo}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"  informe: {out.relative_to(ROOT)}\n  grafico: {png.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
