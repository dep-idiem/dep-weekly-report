"""Mensajes por JP con los puntos a corregir en ClickUp, para enviarlos a mano (no se envia nada).

Uso:
    python -m dep_reportes.mensajes_jp                      # ultimo corte de la hoja
    python -m dep_reportes.mensajes_jp --corte 2026-09-20 --tipo-corte oficial

Lee la hoja de reportes (solo lectura) y escribe reportes/mensajes_jp/<corte>/:
- <jp_nombre>.txt: un mensaje por JP (plantilla en config/, ver plantilla_mensaje_jp en reportes.json).
- _administracion.txt: advertencias cuyo responsable es Administracion DEP y proyectos sin JP.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from dep_clickup.config import ROOT

from . import esquema as E, presentacion as PR, resolucion as RES
from .config_reportes import parametros

SALIDA = ROOT / "reportes" / "mensajes_jp"
SIN_JP = "Sin JP"
ORDEN_IMPACTO = {RES.IMPIDE: 0, RES.DISTORSIONA: 1}      # las informativas no van en los mensajes
ENLACE_PENDIENTE = "[enlace pendiente: completar enlace_reporte en config/reportes.json]"
_TAREA_EN_MENSAJE = re.compile(r"«([^»]*)»")


@dataclass
class Proyecto:
    list_id: str
    codigo: str
    etiqueta: str
    jp: str
    tiene_linea_base: bool
    advertencias: list[dict] = field(default_factory=list)

    @property
    def motivo(self) -> str:
        return PR.motivo_sin_linea_base(a["tipo"] for a in self.advertencias)


def estado(p: Proyecto) -> str:
    return "Tiene curva S." if p.tiene_linea_base else f"Todavía no tiene curva S porque {p.motivo}."


def nombre_tarea(a: dict, nombres: dict[tuple[str, str], str]) -> str | None:
    n = nombres.get((a.get("list_id"), a.get("task_id")))
    if n:
        return n
    m = _TAREA_EN_MENSAJE.search(a.get("mensaje") or "")
    return m.group(1) if m else None


def puntos(p: Proyecto, nombres: dict[tuple[str, str], str], adm: str) -> list[str]:
    """Puntos a corregir por el JP: primero lo que impide la curva S, despues lo que distorsiona las cifras.
    Las repeticiones de un mismo tipo se juntan en un punto."""
    grupos: dict[tuple[int, str], list[dict]] = {}
    for a in p.advertencias:
        if a.get("responsable_accion") != RES.JP or a.get("impacto") not in ORDEN_IMPACTO or not a.get("como_resolver"):
            continue
        grupos.setdefault((ORDEN_IMPACTO[a["impacto"]], a["tipo"]), []).append(a)
    out = []
    for (_, tipo), filas in sorted(grupos.items(), key=lambda kv: kv[0][0]):   # estable: orden de aparicion
        grupal = RES.ACCION_GRUPAL.get(tipo)
        if len(filas) > 1 and grupal:
            tareas = [nombre_tarea(a, nombres) or "tarea sin nombre" for a in filas]
            out.append(grupal(RES.lista_tareas(tareas), len(tareas), p.tiene_linea_base, adm))
        else:
            out += list(dict.fromkeys(a["como_resolver"] for a in filas))
    return out


def bloque_proyecto(p: Proyecto, nombres: dict[tuple[str, str], str], adm: str) -> str:
    ps = puntos(p, nombres, adm)
    lineas = [p.etiqueta, f"Estado: {estado(p)}"]
    if ps:
        lineas.append("Puntos a corregir:")
        lineas += [f"  {i}. {x}" for i, x in enumerate(ps, 1)]
    else:
        lineas.append("Puntos a corregir: Sin observaciones.")
    return "\n".join(lineas)


def ordenar(proyectos: Sequence[Proyecto]) -> list[Proyecto]:
    """Primero los que no tienen curva S."""
    return sorted(proyectos, key=lambda p: (p.tiene_linea_base, p.codigo))


def mensaje_jp(jp: str, proyectos: Sequence[Proyecto], nombres, corte: dt.date, plantilla: str, cfg: dict) -> str:
    adm = cfg.get("responsable_administracion", "Administración DEP")
    fecha_oficial = cfg.get("fecha_primer_reporte_oficial")
    bloques = "\n\n".join(bloque_proyecto(p, nombres, adm) for p in ordenar(proyectos))
    return plantilla.format(
        jp_nombre=jp, jp_nombre_pila=jp.split()[0] if jp.split() else jp, corte=PR.fecha(corte),
        fecha_primer_reporte=PR.fecha(dt.date.fromisoformat(fecha_oficial)) if fecha_oficial else "[fecha por definir]",
        enlace_reporte=cfg.get("enlace_reporte") or ENLACE_PENDIENTE, proyectos=bloques, firma=adm,
    ).rstrip() + "\n"


def mensaje_administracion(proyectos: Sequence[Proyecto], corte: dt.date, adm: str) -> str:
    lineas = [f"Pendientes de {adm} (datos al {PR.fecha(corte)})", ""]
    n = 0
    for p in sorted(proyectos, key=lambda p: p.codigo):
        ps = list(dict.fromkeys(a["como_resolver"] for a in p.advertencias
                                if a.get("responsable_accion") == adm and a.get("como_resolver")))
        if ps:
            lineas.append(f"{p.etiqueta} (JP: {p.jp})")
            lineas += [f"  - {x}" for x in ps]
            lineas.append("")
            n += len(ps)
    if not n:
        lineas += ["Sin pendientes.", ""]
    sin_jp = [p for p in proyectos if p.jp == SIN_JP]
    if sin_jp:
        lineas += ["Proyectos sin JP (no reciben mensaje; revisar a quién enviar sus puntos):"]
        lineas += [f"  - {p.etiqueta}" for p in sorted(sin_jp, key=lambda p: p.codigo)]
        lineas.append("")
    return "\n".join(lineas).rstrip() + "\n"


def proyectos_del_corte(tablas: dict[str, list[dict]], corte: dt.date, tipo_corte: str) -> list[Proyecto]:
    del_corte = lambda f: f.get("corte") == corte and (f.get("tipo_corte") or E.OFICIAL) == tipo_corte
    ps = {f["list_id"]: Proyecto(f["list_id"], f["codigo"], f.get("proyecto") or f["codigo"],
                                 f.get("jp_nombre") or SIN_JP, bool(f.get("tiene_linea_base")))
          for f in tablas.get("metricas_semanales", []) if del_corte(f)}
    for a in tablas.get("advertencias", []):
        if del_corte(a) and a["list_id"] in ps:
            ps[a["list_id"]].advertencias.append(a)
    return list(ps.values())


def nombres_tareas(tablas: dict[str, list[dict]], corte: dt.date) -> dict[tuple[str, str], str]:
    """(list_id, task_id) -> nombre, de la foto de tareas mas reciente hasta el corte."""
    out: dict[tuple[str, str], tuple[dt.date, str]] = {}
    for f in tablas.get("fotos_tareas", []):
        c = f.get("corte")
        k = (f.get("list_id"), f.get("task_id"))
        if c and c <= corte and (k not in out or out[k][0] < c):
            out[k] = (c, f.get("task_nombre") or "")
    return {k: v[1] for k, v in out.items() if v[1]}


def archivo(nombre: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", nombre).strip(" ._") or "sin_nombre"


def generar(tablas: dict[str, list[dict]], corte: dt.date, tipo_corte: str, cfg: dict,
            plantilla: str) -> dict[str, str]:
    """nombre de archivo -> contenido."""
    proyectos = proyectos_del_corte(tablas, corte, tipo_corte)
    nombres = nombres_tareas(tablas, corte)
    adm = cfg.get("responsable_administracion", "Administración DEP")
    por_jp: dict[str, list[Proyecto]] = defaultdict(list)
    for p in proyectos:
        if p.jp != SIN_JP:
            por_jp[p.jp].append(p)
    out = {f"{archivo(jp)}.txt": mensaje_jp(jp, ps, nombres, corte, plantilla, cfg) for jp, ps in sorted(por_jp.items())}
    out["_administracion.txt"] = mensaje_administracion(proyectos, corte, adm)
    return out


def ultimo_corte(tablas: dict[str, list[dict]]) -> tuple[dt.date, str]:
    f = next((f for f in tablas.get("metricas_semanales", []) if f.get("es_ultimo_corte")), None)
    if f is None:
        raise SystemExit("La hoja no tiene cortes en metricas_semanales")
    return f["corte"], f.get("tipo_corte") or E.OFICIAL


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dep_reportes.mensajes_jp", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corte", help="por defecto, el último corte de la hoja")
    ap.add_argument("--tipo-corte", choices=[E.OFICIAL, E.PRELIMINAR], default=E.OFICIAL)
    a = ap.parse_args(argv)
    from .almacen import AlmacenSheets
    from .config_reportes import SHEETS_REPORTES_ID
    tablas = AlmacenSheets(SHEETS_REPORTES_ID).leer(["metricas_semanales", "advertencias", "fotos_tareas"])
    corte, tipo = (dt.date.fromisoformat(a.corte), a.tipo_corte) if a.corte else ultimo_corte(tablas)
    cfg = parametros()
    plantilla = (ROOT / cfg.get("plantilla_mensaje_jp", "config/plantilla_mensaje_jp.txt")).read_text(encoding="utf-8")
    archivos = generar(tablas, corte, tipo, cfg, plantilla)
    dest = SALIDA / (corte.isoformat() if tipo == E.OFICIAL else f"{corte.isoformat()}_preliminar")
    dest.mkdir(parents=True, exist_ok=True)
    for nombre, txt in archivos.items():
        (dest / nombre).write_text(txt, encoding="utf-8")
    print(f"{len(archivos) - 1} mensajes de JP y _administracion.txt en {dest}")
    if not cfg.get("enlace_reporte"):
        print("  AVISO: falta enlace_reporte en config/reportes.json (los mensajes llevan un marcador)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
