"""Lineas base (Rev. 0, 1, ...) de los proyectos: congelar, importar desde Excel, revisar.

Las filas de la linea base solo se agregan; nunca se modifican ni se borran. La revision vigente de un
proyecto es la de numero mas alto.

Disparador de la Rev. 0: la tarea "1.2 ..." de la fase "01 ..." pasa a un estado de tipo cerrado
(grupos "done" o "closed" de ClickUp), excepto "No Aplica".

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
from .metricas import TareaMetrica
from .proyecto import (ADV_SIN_TAREA_12, ADV_TAREA_12_NO_APLICA, ADV_VARIAS_TAREAS_12, NO_APLICA,
                       Aviso, es_no_aplica, fases_por_tarea)

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
    """Filas de una revision -> tareas del programa y fase de cada una."""
    tareas = [TareaMetrica(f.task_id, f.task_nombre, None, f.start, f.due, f.hh, None) for f in filas]
    return tareas, {f.task_id: f.fase for f in filas}


# --- Congelar -----------------------------------------------------------------------------------

def inicio_proyecto(lista: ListInfo, tareas: Sequence[Task]) -> dt.date | None:
    """Fecha de inicio de la lista o, si falta, el start mas temprano de sus tareas."""
    if lista.start:
        return lista.start.date()
    starts = [t.start_date for t in tareas if t.start_date]
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


def incrementales(lista: ListInfo, tareas: Sequence[Task], paquetes: set[str], filas_vigentes: Sequence[FilaLB],
                   ahora: dt.datetime, excluir_no_aplica: bool = True) -> list[FilaLB]:
    """Paquetes creados despues de la captura de la revision vigente que aun no estan en ella, con HH y fechas.
    Se agregan como filas `incremental` de la misma revision: la curva programada crece y la revision no cambia."""
    if not filas_vigentes:
        return []
    base = [f for f in filas_vigentes if f.tipo != "incremental"] or list(filas_vigentes)
    captura, rev = min(f.fecha_captura for f in base), base[0].rev
    en_lb = {f.task_id for f in filas_vigentes}
    tm = {t.id: t for t in a_tareas_metrica(tareas)}
    fases = fases_por_tarea(list(tm.values()))
    out = []
    for t in tareas:
        x = tm[t.id]
        if (t.id in paquetes and t.id not in en_lb and x.hh and x.hh > 0 and x.start and x.due
                and t.date_created and t.date_created > captura and not (excluir_no_aplica and es_no_aplica(x))):
            out.append(FilaLB(lista.id, rev, "incremental", ahora, f"Paquete nuevo después de la Rev. {rev} "
                              f"(creado el {t.date_created:%Y-%m-%d})", base[0].fecha_inicio,
                              base[0].fecha_entrega_contractual, t.id, t.name, fases[t.id], float(x.hh), x.start, x.due))
    return out


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
    """Tareas cuyo nombre empieza con "1.2" dentro de la fase "01"."""
    tm = a_tareas_metrica(tareas)
    fases = fases_por_tarea(tm)
    return [t for t in tareas if t.name.strip().startswith("1.2") and fases[t.id].strip().startswith("01")]


@dataclass(frozen=True)
class Decision:
    accion: str          # "ninguna" | "congelar" | "importar"
    tipo: str | None     # tipo de la Rev. 0 a crear
    estado: str          # "vigente" | "sin_linea_base"
    en_planificacion: bool
    avisos: tuple[Aviso, ...]


def decidir(list_id: str, tareas: Sequence[Task], existentes: Sequence[FilaLB], observada_antes: bool,
            primera_corrida: bool, importables: Sequence[str] = ()) -> Decision:
    """Que hacer con la linea base de un proyecto en este corte.

    observada_antes: la lista ya aparecia en cortes anteriores (fotos_tareas).
    primera_corrida: no hay ninguna ejecucion de escritura previa.
    """
    if vigente(existentes, list_id):
        return Decision("ninguna", None, "vigente", False, ())
    if list_id in importables:
        return Decision("importar", "importada_excel", "vigente", False, ())
    t12 = tareas_12(tareas)
    avisos: list[Aviso] = []
    if len(t12) > 1:
        avisos.append(Aviso(ADV_VARIAS_TAREAS_12, t12[0].id, f"{len(t12)} tareas 1.2 en la fase 01; se usa \"{t12[0].name}\"",
                            {"n": len(t12)}))
    if not t12:
        if primera_corrida:
            avisos.append(Aviso(ADV_SIN_TAREA_12, "", "Sin tarea 1.2 en la fase 01: Rev. 0 tardía con la foto actual",
                                {"tardia": True}))
            return Decision("congelar", "tardia", "vigente", False, tuple(avisos))
        avisos.append(Aviso(ADV_SIN_TAREA_12, "", "Sin tarea 1.2 en la fase 01: no se congela automáticamente"))
        return Decision("ninguna", None, "sin_linea_base", False, tuple(avisos))
    t = t12[0]
    if t.status.strip().lower() == NO_APLICA:
        avisos.append(Aviso(ADV_TAREA_12_NO_APLICA, t.id, f"\"{t.name}\" está en No Aplica: no se congela automáticamente"))
        return Decision("ninguna", None, "sin_linea_base", False, tuple(avisos))
    if t.cerrada:
        # La advertencia linea_base_tardia la emite run.procesar_lista mientras la Rev. 0 tardia este vigente.
        return Decision("congelar", "normal" if observada_antes else "tardia", "vigente", False, tuple(avisos))
    return Decision("ninguna", None, "sin_linea_base", True, tuple(avisos))


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
