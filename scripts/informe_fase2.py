"""Corre el dry-run de un corte y genera reportes/fase2/informe_dry_run.md. No escribe en Sheets ni en ClickUp.

Uso:
    python scripts/informe_fase2.py --corte 2026-09-20
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dep_reportes import calidad, esquema as E, linea_base as LB, proyecto as P  # noqa: E402
from dep_reportes.calendario import calendario_chile  # noqa: E402
from dep_reportes.config_reportes import DRY_RUN_DIR, IMPORTADAS  # noqa: E402
from dep_reportes.modos import DIAS_NO_HABILES_CSV, LEGADO, modo_dep  # noqa: E402
from dep_reportes.run import SIN_JP, ejecutar, fecha_corte  # noqa: E402

SALIDA = ROOT / "reportes" / "fase2" / "informe_dry_run.md"
ID_0152 = "901328186343"


def tabla(cab, filas) -> str:
    out = ["| " + " | ".join(cab) + " |", "|" + "|".join("---" for _ in cab) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in f) + " |" for f in filas]
    return "\n".join(out)


def n(x, nd=2) -> str:
    if x is None:
        return "—"
    return f"{x:,.{nd}f}".replace(",", " ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corte", default="2026-09-20")
    a = ap.parse_args()
    corte = fecha_corte(a.corte, dt.date.today())
    c = ejecutar(corte, dry_run=True)
    L: list[str] = [f"# Reportes DEP fase 2 — informe del dry-run del corte {corte}\n",
                    f"Generado {dt.datetime.now():%Y-%m-%d %H:%M}. Modo de cálculo `{c.modo.nombre}`. "
                    f"Nada se escribió en Google Sheets ni en ClickUp. CSV en `reportes/dry_run/{corte}/`.\n",
                    "Es la **primera corrida** (la hoja no tiene ejecuciones de escritura), así que aplica la decisión 6.\n"
                    if c.primera_corrida else ""]

    # 1. Proyectos
    L.append("## 1. Proyectos, JP y línea base\n")
    filas = []
    for r in c.listas:
        lb = r.lb_filas
        if lb:
            estado = f"Rev. 0 **{lb[0].tipo}** (se crearía)" if r.lb_nuevas else f"vigente Rev. {lb[0].rev}"
        elif r.decision.en_planificacion:
            estado = "en planificación (1.2 abierta)"
        else:
            tipos = {x["tipo"] for x in r.advertencias}
            motivo = ("1.2 en No Aplica" if P.ADV_TAREA_12_NO_APLICA in tipos else
                      "sin HH presupuestadas" if P.ADV_LB_SIN_HH in tipos else
                      "sin tarea 1.2" if P.ADV_SIN_TAREA_12 in tipos else "—")
            estado = f"sin línea base ({motivo})"
        m = r.resultado.metricas
        filas.append([r.codigo, r.lista.name.split("|")[1].strip() if "|" in r.lista.name else r.lista.name,
                      r.jp.username if r.jp else f"**{SIN_JP}**", r.jp.email if r.jp else "",
                      r.lista.status or "", LB.inicio_proyecto(r.lista, r.tareas) or "—",
                      r.lista.due.date() if r.lista.due else "—", estado, len(lb),
                      n(m["total_hh"], 0), n(m["hh_actuales_clickup"], 0)])
    L.append(tabla(["Código", "Nombre", "JP", "Correo JP", "Estado lista", "Inicio", "Término vigente",
                    "Línea base", "Tareas LB", "TotalHH LB", "HH actuales"], filas))
    sin_jp = [r.codigo for r in c.listas if r.jp is None]
    plan = [r.codigo for r in c.listas if r.decision.en_planificacion]
    na12 = [r.codigo for r in c.listas if any(x["tipo"] == P.ADV_TAREA_12_NO_APLICA for x in r.advertencias)]
    sinhh = [r.codigo for r in c.listas if any(x["tipo"] == P.ADV_LB_SIN_HH for x in r.advertencias)]
    duplicados = [k for k, v in Counter(r.codigo for r in c.listas).items() if v > 1]
    L.append(f"""
**JP:** responsable de la lista; el correo sale de los miembros del workspace (el listado de listas del folder trae el nombre de usuario pero no el ID).

## 2. Proyectos "Sin JP" y en planificación

