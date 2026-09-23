"""Proceso semanal de reportes DEP: lee ClickUp, congela lineas base, calcula metricas y escribe la hoja.

Uso:
    python -m dep_reportes.run --corte 2026-09-20 --dry-run
    python -m dep_reportes.run --corte 2026-09-20
    python -m dep_reportes.run --corte 2026-09-20 --solo <list_id>

El corte es un domingo (fecha de control C, inclusive). Sin --corte se usa el ultimo domingo.
Cero escrituras en ClickUp. En Sheets no se escriben datos por persona: solo agregados por proyecto,
fase, tarea y dia, y el nombre y correo del JP.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from dep_clickup import ClickUpClient
from dep_clickup.config import TZ
from dep_clickup.models import ListInfo, Member, Task
from dep_clickup.naming import list_code

from . import calidad, codigos as COD, controles as CTL, esquema as E, linea_base as LB, proyecto as P
from .adaptador_clickup import a_horas, a_tareas_metrica, horas_por_tarea
from .almacen import AlmacenCsv, AlmacenSheets, celda_csv, completar, duplicados, filas_lb_desde_tabla, fusionar
from .config_reportes import (DRY_RUN_DIR, FOLDER_PJ_INGENIERIA, IMPORTADAS, RESPALDOS_DIR,
                              RETENCION_PRELIMINAR_DIAS, SHEETS_REPORTES_ID, TIME_ENTRIES_DESDE)
from .metricas import Horas, TareaMetrica
from .modos import Modo, por_nombre

log = logging.getLogger("dep_reportes.run")
SIN_JP = "Sin JP"


def ultimo_domingo(hoy: dt.date) -> dt.date:
    return hoy - dt.timedelta(days=(hoy.weekday() + 1) % 7)


def fecha_corte(txt: str | None, hoy: dt.date, tipo_corte: str = E.OFICIAL) -> dt.date:
    """Oficial: un domingo (por defecto el ultimo). Preliminar: cualquier dia (por defecto ayer)."""
    if txt is None:
        return ultimo_domingo(hoy) if tipo_corte == E.OFICIAL else hoy - dt.timedelta(days=1)
    d = dt.date.fromisoformat(txt)
    if tipo_corte == E.OFICIAL and d.weekday() != 6:
        raise SystemExit(f"--corte {d} no es domingo ({d:%A}): un corte oficial debe ser domingo")
    return d


class ControlFallido(RuntimeError):
    """Algun control de cordura fallo: no se escribio nada (salvo la fila de ejecuciones)."""


def buscar_jp(lista: ListInfo, miembros: list[Member]) -> Member | None:
    if lista.assignee_id is not None:
        return next((x for x in miembros if x.id == lista.assignee_id), None)
    if lista.assignee_username:
        cand = [x for x in miembros if x.username == lista.assignee_username]
        return cand[0] if len(cand) == 1 else None
    return None


@dataclass
class ResultadoLista:
    lista: ListInfo
    codigo: str
    jp: Member | None
    tareas: list[Task]
    tm: list[TareaMetrica]
    horas: list[Horas]
    decision: LB.Decision
    lb_filas: list[LB.FilaLB]          # revision vigente (existente o recien creada)
    lb_nuevas: list[LB.FilaLB]
    resultado: P.ResultadoProyecto
    advertencias: list[dict]           # las que van a la hoja
    advertencias_todas: list[dict]     # incluye las del detector sobre tareas sin HH


@dataclass
class Corrida:
    corte: dt.date
    modo: Modo
    dry_run: bool
    listas: list[ResultadoLista] = field(default_factory=list)
    nuevas: dict[str, list[dict]] = field(default_factory=dict)
    finales: dict[str, list[dict]] = field(default_factory=dict)
    lb_nuevas: list[dict] = field(default_factory=list)
    primera_corrida: bool = True
    peticiones_clickup: dict = field(default_factory=dict)
    peticiones_sheets: dict = field(default_factory=dict)
    plan_sheets: dict = field(default_factory=dict)
    segundos_clickup: float = 0.0
    n_entradas: int = 0
    respaldo: object = None
    tipo_corte: str = E.OFICIAL
    fallos: list = field(default_factory=list)
    filas_antes: dict = field(default_factory=dict)
    tipos: dict = field(default_factory=dict)
    verificacion: dict = field(default_factory=dict)


def procesar_lista(lista: ListInfo, tareas: list[Task], entradas_lista, miembros: list[Member], corte: dt.date,
                   modo: Modo, lb_exist: list[LB.FilaLB], observada_antes: bool, primera_corrida: bool,
                   ahora: dt.datetime, codigo: str | None = None,
                   comparten_codigo: Sequence[ListInfo] = ()) -> ResultadoLista:
    codigo = codigo or list_code(lista.name) or lista.id
    tm = a_tareas_metrica(tareas)
    horas = a_horas(entradas_lista)
    jp = buscar_jp(lista, miembros)
    avisos: list[P.Aviso] = []
    if comparten_codigo:
        otras = "; ".join(f"{o.id} ({o.name.split('|')[1].strip() if '|' in o.name else o.name})"
                          for o in comparten_codigo)
        avisos.append(P.Aviso(P.ADV_CODIGO_DUPLICADO, "", f"El código {list_code(lista.name)} está también en: "
                                                          f"{otras}. En los reportes esta lista es {codigo}"))
    if jp is None:
        det = "La lista no tiene responsable" if not (lista.assignee_id or lista.assignee_username) else \
            f"Responsable \"{lista.assignee_username}\" no se encontró entre los miembros"
        avisos.append(P.Aviso(P.ADV_SIN_JP, "", det))

    dec = LB.decidir(lista.id, tareas, lb_exist, observada_antes, primera_corrida, tuple(IMPORTADAS))
    avisos += dec.avisos
    nuevas: list[LB.FilaLB] = []
    if dec.accion == "congelar":
        nuevas = LB.congelar(lista, tareas, 0, dec.tipo, f"Rev. 0 automática ({dec.tipo})", ahora,
                             excluir_no_aplica=modo.excluir_no_aplica)
    elif dec.accion == "importar":
        imp = IMPORTADAS[lista.id]
        nuevas = LB.importar_excel(lista, tareas, imp.ruta, imp.fecha_entrega_contractual, ahora,
                                   excluir_no_aplica=modo.excluir_no_aplica)
    if dec.accion != "ninguna" and not nuevas:
        avisos.append(P.Aviso(P.ADV_LB_SIN_HH, "", f"Correspondía Rev. 0 ({dec.tipo}) pero no hay tareas con HH "
                                                   "Presupuestadas: se reintenta en el próximo corte"))
    vig = LB.vigente(lb_exist, lista.id)
    lb_filas = vig[1] if vig else nuevas
    if lb_filas and lb_filas[0].rev == 0 and lb_filas[0].tipo == "tardia":
        # Estable entre corridas del mismo corte: depende solo de la linea base guardada.
        avisos.append(P.Aviso(P.ADV_LB_TARDIA, "", f"Rev. 0 tardía: congelada el {lb_filas[0].fecha_captura:%Y-%m-%d} "
                                                   "con la foto de ese día (la 1.2 ya estaba cerrada o no existía)"))
    if dec.en_planificacion:
        avisos.append(P.Aviso(P.ADV_EN_PLANIFICACION, "", "Tarea 1.2 abierta: proyecto en planificación, sin línea base"))
    lb_tareas, fase_lb = LB.a_tareas(lb_filas) if lb_filas else (None, {})

    fin = lista.due.date() if lista.due else None
    res = P.calcular(lb_tareas, tm, horas, corte, fin, modo, fase_lb)
    avisos += res.avisos

    padres = {t.id: t.parent for t in tm}
    hpt = horas_por_tarea([h for h in horas if h.fecha <= corte], padres, acumular_en_ancestros=True)
    detector = calidad.detectar(tm, hpt, {t.id: t.time_estimate_h for t in tareas})
    adv = [{"corte": corte, "list_id": lista.id, "tipo": a.tipo, "task_id": a.task_id or "", "detalle": a.detalle}
           for a in avisos]
    adv += [{"corte": corte, "list_id": lista.id, "tipo": a.tipo, "task_id": a.tarea_id,
             "detalle": f"{a.tarea}: {a.detalle}"} for a in detector]
    con_hh = {t.id for t in tm if t.hh} | {f.task_id for f in lb_filas}
    return ResultadoLista(lista, codigo, jp, tareas, tm, horas, dec, lb_filas, nuevas, res,
                          P.para_hoja(adv, con_hh), adv)


def identificacion(r: ResultadoLista) -> dict:
    return {"codigo": r.codigo, "jp_nombre": r.jp.username if r.jp else SIN_JP, "jp_email": r.jp.email if r.jp else ""}


def filas_de(r: ResultadoLista, corte: dt.date, modo: Modo, ahora: dt.datetime,
             tipo_corte: str = E.OFICIAL) -> dict[str, list[dict]]:
    lid = r.lista.id
    rev = r.lb_filas[0].rev if r.lb_filas else None
    mt = r.resultado.metricas
    idn = identificacion(r)
    out: dict[str, list[dict]] = defaultdict(list)
    out["proyectos"].append({
        "list_id": lid, "nombre": r.lista.name, **idn,
        "estado_lista": r.lista.status or "",
        "fecha_inicio": LB.inicio_proyecto(r.lista, r.tareas),
        "fecha_termino_vigente": r.lista.due.date() if r.lista.due else None,
        "estado_linea_base": "vigente" if r.lb_filas else "sin_linea_base",
        "rev_vigente": rev, "actualizado_en": ahora,
    })
    tc = {"corte": corte, "tipo_corte": tipo_corte}
    out["metricas_semanales"].append({**tc, "list_id": lid, **idn, "rev_linea_base": rev,
                                      "modo_calculo": modo.nombre,
                                      **{c: mt.get(c) for c, _ in E.METRICAS}, "n_advertencias": len(r.advertencias)})
    out["metricas_fase"] += [{**tc, "list_id": lid, **idn, **f} for f in r.resultado.fases]
    fases = P.fases_por_tarea(r.tm)
    propias: dict[str, float] = defaultdict(float)
    for h in r.horas:
        if h.fecha <= corte:
            propias[h.tarea_id] += h.horas
    fotos = tipo_corte == E.OFICIAL          # historial semanal: solo corridas oficiales
    out["fotos_tareas"] += [] if not fotos else [{"corte": corte, "list_id": lid, "task_id": t.id, "parent_id": t.parent or "",
                             "task_nombre": t.nombre, "fase": fases[t.id], "estado": t.estado or "", "hh": t.hh,
                             "start": t.start, "due": t.due, "avance_real": t.avance,
                             "hh_gastadas_acum": round(propias.get(t.id, 0.0), 6)} for t in r.tm]
    out["serie_diaria"] += [{**tc, "list_id": lid, **idn, "fecha": p.fecha,
                             "hh_prog_acum": p.programadas if r.lb_filas else None,
                             "hh_gastadas_acum": p.gastadas, "hh_proyectadas_acum": p.proyectadas}
                            for p in r.resultado.serie]
    out["advertencias"] += [{**a, **tc, **idn} for a in r.advertencias]
    out["linea_base"] += [f.fila() for f in r.lb_nuevas]
    return out


def ejecutar(corte: dt.date, dry_run: bool = True, solo: str | None = None, modo: Modo | None = None,
             sheets: AlmacenSheets | None = None, cu: ClickUpClient | None = None,
             eliminar_pestañas: tuple[str, ...] = (), tipo_corte: str = E.OFICIAL,
             umbrales: CTL.Umbrales | None = None) -> Corrida:
    modo = modo or por_nombre("dep")
    ahora = dt.datetime.now(TZ).replace(microsecond=0)
    corrida = Corrida(corte, modo, dry_run)
    corrida.tipo_corte = tipo_corte
    sheets = sheets or AlmacenSheets(SHEETS_REPORTES_ID)
    existentes = sheets.leer(E.TABLAS)                      # lectura, tambien en dry-run
    lb_exist = filas_lb_desde_tabla(existentes.get("linea_base", []))
    # Solo cuentan escrituras de cortes anteriores: repetir un corte debe dar el mismo resultado (idempotencia).
    corrida.primera_corrida = not any(e.get("modo") == "escritura" and e.get("resultado") == "ok"
                                      and e.get("corte") and e["corte"] < corte
                                      for e in existentes.get("ejecuciones", []))
    observadas = {f["list_id"] for f in existentes.get("fotos_tareas", []) if f.get("corte") and f["corte"] < corte}

    t0 = time.monotonic()
    cu = cu or ClickUpClient()
    team_id = cu.get_team_id()
    miembros = cu.list_members(team_id)
    listas = cu.list_lists(FOLDER_PJ_INGENIERIA)
    # Codigos unicos y estables: se asignan con todas las listas del folder (tambien con --solo).
    previos = {f["list_id"]: f["codigo"] for f in existentes.get("proyectos", []) if f.get("codigo")}
    asig = COD.asignar([(l.id, l.name) for l in listas], previos)
    comparten = {lid: [o for o in listas if o.id in ids and o.id != lid]
                 for ids in asig.duplicados.values() for lid in ids}
    if solo:
        listas = [l for l in listas if l.id == solo]
        if not listas:
            raise SystemExit(f"La lista {solo} no está en el folder {FOLDER_PJ_INGENIERIA}")
    entradas = cu.list_time_entries(TIME_ENTRIES_DESDE, corte, folder_id=FOLDER_PJ_INGENIERIA,
                                    assignees=[x.id for x in miembros], team_id=team_id)
    corrida.n_entradas = len(entradas)
    por_lista = defaultdict(list)
    for e in entradas:
        por_lista[e.list_id].append(e)
    for lista in sorted(listas, key=lambda l: l.name):
        tareas = cu.list_tasks(lista.id)
        corrida.listas.append(procesar_lista(lista, tareas, por_lista.get(lista.id, []), miembros, corte, modo,
                                             lb_exist, lista.id in observadas, corrida.primera_corrida, ahora,
                                             asig.codigos[lista.id], comparten.get(lista.id, ())))
    corrida.segundos_clickup = time.monotonic() - t0
    corrida.peticiones_clickup = dict(cu.request_log)

    nuevas: dict[str, list[dict]] = {t: [] for t in E.TABLAS}
    for r in corrida.listas:
        for t, filas in filas_de(r, corte, modo, ahora, tipo_corte).items():
            nuevas[t] += filas
    n_lb = len({(f["list_id"], f["rev"]) for f in nuevas["linea_base"]})
    nuevas["ejecuciones"] = [{"ejecutado_en": ahora, "corte": corte, "tipo_corte": tipo_corte,
                              "modo": "dry_run" if dry_run else "escritura",
                              "n_proyectos": len(corrida.listas), "n_lineas_base_nuevas": n_lb,
                              "resultado": "ok", "detalle_error": ""}]
    alcance = {l.id for l in listas} if solo else None
    corrida.nuevas = nuevas
    corrida.lb_nuevas = [f for f in fusionar("linea_base", existentes.get("linea_base", []), nuevas["linea_base"], corte)
                         [len(existentes.get("linea_base", [])):]]
    ident = {r.lista.id: identificacion(r) for r in corrida.listas}
    for t in E.CON_ULTIMO_CORTE:           # tambien en el CSV del dry-run
        nuevas[t] = completar(t, fusionar(t, existentes.get(t, []), nuevas[t], corte, alcance, tipo_corte,
                                          RETENCION_PRELIMINAR_DIAS), ident)[
            -len(nuevas[t]):] if nuevas[t] else []
    corrida.finales = {t: completar(t, fusionar(t, existentes.get(t, []), nuevas[t], corte, alcance, tipo_corte,
                                                RETENCION_PRELIMINAR_DIAS), ident)
                       for t in E.TABLAS if t != "linea_base"}
    corrida.filas_antes = {t: len(existentes.get(t, [])) for t in E.TABLAS}
    corrida.plan_sheets = sheets.plan(corrida.finales, corrida.lb_nuevas)

    # Controles de cordura, antes de escribir
    corrida.fallos = CTL.verificar(
        corte, [e.date for e in entradas], [_control(r, lb_exist) for r in corrida.listas],
        existentes.get("ejecuciones", []), existentes.get("metricas_semanales", []),
        umbrales or CTL.cargar_umbrales(), parcial=bool(solo))

    if dry_run:
        dest = dir_dry_run(corte, tipo_corte)
        AlmacenCsv(dest).escribir(nuevas)
        _escribir_resumen(corrida, dest / "resumen.json")
    elif corrida.fallos:
        fila = dict(nuevas["ejecuciones"][0], resultado="control_fallido",
                    detalle_error=" | ".join(corrida.fallos)[:1000])
        sheets.escribir({"ejecuciones": fusionar("ejecuciones", existentes.get("ejecuciones", []), [fila], corte)}, [])
        corrida.peticiones_sheets = dict(sheets.peticiones)
        raise ControlFallido("Controles de cordura fallidos (no se escribió nada): " + " | ".join(corrida.fallos))
    else:
        ajenas = [t for t in eliminar_pestañas if t in sheets.metadata()]
        crudas = sheets.valores_crudos(ajenas)
        con_datos = [t for t, v in crudas.items() if any(x not in (None, "") for fila in v for x in fila)]
        if con_datos:
            raise SystemExit(f"No se borran pestañas con datos: {', '.join(con_datos)}")
        corrida.respaldo = _respaldar(existentes, crudas, sheets, ahora)
        try:
            sheets.escribir(corrida.finales, corrida.lb_nuevas, eliminar=ajenas)
            problemas, corrida.tipos = sheets.verificar_tipos(E.TABLAS)
            if problemas:
                raise RuntimeError("Tipos no reconocidos por Sheets: " + "; ".join(problemas))
            corrida.verificacion = _verificar_lectura(sheets, corrida, existentes)
        except Exception as e:  # registrar el error en ejecuciones (mejor esfuerzo) y relanzar
            try:
                fila = dict(nuevas["ejecuciones"][0], resultado="error", detalle_error=str(e)[:500])
                ej = fusionar("ejecuciones", existentes.get("ejecuciones", []), [fila], corte)
                sheets.escribir({"ejecuciones": ej}, [])
            except Exception:
                log.exception("No se pudo registrar el error en ejecuciones")
            raise
    corrida.peticiones_sheets = dict(sheets.peticiones)
    return corrida


def dir_dry_run(corte: dt.date, tipo_corte: str) -> Path:
    return DRY_RUN_DIR / (corte.isoformat() if tipo_corte == E.OFICIAL else f"{corte.isoformat()}_preliminar")


def _control(r: ResultadoLista, lb_exist: list[LB.FilaLB]) -> CTL.ProyectoControl:
    vig = LB.vigente(lb_exist, r.lista.id)
    m = r.resultado.metricas
    return CTL.ProyectoControl(
        r.lista.id, r.codigo, r.lb_filas[0].rev if r.lb_filas else None,
        sum(f.hh for f in vig[1]) if vig else None, m["total_hh"], m["hh_prog_acum"], m["avance_prog"])


def _respaldar(existentes: dict[str, list[dict]], crudas: dict[str, list[list]], sheets: AlmacenSheets,
               ahora: dt.datetime):
    """Copia local de lo que habia en la hoja antes de escribir: pestañas del esquema, pestañas que se
    borran y la lista de pestañas con su configuracion."""
    dest = RESPALDOS_DIR / ahora.strftime("%Y%m%dT%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    AlmacenCsv(dest).escribir(existentes)
    for t, valores in crudas.items():
        (dest / f"pestana_{t}.json").write_text(json.dumps(valores, ensure_ascii=False, default=str), encoding="utf-8")
    meta = {t: {"sheetId": p["sheetId"], "gridProperties": p.get("gridProperties")} for t, p in sheets.metadata().items()}
    (dest / "metadata.json").write_text(json.dumps(
        {"spreadsheet_id": sheets.id, "locale": getattr(sheets, "locale", None), "zona": getattr(sheets, "zona", None),
         "pestañas": meta, "respaldado_en": ahora.isoformat()}, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest


def _verificar_lectura(sheets: AlmacenSheets, c: "Corrida", antes: dict[str, list[dict]]) -> dict:
    """Relee todas las pestañas y las compara celda a celda (en la representacion del CSV) con lo escrito."""
    leido = sheets.leer(E.TABLAS)
    out = {}
    for t in E.TABLAS:
        if t == "linea_base":
            esperado = list(antes.get(t, [])) + list(c.lb_nuevas)
        else:
            esperado = list(c.finales.get(t, []))
        ti = E.tipos(t)
        rep_ = lambda filas: [[celda_csv(f.get(k), ti[k]) for k in E.columnas(t)] for f in filas]
        out[t] = {"filas_leidas": len(leido.get(t, [])), "filas_esperadas": len(esperado),
                  "ok": rep_(leido.get(t, [])) == rep_(esperado), "duplicados": duplicados(t, leido.get(t, []))}
    return out


def _escribir_resumen(c: Corrida, ruta) -> None:
    resumen = {
        "corte": c.corte.isoformat(), "tipo_corte": c.tipo_corte, "modo_calculo": c.modo.nombre,
        "primera_corrida": c.primera_corrida, "controles_fallidos": c.fallos,
        "n_entradas_tiempo": c.n_entradas, "peticiones_clickup": c.peticiones_clickup,
        "peticiones_sheets_lectura": dict(c.peticiones_sheets) if c.peticiones_sheets else None,
        "plan_sheets": c.plan_sheets, "segundos_clickup": round(c.segundos_clickup, 1),
        "filas": {t: len(f) for t, f in c.nuevas.items()},
    }
    ruta.write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dep_reportes.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tipo-corte", choices=[E.OFICIAL, E.PRELIMINAR], default=E.OFICIAL)
    ap.add_argument("--corte", help="oficial: domingo (por defecto el último); preliminar: cualquier día (por defecto ayer)")
    ap.add_argument("--dry-run", action="store_true", help="CSV en reportes/dry_run/<corte>/, sin tocar Sheets")
    ap.add_argument("--solo", help="procesar solo esta lista")
    ap.add_argument("--modo", choices=["dep", "legado"], default="dep")
    ap.add_argument("--eliminar-pestanas", default="",
                    help="pestañas ajenas al esquema a borrar, separadas por coma (solo si están vacías)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    corte = fecha_corte(a.corte, dt.datetime.now(TZ).date(), a.tipo_corte)
    c = ejecutar(corte, dry_run=a.dry_run, solo=a.solo, modo=por_nombre(a.modo), tipo_corte=a.tipo_corte,
                 eliminar_pestañas=tuple(x.strip() for x in a.eliminar_pestanas.split(",") if x.strip()))
    imprimir(c, a.dry_run)
    return 1 if c.fallos else 0


def imprimir(c: Corrida, dry_run: bool) -> None:
    """Resumen de la corrida (sin secretos ni datos por persona)."""
    corte = c.corte
    print(f"Corte {corte} {c.tipo_corte} ({'dry-run' if dry_run else 'escritura'}, modo {c.modo.nombre}): "
          f"{len(c.listas)} proyectos, {len(c.lb_nuevas)} filas nuevas de línea base, "
          f"{sum(len(r.advertencias) for r in c.listas)} advertencias")
    print(f"  ClickUp: {sum(c.peticiones_clickup.values())} peticiones en {c.segundos_clickup:.0f} s; "
          f"Sheets: {c.peticiones_sheets}")
    for r in c.listas:
        m = r.resultado.metricas
        lb = f"{r.lb_filas[0].tipo} rev {r.lb_filas[0].rev}" if r.lb_filas else             ("en planificación" if r.decision.en_planificacion else "sin línea base")
        print(f"  {r.codigo:<20} JP={r.jp.username if r.jp else SIN_JP:<28} LB={lb:<22} avance prog={_f(m['avance_prog'])} real={_f(m['avance_real'])}")
    for f in c.fallos:
        print(f"  CONTROL FALLIDO: {f}")
    if dry_run:
        print(f"  CSV: {dir_dry_run(corte, c.tipo_corte)}")
    else:
        print(f"  Respaldo: {c.respaldo}")
        print("  Verificación de tipos (primeras 50 filas de cada pestaña): OK")
        for t, cols in c.tipos.items():
            print(f"    {t}: " + ", ".join(f"{k}={v}" for k, v in cols.items() if v != "texto"))
        print(f"  {'Pestaña':<20} {'antes':>6} {'después':>8} {'esperadas':>9}  relectura   duplicados")
        for t, v in c.verificacion.items():
            print(f"  {t:<20} {c.filas_antes.get(t, 0):>6} {v['filas_leidas']:>8} {v['filas_esperadas']:>9}  "
                  f"{'idénticas' if v['ok'] else 'DIFERENTES':<11} {v['duplicados']}")


def _f(x) -> str:
    return "  -   " if x is None else f"{x:.3f}"


if __name__ == "__main__":
    sys.exit(main())
