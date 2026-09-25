"""Cada tipo de advertencia tiene como resolverla, quien y su impacto (o esta explicitamente pendiente)."""
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

from dep_reportes import almacen as A, calidad, esquema as E, proyecto as P, resolucion as RES

TODOS_LOS_TIPOS = sorted({v for k, v in vars(P).items() if k.startswith("ADV_")} | set(calidad.SEVERIDAD))
RESPONSABLES = {RES.JP, RES.administracion(), RES.INFORMATIVA}
IMPACTOS = {RES.IMPIDE, RES.DISTORSIONA, RES.INFORMATIVA, RES.IMPIDE_PRESUPUESTO}
LARGO = "Tarea con un nombre bastante largo para probar el recorte del texto en la hoja de advertencias"


@pytest.mark.parametrize("tipo", TODOS_LOS_TIPOS)
def test_todo_tipo_tiene_solucion_o_esta_pendiente(tipo):
    """Falla si aparece un tipo nuevo sin solucion: agregarlo a resolucion.CATALOGO."""
    en = [tipo in RES.CATALOGO, tipo in RES.PENDIENTES, tipo in RES.SOLO_CALIDAD]
    assert sum(en) == 1, f"{tipo}: definir en resolucion.CATALOGO"


def test_pendientes_son_solo_los_conocidos():
    """Los pendientes esperan decision de Administracion DEP; al definirlos, moverlos a CATALOGO."""
    assert set(RES.PENDIENTES) == {"sin_tarea_1_2", "varias_tareas_1_2", "sin_termino_vigente",
                                   "tarea_de_linea_base_ahora_no_aplica"}
    assert set(RES.SOLO_CALIDAD) == P.SOLO_CALIDAD


@pytest.mark.parametrize("tipo", sorted(RES.CATALOGO))
@pytest.mark.parametrize("tiene_lb", [True, False])
def test_columnas_completas_cortas_y_sin_codigos(tipo, tiene_lb):
    ctx = RES.Contexto(LARGO, "2026.0152 · " + LARGO, tiene_lb,
                       {"codigo": "PJ-2026.0152", "nombre": LARGO, "codigo_base": "PJ-2026.0152",
                        "fecha": dt.datetime(2026, 9, 23), "falta": "due"})
    r = RES.resolver(tipo, ctx)
    assert r["responsable_accion"] in RESPONSABLES and r["impacto"] in IMPACTOS
    txt = r["como_resolver"]
    assert txt and len(txt) <= 220, (len(txt), txt)
    assert tipo not in txt and "_" not in txt and "__" not in txt
    for voseo in ("asigná", "corregí", "registrá", "actualizá", "pedí", "avisá", "cargá", "borrá", "dejá"):
        assert voseo not in txt.lower()


def test_impacto_depende_de_la_linea_base():
    doble = lambda lb: RES.resolver("hh_en_padre_y_subtarea", RES.Contexto("6.2 Informe", "x", lb))
    assert doble(True)["impacto"] == RES.DISTORSIONA and doble(False)["impacto"] == RES.IMPIDE
    assert "avisa a Administración DEP" in doble(False)["como_resolver"]
    assert "avisa" not in doble(True)["como_resolver"]
    assert RES.resolver("hh_sin_start_o_due", RES.Contexto("T", "x", False))["impacto"] == RES.IMPIDE


def test_ejemplos_de_texto():
    r = RES.resolver("hh_sin_start_o_due", RES.Contexto("Visita 2/2", "x", True, {"falta": "start y due"}))
    assert r == {"como_resolver": "En ClickUp, asigna fecha de inicio y de término a «Visita 2/2».",
                 "responsable_accion": "JP", "impacto": RES.DISTORSIONA, "prioridad": RES.NORMAL}
    r = RES.resolver("sin_jp", RES.Contexto(lista="2026.0040 · Estudio"))
    assert r["responsable_accion"] == "Administración DEP" and "«2026.0040 · Estudio»" in r["como_resolver"]
    r = RES.resolver("nombre_lista_sin_formato", RES.Contexto(datos={"codigo": "PJ-2024.0008", "nombre": "AITO"}))
    assert r["como_resolver"] == "En ClickUp, renombra la lista como «PJ-2024.0008 | AITO | cliente»."
    assert RES.resolver("linea_base_tardia", RES.Contexto(datos={"fecha": dt.date(2026, 9, 23)}))[
        "responsable_accion"] == RES.INFORMATIVA
    assert RES.resolver("sin_termino_vigente", RES.Contexto()) == \
        {"como_resolver": None, "responsable_accion": None, "impacto": None, "prioridad": None}


def test_responsable_administracion_sale_de_config(monkeypatch):
    monkeypatch.setattr(RES, "parametros", lambda: {"responsable_administracion": "Oficina de Proyectos"})
    r = RES.resolver("tarea_1_2_no_aplica", RES.Contexto(lista="x"))
    assert "avisa a Oficina de Proyectos" in r["como_resolver"]
    assert RES.resolver("sin_jp", RES.Contexto())["responsable_accion"] == "Oficina de Proyectos"


def test_esquema_y_filas_antiguas():
    assert E.columnas("advertencias")[-4:] == ["como_resolver", "responsable_accion", "impacto", "prioridad"]
    f = A.completar("advertencias", [{"corte": dt.date(2026, 9, 13), "list_id": "1", "tipo": "horas_sin_avance",
                                      "proyecto": "2026.0152 · Nestlé"}], {})[0]
    assert f["responsable_accion"] == "JP" and f["impacto"] == RES.DISTORSIONA and f["como_resolver"]


def test_guia_al_dia():
    """docs/guia_advertencias.md debe regenerarse al cambiar el catalogo: python scripts/guia_advertencias.py"""
    raiz = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("guia", raiz / "scripts" / "guia_advertencias.py")
    guia = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guia)
    assert (raiz / "docs" / "guia_advertencias.md").read_text(encoding="utf-8") == guia.generar()