- **Sin JP:** {', '.join(sin_jp) if sin_jp else 'ninguno (todas las listas tienen responsable)'}.
- **En planificación** (tarea 1.2 abierta; sin línea base ni curva programada): {', '.join(plan) or 'ninguno'}.
- **Tarea 1.2 en "No Aplica"** (decisión 5: advertencia y no se congela): {', '.join(na12) or 'ninguno'}. **Requiere decisión**: hoy quedan sin curva programada indefinidamente. Opciones: congelar una Rev. 0 manual con `python -m dep_reportes.linea_base revisar --list-id … --motivo "…"` (si no hay Rev. 0, crea la Rev. 0 con tipo `revision`) o tratar "No Aplica" como cerrada en la primera corrida (Rev. 0 `tardia`).
- **Correspondía Rev. 0 pero no hay tareas con HH Presupuestadas:** {', '.join(sinhh) or 'ninguno'}. Una Rev. 0 sin tareas no se puede registrar (la pestaña `linea_base` guarda filas por tarea); se reintenta cada corte hasta que tengan HH.
""" + (f"- **Códigos repetidos:** {', '.join(duplicados)} aparece en más de una lista (se distinguen por `list_id`).\n" if duplicados else ""))

    # 3. 0152: legado vs dep
    r152 = next((r for r in c.listas if r.lista.id == ID_0152), None)
    if r152:
        imp = IMPORTADAS[ID_0152]
        lb_todo = LB.importar_excel(r152.lista, r152.tareas, imp.ruta, imp.fecha_entrega_contractual,
                                    dt.datetime.now(), excluir_no_aplica=False)
        lb_t, fase_lb = LB.a_tareas(lb_todo)
        lb_dep, fase_dep = LB.a_tareas(r152.lb_filas)
        chile = calendario_chile(extra_csv=DIAS_NO_HABILES_CSV)
        fin = r152.lista.due.date()
        variantes = [
            ("legado", LEGADO, lb_t, fase_lb),
            ("+ feriados", LEGADO.con(cal=chile), lb_t, fase_lb),
            ("+ proyección desde C", LEGADO.con(cal=chile, base_en_control=True), lb_t, fase_lb),
            ("+ vencido", LEGADO.con(cal=chile, base_en_control=True, vencido_primer_habil=True), lb_t, fase_lb),
            ("dep (+ No Aplica)", modo_dep(), lb_dep, fase_dep),
        ]
        res = [(nom, P.calcular(lb, r152.tm, r152.horas, corte, fin, md, fl)) for nom, md, lb, fl in variantes]
        claves = [("total_hh", 2), ("hh_prog_acum", 2), ("hh_gastadas_acum", 2), ("avance_prog", 6),
                  ("avance_real", 6), ("ev", 2), ("spi", 4), ("cpi", 4), ("hh_estimadas_al_termino", 2),
                  ("hh_actuales_clickup", 2)]
        L.append(f"## 3. PJ-2026.0152: modo `legado` y modo `dep`\n")
        L.append(f"Corte {corte} (domingo), término vigente {fin} (vencimiento de la lista), línea base = Rev. 0 "
                 f"importada de la hoja `Programado` del Excel ({len(r152.lb_filas)} tareas). Avance, horas y "
                 "proyección: ClickUp hoy. Cada columna agrega un cambio a la anterior; la última es el modo `dep`.\n")
        L.append(tabla(["Métrica"] + [nom for nom, _ in res],
                       [[k] + [n(x.metricas[k], nd) for _, x in res] for k, nd in claves]))
        leg, fer, proy, venc, dep = (x.metricas for _, x in res)
        na_152 = [x for x in r152.advertencias if x["tipo"] in (P.ADV_NO_APLICA_CON_HH, P.ADV_LB_TAREA_NO_APLICA)]
        feriados_en = sorted(d for d in chile.feriados if min(t.start for t in lb_t) <= d <= max(t.due for t in lb_t)
                             and d.weekday() < 5)
        L.append(f"""
**Qué cambia y por qué**

