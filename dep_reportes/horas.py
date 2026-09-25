"""Reglas de conteo de horas (peritaje de horas, sección 7). Funciones puras, salvo leer_timetracker.

1. Depuracion de las entradas de tiempo de ClickUp:
   - importadas (origen "api": el lote del 04-05-2026 desde el Timetracker): fuera de todas las metricas;
     su lugar lo ocupa el saldo historico, calculado desde el Timetracker completo;
   - excluidas del total y contadas en `ejecuciones`: duplicados exactos (queda una copia), duracion <= 0 y
     fecha futura.
2. Saldo historico por proyecto: horas del Timetracker anteriores a la fecha de corte historico (primera entrada
   nativa de ClickUp de la lista, o la fecha fijada a mano en config/reportes.json).
3. Advertencias de conteo: horas en tarea padre, exceso en 00 Administracion, horas fuera del plazo del
   proyecto, fases con codigo de otro proyecto y horas del Timetracker que no estan en ClickUp.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from dep_clickup.client import parse_time_entry
from dep_clickup.config import TZ
from dep_clickup.models import TimeEntry

from .metricas import Horas, TareaMetrica
from .proyecto import (ADV_FASE_OTRO_PROYECTO, ADV_FUERA_DE_PLAZO, ADV_HORAS_ADMIN, ADV_HORAS_EN_PADRE,
                       ADV_LISTA_COMBINADA, ADV_TT_SIN_CLICKUP, Aviso, fases_por_tarea)

ORIGENES_IMPORTADOS = frozenset({"api"})
FASE_ADMINISTRACION = re.compile(r"^\s*0?0\b")          # "00 Administración"
CODIGO_EN_TEXTO = re.compile(r"(\d{4}\.\d{4}(?:-\d{4})?)")


# --- 1. Depuracion ----------------------------------------------------------------------------------

@dataclass
class Depuracion:
    nativas: list[TimeEntry] = field(default_factory=list)
    importadas: list[TimeEntry] = field(default_factory=list)
    duplicadas: int = 0
    duracion_no_positiva: int = 0
    futuras: int = 0

    def conteos(self) -> dict[str, int]:
        return {"n_importadas_excluidas": len(self.importadas), "n_duplicadas_excluidas": self.duplicadas,
                "n_duracion_no_positiva_excluidas": self.duracion_no_positiva, "n_futuras_excluidas": self.futuras}


def depurar(raw: Iterable[dict], hoy: dt.date, origenes_importados: frozenset[str] = ORIGENES_IMPORTADOS) -> Depuracion:
    """Clasifica las entradas crudas de la API (en el orden recibido; la primera copia de un duplicado queda)."""
    d = Depuracion()
    vistas: set[tuple] = set()
    for x in raw:
        if int(x.get("duration") or 0) <= 0:
            d.duracion_no_positiva += 1
            continue
        e = parse_time_entry(x)
        if e is None:
            d.duracion_no_positiva += 1
            continue
        if e.date > hoy:
            d.futuras += 1
            continue
        if e.source in origenes_importados:          # antes que los duplicados: se excluyen de todos modos
            d.importadas.append(e)
            continue
        clave = (e.user_id, e.task_id, e.start, e.duration_ms)
        if clave in vistas:
            d.duplicadas += 1
            continue
        vistas.add(clave)
        d.nativas.append(e)
    return d


# --- 2. Timetracker y saldo historico ---------------------------------------------------------------

@dataclass(frozen=True)
class RegistroTT:
    """Una fila del Timetracker antiguo (lista "Time Tracking"): una persona, un dia, horas y proyecto."""
    task_id: str
    usuario_id: int | None   # None: fila de saldo mensual sin persona (carga historica del 05-02-2026)
    fecha: dt.date
    horas: float
    codigo: str          # "2025.0019" (sin prefijo PJ-)


def _valor(t: dict, nombre: str):
    return next((c.get("value") for c in t.get("custom_fields", []) if c.get("name") == nombre), None)


def _opciones(t: dict, nombre: str) -> dict[int, str]:
    for c in t.get("custom_fields", []):
        if c.get("name") == nombre and c.get("type") == "drop_down":
            return {o["orderindex"]: o["name"] for o in c.get("type_config", {}).get("options", [])}
    return {}


def codigo_tt(t: dict) -> str | None:
    """Proyecto de una fila: "Proyecto v0.1" (el vigente) o, si esta vacio, "🧩 Proyecto" (el anterior)."""
    for campo in ("Proyecto v0.1", "🧩 Proyecto"):
        v = _valor(t, campo)
        if v in (None, ""):
            continue
        nombre = _opciones(t, campo).get(int(v), "")
        m = CODIGO_EN_TEXTO.match(nombre.strip())
        if m:
            return m.group(1)
    return None


def parse_timetracker(tareas: Iterable[dict]) -> list[RegistroTT]:
    """Filas con horas (time_estimate), fecha ("Día ingreso") y proyecto con codigo. Una fila con varios
    responsables se reparte en partes iguales; una sin responsable (saldo mensual) queda sin persona."""
    out = []
    for t in tareas:
        ms, dia, cod = t.get("time_estimate"), _valor(t, "Día ingreso"), codigo_tt(t)
        asignados = [a["id"] for a in t.get("assignees", []) if a.get("id") is not None]
        if not ms or not dia or not cod:
            continue
        fecha = dt.datetime.fromtimestamp(int(dia) / 1000, dt.timezone.utc).date()   # 08:00 UTC del dia
        for uid in asignados or [None]:
            out.append(RegistroTT(t["id"], int(uid) if uid is not None else None, fecha,
                                  int(ms) / 3_600_000 / max(len(asignados), 1), cod))
    return out


def leer_timetracker(cu, list_id: str) -> list[RegistroTT]:
    """Todas las filas (tambien archivadas) de la lista del Timetracker. Solo GET."""
    tareas: list[dict] = []
    for archivadas in ("false", "true"):
        page = 0
        while True:
            d = cu.get(f"/list/{list_id}/task", {"page": page, "subtasks": "true", "include_closed": "true",
                                                 "archived": archivadas})
            tareas += d.get("tasks", [])
            if d.get("last_page", True) or not d.get("tasks"):
                break
            page += 1
    return parse_timetracker(tareas)


def codigo_sin_prefijo(codigo: str) -> str:
    return re.sub(r"^(PJ|PR)-", "", codigo or "")


def corte_historico(nativas: Sequence[TimeEntry], manual: dt.date | None = None) -> dt.date | None:
    """Fecha desde la que manda ClickUp: la fijada a mano o la de la primera entrada nativa de la lista."""
    if manual:
        return manual
    return min((e.date for e in nativas), default=None)


def saldo_historico(registros: Sequence[RegistroTT], corte_hist: dt.date | None, corte: dt.date) -> float:
    """Horas del Timetracker antes del corte historico (sin entradas nativas: todas hasta el corte)."""
    limite = min(corte_hist - dt.timedelta(days=1), corte) if corte_hist else corte
    return sum(r.horas for r in registros if r.fecha <= limite)


def tt_sin_clickup(registros: Sequence[RegistroTT], corte_hist: dt.date | None, corte: dt.date,
                   nativas: Sequence[TimeEntry]) -> float:
    """Horas del Timetracker desde el corte historico hasta el corte del reporte, de personas que ese dia no
    tienen ninguna entrada nativa en la lista: posibles horas sin registrar en ClickUp."""
    if corte_hist is None:
        return 0.0
    con_registro = {(e.user_id, e.date) for e in nativas}
    return sum(r.horas for r in registros
               if corte_hist <= r.fecha <= corte and (r.usuario_id, r.fecha) not in con_registro)


# --- 3. Advertencias --------------------------------------------------------------------------------

def horas_en_padres(tareas: Sequence[TareaMetrica], horas: Sequence[Horas]) -> list[Aviso]:
    """Una advertencia por tarea con subtareas que tiene horas registradas directamente."""
    con_hijas = {t.parent for t in tareas if t.parent}
    nombres = {t.id: t.nombre for t in tareas}
    por_tarea: dict[str, float] = defaultdict(float)
    for h in horas:
        if h.tarea_id in con_hijas:
            por_tarea[h.tarea_id] += h.horas
    return [Aviso(ADV_HORAS_EN_PADRE, tid, f"{nombres[tid]}: {hs:.2f} h registradas en la tarea padre", {"horas": hs})
            for tid, hs in sorted(por_tarea.items(), key=lambda kv: -kv[1]) if hs > 0]


def horas_en_administracion(tareas: Sequence[TareaMetrica], horas: Sequence[Horas], umbral: float,
                            minimo_h: float = 0.0) -> list[Aviso]:
    """Horas en la fase 00 Administracion sobre `umbral` (fraccion) del proyecto y de al menos `minimo_h` horas."""
    total = sum(h.horas for h in horas)
    if not total:
        return []
    fases = fases_por_tarea(tareas)
    admin = sum(h.horas for h in horas if FASE_ADMINISTRACION.match(fases.get(h.tarea_id, "")))
    if admin / total <= umbral or admin < minimo_h:
        return []
    return [Aviso(ADV_HORAS_ADMIN, "", f"{admin:.1f} h de {total:.1f} ({admin / total:.0%}) en la fase 00 Administración "
                                       f"(umbral {umbral:.0%})", {"horas": admin, "fraccion": admin / total, "umbral": umbral})]


def horas_fuera_de_plazo(horas: Sequence[Horas], inicio: dt.date | None, fin: dt.date | None) -> list[Aviso]:
    antes = [h for h in horas if inicio and h.fecha < inicio]
    despues = [h for h in horas if fin and h.fecha > fin]
    if not antes and not despues:
        return []
    datos = {"inicio": inicio, "fin": fin, "n_antes": len(antes), "h_antes": sum(h.horas for h in antes),
             "n_despues": len(despues), "h_despues": sum(h.horas for h in despues)}
    return [Aviso(ADV_FUERA_DE_PLAZO, "", f"{len(antes)} entradas ({datos['h_antes']:.1f} h) antes del inicio {inicio} y "
                                          f"{len(despues)} ({datos['h_despues']:.1f} h) después del término {fin}", datos)]


def codigos_en_nombre(nombre: str) -> set[str]:
    """Codigos de proyecto presentes en un nombre: "PJ-2025.0019-0147" -> {2025.0019-0147, 2025.0019, 2025.0147}."""
    out: set[str] = set()
    for m in re.finditer(r"(\d{4})\.(\d{4})((?:-\d{4})*)", nombre or ""):
        anio, num, sufijos = m.groups()
        out |= {f"{anio}.{num}{sufijos}", f"{anio}.{num}"}
        out |= {f"{anio}.{s}" for s in sufijos.split("-") if s}
    return out


def _codigo_fase(t: TareaMetrica) -> str | None:
    m = re.search(r"(\d{4})\.(\d{4})", t.nombre or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def fases_de_otro_proyecto(tareas: Sequence[TareaMetrica], nombre_lista: str) -> list[Aviso]:
    """Fases (tareas de primer nivel) con un codigo que no esta en el nombre de la lista."""
    aceptados = codigos_en_nombre(nombre_lista)
    out = []
    for t in tareas:
        cod = None if t.parent else _codigo_fase(t)
        if cod and cod not in aceptados:
            out.append(Aviso(ADV_FASE_OTRO_PROYECTO, t.id, f"Fase \"{t.nombre}\" con código {cod}, que no está en el "
                                                           f"nombre de la lista", {"codigo_fase": cod}))
    return out


def lista_combinada(tareas: Sequence[TareaMetrica]) -> list[Aviso]:
    """Lista cuyas fases llevan codigos de mas de un proyecto (por ejemplo 0019-0147: fases de 0019 y de 0147)."""
    codigos = sorted({c for t in tareas if not t.parent for c in [_codigo_fase(t)] if c})
    if len(codigos) < 2:
        return []
    return [Aviso(ADV_LISTA_COMBINADA, "", f"Fases con códigos de {len(codigos)} proyectos: {', '.join(codigos)}",
                  {"codigos": codigos})]


def aviso_tt_sin_clickup(horas: float, desde: dt.date | None, minimo: float = 0.5) -> list[Aviso]:
    if horas < minimo or desde is None:
        return []
    return [Aviso(ADV_TT_SIN_CLICKUP, "", f"{horas:.1f} h del Timetracker desde el {desde} sin entradas en ClickUp "
                                          "de la misma persona y día", {"horas": horas, "desde": desde})]
