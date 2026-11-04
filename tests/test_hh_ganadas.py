"""Curva de avance ganado en serie_diaria (presentacion.avances_por_lista / hh_ganadas)."""
import datetime as dt

from dep_reportes import esquema as E
from dep_reportes import presentacion as PR

D = dt.date


def test_escalonada_con_cortes_previos_y_el_actual():
    fechas = [D(2026, 10, 29) + dt.timedelta(days=i) for i in range(10)]       # 29-oct .. 7-nov
    avances = {D(2026, 11, 1): 0.0, D(2026, 11, 2): 0.0154}
    out = PR.hh_ganadas(fechas, avances, D(2026, 11, 3), 0.1, 130)
    assert out[:3] == [None, None, None]               # antes del primer corte
    assert out[3] == 0.0                               # 1-nov
    assert out[4] == round(0.0154 * 130, 4)            # 2-nov
    assert out[5] == 13.0                              # 3-nov: avance de la corrida
    assert out[6:] == [None] * 4                       # despues del corte


def test_sin_total_o_sin_avance():
    f = [D(2026, 11, 1), D(2026, 11, 2)]
    assert PR.hh_ganadas(f, {D(2026, 11, 1): 0.5}, D(2026, 11, 2), 0.6, None) == [None, None]
    assert PR.hh_ganadas(f, {}, D(2026, 11, 2), None, 100) == [None, None]
    assert PR.hh_ganadas(f, {}, D(2026, 11, 1), 0.25, 100) == [25.0, None]


def test_avances_por_lista_omite_corte_actual_y_prefiere_oficial():
    filas = [
        {"corte": D(2026, 11, 1), "tipo_corte": "oficial", "list_id": "a", "avance_real": 0.2},
        {"corte": D(2026, 11, 1), "tipo_corte": "preliminar", "list_id": "a", "avance_real": 0.9},
        {"corte": D(2026, 10, 25), "tipo_corte": "preliminar", "list_id": "a", "avance_real": 0.1},
        {"corte": D(2026, 10, 26), "tipo_corte": "preliminar", "list_id": "b", "avance_real": 0.3},
        {"corte": D(2026, 10, 26), "tipo_corte": "oficial", "list_id": "b", "avance_real": 0.4},
        {"corte": D(2026, 11, 3), "tipo_corte": "preliminar", "list_id": "a", "avance_real": 0.5},
        {"corte": D(2026, 10, 20), "tipo_corte": "oficial", "list_id": "c", "avance_real": None},
    ]
    out = PR.avances_por_lista(filas, D(2026, 11, 3))
    assert out == {"a": {D(2026, 11, 1): 0.2, D(2026, 10, 25): 0.1}, "b": {D(2026, 10, 26): 0.4}}


def test_columna_en_esquema():
    assert ("hh_ganadas_acum", E.NUMERO) in E.TABLAS["serie_diaria"]