- **Feriados** ({', '.join(str(d) for d in feriados_en)} caen en días hábiles dentro del programa): las HH de las tareas que cruzan esos días se reparten en menos días. HH programadas a C: {n(leg['hh_prog_acum'])} → {n(fer['hh_prog_acum'])} ({n(fer['hh_prog_acum'] - leg['hh_prog_acum'])}); avance programado {n(leg['avance_prog'], 6)} → {n(fer['avance_prog'], 6)}. El avance real no cambia (no depende del calendario).
- **Proyección desde las HH gastadas a C (inclusive)** en vez del último punto de una grilla cada 3 días: gastadas {n(fer['hh_gastadas_acum'])} → {n(proy['hh_gastadas_acum'])}; estimadas al término {n(fer['hh_estimadas_al_termino'])} → {n(proy['hh_estimadas_al_termino'])}. En este proyecto no hay horas entre el último punto de la grilla y el domingo 20, así que la diferencia es {n(proy['hh_estimadas_al_termino'] - fer['hh_estimadas_al_termino'])}. Con horas en esos días, el Excel las perdía de la proyección.
- **Proyecto vencido:** el término ({fin}) es posterior al corte, no aplica ({n(venc['hh_estimadas_al_termino'] - proy['hh_estimadas_al_termino'])}).
- **Tareas "No Aplica":** {('hay ' + str(len(na_152)) + ' advertencias: ' + '; '.join(x['detalle'] for x in na_152)) if na_152 else 'ninguna tarea en No Aplica tiene HH en 0152, así que **no cambia nada**'} (diferencia en TotalHH {n(dep['total_hh'] - venc['total_hh'])}, en avance real {n(dep['avance_real'] - venc['avance_real'], 6)}).
- **Serie diaria:** la curva ya no se muestrea cada 3 días; no cambia las métricas.
- **Estimadas al término** = gastadas a C + todas las HH pendientes, incluidas las 10 HH de "10.2 Levantamiento de Observaciones" (13–16 oct), posteriores al término del 2 oct. La curva del Excel se cortaba en el término y las omitía (386,25 vs 396,25 en la foto del Excel).
- Comparado con el Excel (C = 19-09, sábado): avance programado 0,747107 y real 0,732231. El corte del domingo 20 no agrega días hábiles, así que en `legado` el avance programado es el mismo; el avance real es el mismo porque no cambió en ClickUp.
""")

    # 4. Advertencias
    L.append("## 4. Advertencias\n")
    todas = [x for r in c.listas for x in r.advertencias]
    cnt = Counter(x["tipo"] for x in todas)
    L.append(f"Total: **{len(todas)}**.\n")
    L.append(tabla(["Tipo", "Cantidad", "Origen"],
                   [[t, v, "detector fase 1" if t in calidad.SEVERIDAD else "fase 2"] for t, v in cnt.most_common()]))
    tipos = [t for t, _ in cnt.most_common()]
    por = {r.codigo + ("" if Counter(x.codigo for x in c.listas)[r.codigo] == 1 else f" ({r.lista.id})"):
           Counter(x["tipo"] for x in r.advertencias) for r in c.listas}
    L.append("\nPor proyecto:\n")
    L.append(tabla(["Proyecto"] + tipos + ["Total"],
                   [[p] + [v.get(t, "") for t in tipos] + [sum(v.values())] for p, v in por.items()]))
    universo = {(r.lista.id, t.id) for r in c.listas for t in r.tm if t.hh}
    ash = [x for x in todas if x["tipo"] == calidad.AVANCE_SIN_HORAS]
    ash_hh = sum((x["list_id"], x["task_id"]) in universo for x in ash)
    L.append(f"""
**Ruido:** {len(ash)} de las {len(todas)} advertencias son `avance_sin_horas` y solo {ash_hh} de ellas son de tareas con HH Presupuestadas; el resto son hitos, tareas administrativas o tareas cuyo trabajo se registró en otra tarea. Como la hoja la verán todos los JP, propongo dejar en la hoja solo las advertencias sobre tareas con HH (o las de severidad error/aviso) y mantener el detalle completo en `calidad_datos.md`. Por ahora se escriben todas, como pide la tarea.
""")

    # 5. Peticiones y duracion
    pc = c.peticiones_clickup
    ps = c.plan_sheets
    filas_n = {t: len(f) for t, f in c.nuevas.items()}
    L.append("## 5. Peticiones y duración de la corrida real\n")
    L.append(f"""- **ClickUp:** {sum(pc.values())} peticiones medidas en este dry-run ({', '.join(f'{k}: {v}' for k, v in sorted(pc.items()))}); {c.segundos_clickup:.0f} s. La corrida real hace exactamente las mismas lecturas. {c.n_entradas} entradas de tiempo en una sola petición (folder completo, todos los miembros).
