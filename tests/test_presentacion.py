"""Columnas de presentacion para Looker (nombre corto, cliente, titular, mensajes de advertencia)."""
import datetime as dt

import pytest

from dep_reportes import almacen as A, calidad, esquema as E, presentacion as PR, proyecto as P


# --- Nombre de la lista -------------------------------------------------------------------------

def test_partes_nombre_con_formato():
    assert PR.partes_nombre("PJ-2026.0152 | Evaluación estructural de Fábrica Nestlé Purina | NESTLE CHILE S.A") == \
        ("Evaluación estructural de Fábrica Nestlé Purina", "NESTLE CHILE S.A", True)
    # espacios sobrantes (como en 0123 y 0177)
    assert PR.partes_nombre("PJ-2026.0123 | INSPECCIÓN   VISUAL   | Corteva  ") == ("INSPECCIÓN VISUAL", "Corteva", True)
    assert PR.partes_nombre("PJ-2025.0019-0147 | Calibración | CMP")[2]


@pytest.mark.parametrize("nombre, corto", [
    ("PJ-2024.0008 | AITO Hospital Sotero del Río", "AITO Hospital Sotero del Río"),   # sin cliente
    ("PJ-2025.0019-0147 | Calibración y Ajustes en Modelos CMP", "Calibración y Ajustes en Modelos CMP"),
    ("PJ-2026.0001 | a | b | c", "a | b | c"),                                          # partes de mas
    ("PJ-2026.0001 |  | CMP", "CMP"),                                                   # nombre vacio
    ("PJ-2026.0001 - Algo", "Algo"),
    ("PJ-2026.0001", "PJ-2026.0001"),                                                   # solo el codigo
    ("Lista sin código | Algo | Cliente", "Lista sin código | Algo | Cliente"),
])
def test_partes_nombre_sin_formato_quita_el_codigo(nombre, corto):
    assert PR.partes_nombre(nombre) == (corto, None, False)
    assert PR.etiqueta_proyecto("PJ-2024.0008", corto).count("PJ-") == (1 if corto.startswith("PJ-") else 0)


def test_etiqueta_proyecto():
    assert PR.etiqueta_proyecto("PJ-2026.0152", "Evaluación") == "2026.0152 · Evaluación"
    assert PR.etiqueta_proyecto("PJ-2025.0019-0147-A", "Calibración") == "2025.0019-0147-A · Calibración"


# --- Titular ------------------------------------------------------------------------------------

def test_titular_bajo_sobre_y_en_linea():
    assert PR.titular(True, 0.732, 0.743) == "Avance real 73,2 % frente a 74,3 % programado: 1,1 puntos bajo el plan."
    assert PR.titular(True, 0.80, 0.743) == "Avance real 80,0 % frente a 74,3 % programado: 5,7 puntos sobre el plan."
    assert PR.titular(True, 0.745, 0.743) == "Avance real 74,5 % frente a 74,3 % programado: en línea con el plan."
    # el umbral es la diferencia sin redondear: 0,49 puntos esta en linea, 0,5 no
    assert "en línea" in PR.titular(True, 0.7479, 0.743)
    assert "0,5 puntos sobre" in PR.titular(True, 0.748, 0.743)


def test_titular_sin_linea_base():
    assert PR.titular(False, 0.7, None, "el proyecto está en planificación (la tarea 1.2 sigue abierta)") == \
        "Sin curva programada: el proyecto está en planificación (la tarea 1.2 sigue abierta)."
    assert PR.titular(False, None, None) == f"Sin curva programada: {PR.MOTIVO_GENERICO}."


def test_motivo_sin_linea_base_por_prioridad():
    assert PR.motivo_sin_linea_base(["tarea_1_2_no_aplica", "hh_en_padre_y_subtarea"]).startswith("hay HH contadas dos veces")
    assert PR.motivo_sin_linea_base(["sin_tarea_1_2", "linea_base_sin_hh"]) == "no hay tareas con HH presupuestadas"
    assert PR.motivo_sin_linea_base(["en_planificacion", "avance_sin_horas"]).startswith("el proyecto está en planificación")
    assert PR.motivo_sin_linea_base([]) == PR.MOTIVO_GENERICO


def test_derivadas_semanales():
    f = {"rev_linea_base": 0, "avance_real": 0.6846846846846847, "avance_prog": 0.7567567567567568,
         "hh_gastadas_acum": 152.6, "total_hh": 222.0}
    d = PR.derivadas_semanales(f)
    assert d["tiene_linea_base"] is True
    assert d["desviacion_pts"] == pytest.approx(-7.2072, abs=1e-4)
    assert d["pct_presupuesto_usado"] == pytest.approx(152.6 / 222)
    assert d["titular"] == "Avance real 68,5 % frente a 75,7 % programado: 7,2 puntos bajo el plan."
    sin = PR.derivadas_semanales({"rev_linea_base": None, "avance_real": 0.7, "hh_gastadas_acum": 31.0}, "x")
    assert sin == {"tiene_linea_base": False, "desviacion_pts": None, "pct_presupuesto_usado": None,
                   "titular": "Sin curva programada: x."}


