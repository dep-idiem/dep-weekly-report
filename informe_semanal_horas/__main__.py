"""Informe semanal «Horas de la semana · equipo DEP». Solo lectura de ClickUp.

    python -m informe_semanal_horas                         # hoy; genera en local, sin publicar ni avisar
    python -m informe_semanal_horas --hoy 2026-10-23        # otra fecha de corte
    python -m informe_semanal_horas --solo-general          # sin las versiones por JP
    python -m informe_semanal_horas --publicar              # además sube los PDF a Drive
    python -m informe_semanal_horas --evento schedule       # job del worker: solo los jueves de 07:00 a 08:59 de Santiago

Cuando la fecha de corte es la fecha real, el día en curso va como futuro (el job corre a las 7:00) y sus horas
no cuentan. Con otra fecha, ese día ya cuenta como cerrado.

Salidas (en .gitignore): reportes/horas_semana/AAAA-MM-DD.json y los HTML horas_semana_DEP_AAAA-MM-DD.html y
horas_semana_<iniciales JP>_AAAA-MM-DD.html, cada uno con su PDF (sin el desglose de horas por tarea; ver pdf.py).
A Drive van solo los PDF (pedido de Ale, 05-nov); el HTML queda en local y solo se sube si su PDF falló
(Chrome ausente o con error: se avisa).

Pruebas con datos guardados: --entradas-crudo, --tareas-crudo y --planilla (xlsx local).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import yaml

from dep_clickup import ClickUpClient
from dep_clickup.config import ROOT, TZ
from dep_reportes.calendario import calendario_chile

from . import core, fuentes, pdf

CONFIG = ROOT / "config" / "informe_semanal.yaml"
SALIDA = ROOT / "reportes" / "horas_semana"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def corre_ahora(ahora: dt.datetime) -> bool:
    """GitHub usa UTC y Chile cambia de horario: hay dos cron (10 y 11 UTC). La ventana de dos horas tolera los
    atrasos de GitHub; si en verano corren ambos, el segundo reemplaza los mismos archivos."""
    return ahora.weekday() == 3 and 7 <= ahora.hour < 9


def parametros(hoy: dt.date, hoy_real: dt.date, cfg: dict) -> core.Parametros:
    ultimo = hoy - dt.timedelta(days=1) if hoy == hoy_real else hoy
    return core.Parametros(hoy, ultimo, int(cfg.get("excluir_nuevos_semanas", 4)), tuple(cfg.get("excluir") or ()),
                           bool(cfg.get("estimacion_sin_adm")), tuple(cfg.get("incluir") or ()),
                           cfg.get("jornadas") or {}, float(cfg.get("jornada_estandar") or core.JORNADA_ESTANDAR),
                           tuple(cfg.get("sin_dias_fijos") or ()))


def leer_json(ruta: Path):
    return json.loads(ruta.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m informe_semanal_horas", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hoy", type=dt.date.fromisoformat, help="fecha de corte AAAA-MM-DD (por defecto, hoy)")
    ap.add_argument("--evento", default="manual", help="schedule: solo corre jueves de 07:00 a 08:59 de Santiago")
    ap.add_argument("--publicar", action="store_true", help="sube los PDF a Drive (por defecto no)")
    ap.add_argument("--sin-aviso", action="store_true", default=True,
                    help="por defecto y por ahora la única opción: no se avisa a nadie")
    ap.add_argument("--sin-pdf", action="store_true", help="no genera los PDF")
    ap.add_argument("--solo-general", action="store_true", help="no genera las versiones por JP")
    ap.add_argument("--salida", type=Path, default=SALIDA)
    ap.add_argument("--entradas-crudo", type=Path)
    ap.add_argument("--tareas-crudo", type=Path)
    ap.add_argument("--miembros-crudo", type=Path)
    ap.add_argument("--planilla", type=Path, help="xlsx local en vez de leerla de Drive")
    a = ap.parse_args(argv)

    ahora = dt.datetime.now(TZ)
    if a.evento == "schedule" and not corre_ahora(ahora):
        print(f"Fuera de ventana: {DIAS[ahora.weekday()]} {ahora:%Y-%m-%d %H:%M} (corre los jueves de 07:00 a 08:59 de Santiago)")
        return 0
    hoy = a.hoy or ahora.date()
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    if a.publicar and not cfg.get("carpeta_drive_id"):
        print("ERROR: falta carpeta_drive_id en config/informe_semanal.yaml; no se generó ni subió nada")
        return 1

    p = parametros(hoy, ahora.date(), cfg)
    cu = ClickUpClient()
    crudo_ent = leer_json(a.entradas_crudo) if a.entradas_crudo else fuentes.bajar_entradas(cu, hoy)
    crudo_tar = leer_json(a.tareas_crudo) if a.tareas_crudo else fuentes.bajar_tareas(cu)
    miembros = leer_json(a.miembros_crudo) if a.miembros_crudo else fuentes.miembros(cu)
    ws = fuentes.planilla_local(a.planilla) if a.planilla else fuentes.planilla_ausencias(cfg["planilla_ausencias_id"])
    ausencias = core.leer_ausencias(ws)

    entradas = core.normalizar_entradas(crudo_ent, cfg.get("cargas_api_fechas") or ())
    tareas = core.Tareas.desde(crudo_tar["tareas"])
    cal = calendario_chile(extra_csv=ROOT / "config" / "dias_no_habiles.csv")
    general = core.construir(entradas, tareas, miembros, ausencias, cal, p)
    generado = f"Generado el {DIAS[ahora.weekday()]} {ahora:%d-%m-%Y %H:%M}"

    a.salida.mkdir(parents=True, exist_ok=True)
    fecha = hoy.isoformat()
    archivos = {f"horas_semana_DEP_{fecha}.html": core.render(general, generado)}
    destino = {f"horas_semana_DEP_{fecha}.html": cfg.get("carpeta_general") or "General"}
    versiones = {}
    if not a.solo_general:
        jefes, sin_version = core.jefes(crudo_tar["listas"], cfg.get("jp_a_cargo") or {}, cfg.get("jefes_proyecto") or ())
        for nombre, n in sin_version.items():
            print(f"  {nombre}: {n} listas PJ como responsable y sin versión de JP (solo en el general)")
        for jp in jefes.values():
            v = core.version_jp(general, jp, entradas, tareas, cal)
            if v is None:
                print(f"  {jp['nombre']}: nadie con horas ni asignación en sus listas; sin archivo")
                continue
            sigla = core.iniciales(jp["nombre"], ausencias)
            archivos[f"horas_semana_{sigla}_{fecha}.html"] = core.render(v, generado)
            destino[f"horas_semana_{sigla}_{fecha}.html"] = jp["nombre"].strip()
            versiones[sigla] = {"jp": jp["nombre"], "personas": [x["nombre"] for x in v["personas"]]}
    binarios = {k: v.encode("utf-8") for k, v in archivos.items()}
    if not a.sin_pdf:
        for nombre, contenido in archivos.items():
            try:
                binarios[nombre[:-5] + ".pdf"] = pdf.html_a_pdf(contenido)
                destino[nombre[:-5] + ".pdf"] = destino[nombre]
            except Exception as e:      # el PDF es una copia: sin él siguen los HTML
                print(f"  AVISO: sin PDF de {nombre}: {e}")
    for nombre, contenido in binarios.items():
        (a.salida / nombre).write_bytes(contenido)
    (a.salida / f"{fecha}.json").write_text(json.dumps({**core._publico(general), "versiones": versiones},
                                                       ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")

    _, fuera = core.personas_incluidas(miembros, p)
    print(f"Corte {fecha} · registros hasta {p.ultimo_dia} · {len(general['personas'])} personas · {len(archivos)} HTML y {len(binarios) - len(archivos)} PDF en {a.salida}")
    for m in fuera:
        print(f"  fuera: {m['nombre']} ({m['motivo']})")
    sin_cruce = [x["nombre"] for x in general["personas"] if core.cruzar_nombre(x["nombre"], ausencias.dias) is None]
    if sin_cruce:
        print("  sin fila en la planilla de ausencias: " + ", ".join(sin_cruce))
    if a.publicar:
        from .drive import publicar
        subir = {k: v for k, v in binarios.items() if k.endswith(".pdf") or k[:-5] + ".pdf" not in binarios}
        carpetas, enlaces = publicar(subir, destino, cfg["carpeta_drive_id"])
        for nombre, url in enlaces.items():
            print(f"  {destino[nombre]}/{nombre}: {url}")
        print("Carpetas:")
        for carpeta, url in carpetas.items():
            print(f"  {carpeta}: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