- **Sheets, lectura:** 1 de metadata + 1 `values.batchGet` con todas las pestañas (en este dry-run fue solo la de metadata porque las pestañas aún no existen).
- **Sheets, escritura (corrida real):** {ps.get('peticiones')} peticiones — {ps.get('detalle')}. Pestañas que se crearían: {', '.join(ps.get('pestañas_nuevas', [])) or 'ninguna'}. Unas {ps.get('celdas_escritas', 0):,} celdas. Muy por debajo de la cuota (~60 escrituras/min).
- **Duración estimada:** ~{math.ceil(c.segundos_clickup + 10)} s (ClickUp ~{c.segundos_clickup:.0f} s + Sheets ~5–10 s).
- **Filas por pestaña en este corte:** {', '.join(f'{t}: {v}' for t, v in filas_n.items())}.
- **Crecimiento:** `fotos_tareas` suma ~{filas_n['fotos_tareas']} filas × {len(E.TABLAS['fotos_tareas'])} columnas por semana (~{filas_n['fotos_tareas'] * 52 * len(E.TABLAS['fotos_tareas']) / 1e6:.1f} M celdas/año, de 10 M que admite un archivo). Convendrá archivar o resumir los cortes antiguos en ~3–4 años, o antes si el folder crece.
""")

    # 6. Tipos
    L.append(f"""## 6. Números y fechas en Sheets

- La hoja **"DEP - Reportes"** tiene configuración regional **`en_US`** (punto decimal) y zona horaria **America/Santiago** (leído por la API). No hace falta cambiarla.
- Se escribe con `valueInputOption=RAW`: los números viajan como números JSON (sin texto con coma) y los textos nunca se interpretan (un nombre de tarea que empiece con `=` no se vuelve fórmula).
- Fechas como **número de serie** (días desde 1899-12-30) y formato de columna `DATE` `yyyy-mm-dd` (`DATE_TIME` para `actualizado_en`, `fecha_captura` y `ejecutado_en`), aplicado a toda la columna desde la fila 2 en el mismo `batchUpdate` que crea las pestañas. Looker Studio las lee como fecha.
- Después de escribir, `AlmacenSheets.verificar_tipos` lee la fila 2 de cada pestaña (`effectiveValue` y `effectiveFormat`) y confirma que cada número es `numberValue` y cada fecha es `numberValue` con formato `DATE`/`DATE_TIME`. Si algo falla, la corrida termina con error y queda registrada en `ejecuciones`. **Esta verificación solo puede correr con la primera escritura real**; en el dry-run no se escribió nada.
- `list_id` y `task_id` se guardan como texto (claves de unión en Looker).

## 7. Otros puntos para revisar

- **Pestañas existentes:** el archivo ya tiene dos pestañas vacías, `dep_reportes_datos` y `dep_gestion_datos`. La corrida real **agrega** las 8 pestañas del esquema y no toca esas dos. ¿Se borran, o `dep_gestion_datos` queda para la fase 5?
- **"Estado de tipo cerrado":** se interpreta como los grupos `done` y `closed` de ClickUp ("completado" es `done`; "facturado" es `closed`), excepto "No Aplica", que también es `done`.
- **Tipo `normal` vs `tardia`:** `normal` si la lista ya aparecía en un corte anterior (fotos_tareas) cuando la 1.2 se cerró; `tardia` si al observarla por primera vez la 1.2 ya estaba cerrada. En la primera corrida, sin tarea 1.2 → `tardia`; después, sin 1.2 → solo advertencia.
- **Avance real** se pondera por las HH actuales de ClickUp (Σ avance × HH actual / Σ HH actual) y `ev = avance_real × TotalHH` de la línea base. Si las HH cambian respecto de la línea base se emite la advertencia `hh_cambiaron_vs_linea_base`.
- **Respaldo:** antes de cada escritura real, el contenido previo de la hoja se guarda en `reportes/respaldos/<fecha>/`.
- **Datos por persona:** ninguna pestaña tiene columnas de persona; las horas se agregan por tarea, fase y día. El único dato personal es el nombre y correo del JP (test `test_sin_datos_por_persona_en_el_esquema`).
""")
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text("\n".join(L), encoding="utf-8")
    print(f"Informe: {SALIDA.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