# --- Advertencias -------------------------------------------------------------------------------

TODOS_LOS_TIPOS = sorted({v for k, v in vars(P).items() if k.startswith("ADV_")} | set(calidad.SEVERIDAD))


@pytest.mark.parametrize("tipo", TODOS_LOS_TIPOS)
def test_todo_tipo_tiene_mensaje_sin_codigos_tecnicos(tipo):
    for m in (PR.mensaje(tipo), PR.mensaje(tipo, "6.2 Informe", {"hh": 12.5, "n": 2})):
        assert m != "Advertencia sin descripción"
        assert tipo not in m and "_" not in m and "\"" not in m
    assert PR.nivel(tipo) in ("proyecto", "tarea")


def test_mensajes_con_datos():
    assert PR.mensaje("hh_en_padre_y_subtarea", "6.2", {"hh": 240, "suma": 120, "n": 24}) == \
        "HH contadas dos veces en 6.2: corregir antes de congelar la línea base"
    assert PR.mensaje("hh_cambiaron_vs_linea_base", None, {"actual": 612.5, "linea_base": 605}) == \
        "Las HH presupuestadas cambiaron: 612,5 en ClickUp frente a 605 en la línea base; evaluar una revisión"
    assert PR.mensaje("proyecto_con_termino_vencido", None, {"fin": dt.date(2026, 9, 20)}).startswith(
        "La fecha de término (20-09-2026) ya pasó")
    assert PR.mensaje("horas_sin_avance", "7.2 Revisión JP", {"horas": 1.0}) == \
        "«7.2 Revisión JP» tiene 1,00 h registradas pero 0 % de avance"
    assert PR.mensaje("hh_distinta_de_time_estimate", "X", {"hh": 15, "estimate": None}) == \
        "«X» tiene 15 HH presupuestadas pero no tiene time estimate"
    assert PR.nivel("hh_en_padre_y_subtarea") == "proyecto" and PR.nivel("avance_sin_horas") == "tarea"
    assert PR.nivel(P.ADV_NOMBRE_SIN_FORMATO) == "proyecto"


def test_detector_entrega_datos_para_el_mensaje():
    from dep_reportes.metricas import TareaMetrica
    D = dt.date
    tareas = [TareaMetrica("p", "06 Visitas", None, D(2026, 1, 1), D(2026, 12, 31), 240.0, 0.5),
              TareaMetrica("h", "Visita 1", "p", D(2026, 1, 1), D(2026, 1, 31), 120.0, 0.5)]
    adv = {a.tipo: a for a in calidad.detectar(tareas, {"p": 10.0, "h": 10.0})}
    a = adv[calidad.DOBLE_CONTEO]
    assert a.datos == {"hh": 240.0, "suma": 120.0, "n": 1}
    assert PR.mensaje(a.tipo, a.tarea, a.datos) == "HH contadas dos veces en 06 Visitas: corregir antes de congelar la línea base"


# --- Esquema y filas antiguas -------------------------------------------------------------------

def test_columnas_nuevas_en_el_esquema():
    for t in ("proyectos", "metricas_semanales", "metricas_fase", "serie_diaria", "advertencias"):
        assert {"codigo", "nombre_corto", "cliente", "proyecto"} <= set(E.columnas(t)), t
    assert E.tipos("metricas_semanales")["tiene_linea_base"] == E.BOOLEANO
    assert {"desviacion_pts", "pct_presupuesto_usado", "titular"} <= set(E.columnas("metricas_semanales"))
    assert "hh_linea_base" in E.columnas("serie_diaria")
    assert {"nivel", "mensaje"} <= set(E.columnas("advertencias"))


def test_completar_rellena_presentacion_en_filas_antiguas():
    ident = {"901": {"codigo": "PJ-1", "nombre_corto": "Nuevo nombre", "cliente": "CMP", "proyecto": "1 · Nuevo nombre",
                     "jp_nombre": "Ana", "jp_email": "a@x.cl"}}
    viejas = [{"corte": dt.date(2026, 9, 13), "list_id": "901", "codigo": "PJ-1", "nombre_corto": "Viejo",
               "jp_nombre": "Otra", "rev_linea_base": 0, "avance_real": 0.5, "avance_prog": 0.5,
               "hh_gastadas_acum": 10.0, "total_hh": 100.0}]
    out = A.completar("metricas_semanales", viejas, ident)[0]
    assert (out["nombre_corto"], out["cliente"], out["proyecto"], out["jp_nombre"]) == \
        ("Nuevo nombre", "CMP", "1 · Nuevo nombre", "Otra")
    assert out["titular"].endswith("en línea con el plan.") and out["pct_presupuesto_usado"] == 0.1
    adv = A.completar("advertencias", [{"corte": dt.date(2026, 9, 13), "list_id": "901", "tipo": "avance_sin_horas"}],
                      ident)[0]
    assert adv["nivel"] == "tarea" and adv["mensaje"] == "Una tarea tiene avance pero no tiene horas registradas"
