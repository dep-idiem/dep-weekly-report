import datetime as dt

from dep_reportes import calidad
from dep_reportes.metricas import TareaMetrica

D = dt.date


def T(id_, parent=None, s=D(2026, 9, 1), d=D(2026, 9, 5), hh=None, av=0.0):
    return TareaMetrica(id_, id_, parent, s, d, hh, av)


def tipos(adv, tarea=None):
    return {a.tipo for a in adv if tarea is None or a.tarea_id == tarea}


def test_doble_conteo_incluye_nietos():
    tareas = [T("F"), T("P", "F", hh=10), T("H", "P"), T("N", "H", hh=4)]
    adv = calidad.detectar(tareas)
    assert tipos(adv, "P") == {calidad.DOBLE_CONTEO}
    assert calidad.incumple_hh_en_hojas(adv)


def test_hh_en_no_hoja_sin_doble_conteo():
    adv = calidad.detectar([T("P", hh=10), T("H", "P")])
    assert tipos(adv, "P") == {calidad.HH_EN_PADRE}
    assert calidad.incumple_hh_en_hojas(adv)


def test_solo_hojas_cumple():
    adv = calidad.detectar([T("P"), T("H", "P", hh=3)])
    assert not calidad.incumple_hh_en_hojas(adv)
    assert adv == []


def test_fechas():
    adv = calidad.detectar([T("a", s=None, hh=2), T("b", d=None, hh=2), T("c", s=D(2026, 9, 5), d=D(2026, 9, 1)),
                            T("x", s=None, d=None)])
    assert tipos(adv, "a") == {calidad.SIN_FECHAS}
    assert tipos(adv, "b") == {calidad.SIN_FECHAS}
    assert tipos(adv, "c") == {calidad.DUE_ANTES_START}
    assert tipos(adv, "x") == set()  # sin HH no importa


def test_estimate():
    adv = calidad.detectar([T("a", hh=8), T("b", hh=8), T("c", hh=8)], estimate_h={"a": 8.0, "b": 4.0})
    assert tipos(adv, "a") == set()
    assert tipos(adv, "b") == {calidad.HH_VS_ESTIMATE}
    assert tipos(adv, "c") == {calidad.HH_VS_ESTIMATE}  # sin time estimate


def test_avance_vs_horas():
    tareas = [T("a", av=0.5), T("b", av=0.0), T("c", av=1.0), T("d")]
    adv = calidad.detectar(tareas, horas_por_tarea={"b": 2.0, "c": 1.0})
    assert tipos(adv, "a") == {calidad.AVANCE_SIN_HORAS}
    assert tipos(adv, "b") == {calidad.HORAS_SIN_AVANCE}
    assert tipos(adv, "c") == set()
    assert tipos(adv, "d") == set()
