"""Lineas base (Rev. 0, 1, ...) de los proyectos: congelar, importar desde Excel, revisar.

Las filas de la linea base solo se agregan; nunca se modifican ni se borran. La revision vigente de un
proyecto es la de numero mas alto.

Disparador de la Rev. 0, igual para todas las listas (antiguas y v2; TAREA_curva_programada_unica, 2026-11-03): la
primera hora registrada en la lista (evento_congelar). Hasta entonces el estado es "provisional" y el programado sale
de las HH y fechas vigentes (run.procesar_lista). Si la primera hora fue antes de la semana del corte en una lista ya
observada, la Rev. 0 es "tardia" (se congela con la foto de hoy). No se congela (programada.estado): una lista sin
presupuesto, una con más horas registradas que presupuesto, una de un programa de servicio continuo ni una en
config/reportes.json "linea_base_retenida". La tarea 1.2 y la primera porción ya no disparan nada, y las tareas
nuevas no se agregan a una línea base ya congelada (se ven como desvío).

La Rev. 0 guarda el presupuesto (HH de cada tarea), las fechas de ClickUp de cada tarea y el inicio y término de la
lista; la programada se reconstruye siempre con esos datos y la regla de programada.programar (programada()).

Uso (revision manual):
    python -m dep_reportes.linea_base revisar --list-id <id> --motivo "..." [--tipo tardia] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import asdict, dataclass
from typing import Sequence

from dep_clickup.config import TZ
from dep_clickup.models import ListInfo, Task

from . import metricas as m
from .adaptador_clickup import a_tareas_metrica
from . import programada as PROG
from .metricas import TareaMetrica
from .programada import Programada, programar
from .proyecto import NO_APLICA, Aviso, es_no_aplica, fases_por_tarea

PROVISIONAL = "provisional"

# incremental: paquete creado despues de la revision vigente, congelado al aparecer con HH y fechas (misma rev).
TIPOS = ("normal", "tardia", "importada_excel", "revision", "incremental")


@dataclass(frozen=True)
class FilaLB:
    list_id: str
    rev: int
    tipo: str
    fecha_captura: dt.datetime
    motivo: str
    fecha_inicio: dt.date | None
    fecha_entrega_contractual: dt.date | None
    task_id: str
    task_nombre: str
    fase: str
    hh: float
    start: dt.date | None
    due: dt.date | None

    def fila(self) -> dict:
        return asdict(self)


# --- Lectura ------------------------------------------------------------------------------------

def revisiones(filas: Sequence[FilaLB], list_id: str) -> dict[int, list[FilaLB]]:
    out: dict[int, list[FilaLB]] = {}
    for f in filas:
        if f.list_id == list_id:
            out.setdefault(f.rev, []).append(f)
    return out


def vigente(filas: Sequence[FilaLB], list_id: str) -> tuple[int, list[FilaLB]] | None:
    revs = revisiones(filas, list_id)
    if not revs:
        return None
    r = max(revs)
    return r, revs[r]


def a_tareas(filas: Sequence[FilaLB]) -> tuple[list[TareaMetrica], dict[str, str]]:
    """Filas de una revision -> tareas del programa (fechas de ClickUp tal como se congelaron) y fase de cada una."""
    tareas = [TareaMetrica(f.task_id, f.task_nombre, None, f.start, f.due, f.hh, None) for f in filas]
    return tareas, {f.task_id: f.fase for f in filas}


def programada(filas: Sequence[FilaLB], cal) -> Programada:
    """Programada de una revision: sus tareas, repartidas con la regla de programada.programar dentro del inicio y
    termino de la lista guardados al congelar (las tareas con fechas fuera de ese rango, o sin fechas, se reparten en
    todo el rango)."""
    tareas, _ = a_tareas(filas)
    inicio = next((f.fecha_inicio for f in filas if f.fecha_inicio), None)
    termino = next((f.fecha_entrega_contractual for f in filas if f.fecha_entrega_contractual), None)
    return programar(m.universo(tareas), inicio, termino, cal)


# --- Congelar -----------------------------------------------------------------------------------

def inicio_proyecto(lista: ListInfo, tareas: Sequence[Task]) -> dt.date | None:
    """Fecha de inicio de la lista o, si falta, el start mas temprano de las tareas del presupuesto (con HH). Las
    fechas de tareas sin HH no se leen (TAREA_curva_programada_unica)."""
    if lista.start:
        return lista.start.date()
    starts = [t.start for t in m.universo(a_tareas_metrica(tareas)) if t.start]
    return min(starts) if starts else None


def congelar(lista: ListInfo, tareas: Sequence[Task], rev: int, tipo: str, motivo: str,
             ahora: dt.datetime, excluir_no_aplica: bool = True) -> list[FilaLB]:
    """Foto actual de las tareas con HH > 0 (sin las "No Aplica")."""
    assert tipo in TIPOS
    tm = a_tareas_metrica(tareas)
    fases = fases_por_tarea(tm)
    inicio = inicio_proyecto(lista, tareas)
    contractual = lista.due.date() if lista.due else None
    return [FilaLB(lista.id, rev, tipo, ahora, motivo, inicio, contractual, t.id, t.nombre, fases[t.id],
                   float(t.hh), t.start, t.due)
            for t in m.universo(tm) if not (excluir_no_aplica and es_no_aplica(t))]


def desaparecidos(filas_vigentes: Sequence[FilaLB], tareas: Sequence[Task]) -> list[FilaLB]:
    """Filas de la linea base vigente cuya tarea ya no esta en la lista (borrada o movida). No se borran."""
    ids = {t.id for t in tareas}
    return [f for f in filas_vigentes if f.task_id not in ids]


def importar_excel(lista: ListInfo, tareas: Sequence[Task], ruta, contractual: dt.date, ahora: dt.datetime,
                   excluir_no_aplica: bool = True) -> list[FilaLB]:
    """Rev. 0 desde la hoja Programado del Excel manual (task id, HH, start, due).

    Se excluyen las tareas que hoy estan en "No Aplica" en ClickUp.
    """
    from . import fixture_excel
    fx = fixture_excel.cargar(ruta)
    fases = fases_por_tarea(fx.programa)
    estado = {t.id: t.status for t in tareas}
    na = {tid for tid, st in estado.items() if (st or "").strip().lower() == NO_APLICA}
    motivo = f"Importada desde la hoja Programado de {ruta.name}"
    return [FilaLB(lista.id, 0, "importada_excel", ahora, motivo, inicio_proyecto(lista, tareas), contractual,
                   t.id, t.nombre, fases[t.id], float(t.hh), t.start, t.due)
            for t in m.universo(fx.programa) if not (excluir_no_aplica and t.id in na)]


# --- Disparador ---------------------------------------------------------------------------------

def tareas_12(tareas: Sequence[Task]) -> list[Task]:
    """Tareas cuyo nombre empieza con "1.2" dentro de la fase "01" (ya no disparan la Rev. 0; se conserva para
    informes)."""
    tm = a_tareas_metrica(tareas)
    fases = fases_por_tarea(tm)
    return [t for t in tareas if t.name.strip().startswith("1.2") and fases[t.id].strip().startswith("01")]


@dataclass(frozen=True)
class Evento:
    texto: str
    fecha: dt.date


def evento_congelar(fechas_horas: Sequence[dt.date], corte: dt.date) -> Evento | None:
    """La primera hora registrada en la lista hasta el corte (None si todavia no hay)."""
    horas = sorted(f for f in fechas_horas if f <= corte)
    return Evento(f"primera hora registrada el {horas[0]:%d-%m-%Y}", horas[0]) if horas else None


@dataclass(frozen=True)
class Decision:
    accion: str          # "ninguna" | "congelar" | "importar"
    tipo: str | None     # tipo de la Rev. 0 a crear
    estado: str          # "vigente" | "provisional" | "sin_linea_base"
    en_planificacion: bool   # ya no se usa (la tarea 1.2 no dispara); siempre False
    avisos: tuple[Aviso, ...]
    motivo: str | None = None   # texto de la Rev. 0 automática (el evento que la disparó)
    retenida: str | None = None  # motivo de config "linea_base_retenida" (queda provisional)


def decidir(list_id: str, tareas: Sequence[Task], existentes: Sequence[FilaLB], observada_antes: bool,
            primera_corrida: bool, importables: Sequence[str] = (), evento: Evento | None = None,
            corte: dt.date | None = None, retenidas: dict[str, str] | None = None,
            estado_curva: str | None = None) -> Decision:
    """Que hacer con la linea base de un proyecto en este corte.

    observada_antes: la lista ya aparecia en cortes anteriores (fotos_tareas).
    evento: evento_congelar de la lista (None = todavia no pasa).
    retenidas: list_id -> motivo; la lista no se congela aunque haya evento (config "linea_base_retenida").
    estado_curva: programada.estado. sin_presupuesto, presupuesto_incoherente y recurrente no congelan ni tienen
        programado provisional.
    """
    if vigente(existentes, list_id):
        return Decision("ninguna", None, "vigente", False, ())
    if list_id in importables:
        return Decision("importar", "importada_excel", "vigente", False, ())
    if estado_curva in (PROG.SIN_PRESUPUESTO, PROG.INCOHERENTE, PROG.RECURRENTE):
        return Decision("ninguna", None, "sin_linea_base", False, ())
    motivo_ret = (retenidas or {}).get(list_id)
    if motivo_ret:
        return Decision("ninguna", None, PROVISIONAL, False, (), retenida=motivo_ret)
    if evento is None:
        return Decision("ninguna", None, PROVISIONAL, False, ())
    # Tardía: el evento fue antes de la semana del corte y la lista ya se reportaba (se congela la foto de hoy).
    tardia = observada_antes and corte is not None and evento.fecha <= corte - dt.timedelta(days=7)
    tipo = "tardia" if tardia else "normal"
    return Decision("congelar", tipo, "vigente", False, (), f"Rev. 0 automática ({tipo}: {evento.texto})")


# --- CLI: revision manual -----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dep_reportes.linea_base", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("revisar", help="congela la Rev. N+1 con la foto actual de ClickUp")
    r.add_argument("--list-id", required=True)
    r.add_argument("--motivo", required=True)
    r.add_argument("--tipo", choices=["revision", "tardia"], default="revision",
                   help="tardia solo para crear la Rev. 0 de un proyecto que no tiene ninguna")
    r.add_argument("--dry-run", action="store_true", help="escribe CSV local en vez de Sheets")
    a = ap.parse_args(argv)

    from dep_clickup import ClickUpClient
    from .almacen import AlmacenCsv, AlmacenSheets, filas_lb_desde_tabla
    from .config_reportes import DRY_RUN_DIR, SHEETS_REPORTES_ID

    sheets = AlmacenSheets(SHEETS_REPORTES_ID)
    existentes = filas_lb_desde_tabla(sheets.leer(["linea_base"]).get("linea_base", []))
    cu = ClickUpClient()
    lista = cu.get_list_info(a.list_id)
    tareas = cu.list_tasks(a.list_id)
    v = vigente(existentes, a.list_id)
    rev = v[0] + 1 if v else 0
    if a.tipo == "tardia" and rev != 0:
        raise SystemExit(f"El proyecto ya tiene Rev. {v[0]}: una revision posterior debe ser de tipo 'revision'")
    ahora = dt.datetime.now(TZ).replace(microsecond=0)
    filas = congelar(lista, tareas, rev, a.tipo, a.motivo, ahora)
    if not filas:
        raise SystemExit("La lista no tiene tareas con HH Presupuestadas: no hay nada que congelar")
    print(f"{lista.name}: Rev. {rev} ({a.tipo}) con {len(filas)} tareas y {sum(f.hh for f in filas):g} HH")
    if a.dry_run:
        dest = AlmacenCsv(DRY_RUN_DIR / f"revision_{a.list_id}_{ahora:%Y%m%dT%H%M%S}")
        dest.agregar_linea_base(filas)
        print(f"dry-run: {dest.dir}")
    else:
        sheets.agregar_linea_base(filas)
        print("Revisión agregada a la pestaña linea_base")
    return 0


if __name__ == "__main__":
    sys.exit(main())
