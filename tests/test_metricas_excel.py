"""Paso 4a: metricas.py contra el Excel de referencia (se salta si el fixture no esta)."""
import datetime as dt
from pathlib import Path

import pytest

from dep_reportes import comparacion, metricas as m
from dep_reportes.calendario import Calendario

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "Curva S - Proyecto 2026.0152.xlsx"


@pytest.fixture(scope="module")
def fx():
    if not FIXTURE.exists():
        pytest.skip("fixture Excel no disponible (fixtures/ no se versiona)")
    from dep_reportes import fixture_excel
    return fixture_excel.cargar(FIXTURE)


def test_parametros_del_excel(fx):
    assert fx.control == dt.date(2026, 9, 19)
    assert fx.fin == dt.date(2026, 10, 2)


def test_total_hh(fx):
    assert m.total_hh(fx.programa) == 605


def test_avances(fx):
    assert m.avance_programado(fx.programa, fx.control) == pytest.approx(0.747107, abs=1e-4)
    assert m.avance_real(fx.avance) == pytest.approx(0.732231, abs=1e-4)
    assert m.avance_programado(fx.programa, fx.control) == pytest.approx(fx.avance_programado, abs=1e-12)
    assert m.avance_real(fx.avance) == pytest.approx(fx.avance_real, abs=1e-12)


def test_serie_resumen_punto_a_punto(fx):
    serie = m.serie_resumen(fx.grilla, fx.programa, fx.avance, fx.horas, fx.control, fx.fin)
    assert len(serie) == len(fx.serie) == 19
    for a, b in zip(serie, fx.serie):
        assert a.fecha == b.fecha
        assert a.programadas == pytest.approx(b.programadas, abs=0.01)
        for x, y in ((a.gastadas, b.gastadas), (a.proyectadas, b.proyectadas)):
            assert (x is None) == (y is None), a.fecha
            if x is not None:
                assert x == pytest.approx(y, abs=0.01), a.fecha


def test_todas_las_celdas(fx):
    malos = [c for c in comparacion.validar_4a(fx) if not c.ok]
    assert not malos, malos[:5]


def test_fechas_de_entradas_como_el_excel(fx):
    for e in fx.entradas:
        assert e.fecha == e.fecha_excel
        assert e.horas == pytest.approx(e.horas_excel, abs=1e-9)


def test_fases_suman_el_total(fx):
    fases = m.agregado_por_fase(fx.programa, fx.horas, fx.control, padres=fx.padres, nombres=fx.nombres)
    assert sum(f.hh_programadas for f in fases) == pytest.approx(605)
    assert sum(f.hh_gastadas_a_control for f in fases) == pytest.approx(m.hh_gastadas_a(fx.control, fx.horas, fx.control))
    assert sum(f.hh_programadas_a_control for f in fases) == pytest.approx(
        m.acumulado_a(m.hh_programadas_diarias(fx.programa), fx.control))


# --- Casos sinteticos (no dependen del fixture) --------------------------------------------------

def T(id_, s, d, hh, av=0.0, parent=None):
    return m.TareaMetrica(id_, id_, parent, s, d, hh, av)


D = dt.date


def test_networkdays_como_excel():
    cal = Calendario()
    assert cal.networkdays(D(2026, 8, 14), D(2026, 8, 14)) == 1          # viernes
    assert cal.networkdays(D(2026, 9, 19), D(2026, 9, 20)) == 0          # sabado-domingo
    assert cal.networkdays(D(2026, 8, 14), D(2026, 9, 19)) == 26
    assert cal.networkdays(D(2026, 8, 21), D(2026, 8, 14)) == -6
    assert Calendario(frozenset({D(2026, 9, 18)})).networkdays(D(2026, 9, 14), D(2026, 9, 18)) == 4


def test_fraccion_programada_casos():
    C = D(2026, 9, 16)  # miercoles
    assert m.fraccion_programada(T("a", D(2026, 9, 17), D(2026, 9, 18), 1), C) == 0
    assert m.fraccion_programada(T("a", D(2026, 9, 14), D(2026, 9, 18), 1), C) == pytest.approx(3 / 5)
    assert m.fraccion_programada(T("a", D(2026, 9, 7), D(2026, 9, 11), 1), C) == 1


def test_pendientes_tres_casos():
    C, fin = D(2026, 9, 16), D(2026, 9, 25)
    atrasada = m.hh_pendientes_tarea(T("a", D(2026, 9, 7), D(2026, 9, 11), 10, 0.5), C, fin)
    assert min(atrasada) == D(2026, 9, 17) and max(atrasada) == fin
    assert sum(atrasada.values()) == pytest.approx(5)
    en_curso = m.hh_pendientes_tarea(T("b", D(2026, 9, 14), D(2026, 9, 18), 6, 0.0), C, fin)
    assert sorted(en_curso) == [D(2026, 9, 16), D(2026, 9, 17), D(2026, 9, 18)]
    futura = m.hh_pendientes_tarea(T("c", D(2026, 9, 21), D(2026, 9, 22), 4), C, fin)
    assert futura == {D(2026, 9, 21): 2, D(2026, 9, 22): 2}
    assert m.hh_pendientes_tarea(T("d", D(2026, 9, 21), D(2026, 9, 22), 4, 1.0), C, fin) == {}


def test_gastadas_estrictamente_menor_y_na():
    h = [m.Horas(D(2026, 9, 15), 2), m.Horas(D(2026, 9, 16), 3)]
    assert m.hh_gastadas_a(D(2026, 9, 16), h, D(2026, 9, 16)) == 2
    assert m.hh_gastadas_a(D(2026, 9, 17), h, D(2026, 9, 16)) is None


def test_grilla_incluye_control_y_fin():
    g = m.grilla(D(2026, 9, 1), D(2026, 9, 30), D(2026, 9, 16))
    assert g[0] == D(2026, 9, 1) and D(2026, 9, 16) in g and g[-1] == D(2026, 9, 30)
