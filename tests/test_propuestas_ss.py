"""Carga de propuestas (decisión de Ale del 2026-11-09): las tareas SS de SS_REGISTRO con responsable, fechas y estimate
cuentan como planificado bajo «Propuestas (SS)» en plan_vs_real y en el informe semanal (regla C)."""
import datetime as dt

from dep_clickup.config import TZ
from dep_clickup.models import Task
from dep_reportes import plan_vs_real as PVR
from dep_reportes.calendario import Calendario
from informe_semanal_horas import core as IC, fuentes as IF

D = dt.date
CAL = Calendario(frozenset())
L9, L16 = D(2026, 11, 9), D(2026, 11, 16)


def _ss(i, h, asig=("Genesis",), s=L9, d=L9 + dt.timedelta(days=4), estado="en elaboración", tipo="custom"):
    x = lambda v: dt.datetime(v.year, v.month, v.day, 12, tzinfo=TZ) if v else None
    return Task(i, f"2026.03{i} | SS", None, estado, "901324495476", x(s), x(d), int(h * 3_600_000) or None, tuple(asig), {},
                status_type=tipo)


def test_plan_vs_real_filas_de_propuestas_solo_con_responsable_fechas_y_estimate():
    plan = PVR.plan_por_persona([_ss("1", 10), _ss("2", 0), _ss("3", 5, asig=()), _ss("4", 4, s=None, d=None)], CAL)
    fs = PVR.filas_propuestas(D(2026, 11, 8), "oficial", "901324495476", plan)
    assert [(f["persona"], f["semana_inicio"], f["horas_planificadas"]) for f in fs] == [("Genesis", L9, 10)]
    assert fs[0]["proyecto"] == PVR.PROPUESTAS and fs[0]["list_id"] == "901324495476"
    assert set(fs[0]) == set(PVR.columnas()) - {"es_ultimo_corte"}


def test_informe_semanal_lee_ss_registro_como_propuestas():
    class Cu:
        def get(self, ruta, params=None):
            return {"folders": []} if ruta.endswith("/folder") else {"lists": []}
    listas = IF.listas_fuente(Cu())
    assert {"id": IC.SS_REGISTRO, "name": "SS_REGISTRO", "folder": "Propuestas", "archived": False, "jp": None} in listas
    t = {"id": "s", "name": "2026.0301 | SS", "parent": None, "time_estimate": 8 * 3_600_000, "start_date": None,
         "due_date": str(int(dt.datetime(2026, 11, 13, 12, tzinfo=TZ).timestamp() * 1000)),
         "list": {"id": IC.SS_REGISTRO, "name": "SS_REGISTRO"}, "status": "x", "assignees": [{"id": 7, "username": "Genesis"}]}
    a = IC.calcular_asignado(IC.Tareas.desde([t]), CAL, [L9])
    assert a[(7, L9)].horas == 8 and a[(7, L9)].listas == {IC.PROPUESTAS}


def test_ss_ganadas_perdidas_canceladas_y_cerradas_no_son_carga():
    ts = [_ss("1", 10), _ss("2", 5, estado="ganada"), _ss("3", 5, estado="Perdida"), _ss("4", 5, estado="cancelada"),
          _ss("5", 5, estado="cerrada", tipo="closed"), _ss("6", 3, estado="asignada"), _ss("7", 2, estado="enviada")]
    assert [t.id for t in PVR.ss_activas(ts)] == ["1", "6", "7"]
    raw = lambda i, estado: {"id": i, "name": "SS", "parent": None, "time_estimate": 8 * 3_600_000, "start_date": None,
                             "due_date": str(int(dt.datetime(2026, 11, 13, 12, tzinfo=TZ).timestamp() * 1000)),
                             "list": {"id": IC.SS_REGISTRO, "name": "SS_REGISTRO"}, "status": estado,
                             "assignees": [{"id": 7, "username": "Genesis"}]}
    a = IC.calcular_asignado(IC.Tareas.desde([raw("a", "en elaboración"), raw("b", "ganada"), raw("c", "cerrada")]), CAL, [L9])
    assert a[(7, L9)].horas == 8
