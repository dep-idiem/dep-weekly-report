"""TAREA_pj_asignar_v2 B.4: lectura de ausencias desde ADM-07 (plan_vs_real, informe semanal) y códigos ADM de dos dígitos.
Lo que corre en producción; la asignación, la carga base y el orden de ADM están en test_pj_asignar.py."""
import datetime as dt

from dep_clickup.config import TZ
from dep_clickup.models import CustomField, Task
from dep_clickup.naming import list_code
from dep_reportes import ausencias as AUS, plan_vs_real as PVR
from dep_reportes.calendario import Calendario
from informe_semanal_horas import core as IC

D = dt.date
CAL = Calendario(frozenset({D(2026, 12, 8)}))
L9, L16 = D(2026, 11, 9), D(2026, 11, 16)


def ms(d):
    return int(dt.datetime(d.year, d.month, d.day, 12, tzinfo=TZ).timestamp() * 1000) if d else None


# --- Ausencias ------------------------------------------------------------------------------------

def _aus(tipo="vacaciones", estado=AUS.APROBADA, s=L9, d=L9 + dt.timedelta(days=4), asig=("Ana",)):
    def x(v):
        return dt.datetime(v.year, v.month, v.day, 12, tzinfo=TZ)
    return Task("t", "n", None, estado, "L", x(s), x(d), None, tuple(asig), {"Tipo de ausencia": CustomField("1", "Tipo de ausencia", "drop_down", tipo, 0)})


def test_ausencias_solo_aprobadas_y_horas():
    tr = AUS.tramos_de_tareas([_aus(), _aus(estado=AUS.RECHAZADA)])
    assert len(tr) == 1 and tr[0].horas(CAL) == 44
    assert AUS.Tramo("A", AUS.MEDIO_DIA, L9, L9).horas(CAL) == 4.4
    assert AUS.Tramo("A", "vacaciones", D(2026, 12, 7), D(2026, 12, 9)).horas(CAL) == 17.6    # 8-dic feriado


def test_ausencias_por_semana_y_formato_del_informe():
    dias = AUS.dias_por_persona(AUS.tramos_de_tareas([_aus()]) + [AUS.Tramo("Ana", AUS.MEDIO_DIA, L16, L16)], CAL)
    assert dias["Ana"][L16] == ("administrativo", 0.5) and dias["Ana"][L9] == ("vacaciones", 1.0)
    assert AUS.horas_por_semana(dias) == {("Ana", L9): 44.0, ("Ana", L16): 4.4}


def test_tramos_de_planilla_contiguos_sobre_fin_de_semana_y_feriado():
    v = ("vacaciones", 1.0)
    dias = {"Ana": {D(2026, 11, 12): v, D(2026, 11, 13): v, L16: v, D(2026, 11, 18): v, D(2026, 11, 19): ("licencia", 1.0),
                    D(2026, 12, 7): v, D(2026, 12, 9): v, D(2026, 11, 24): ("administrativo", 0.5)}}
    tr = AUS.tramos_de_planilla(dias, CAL)
    assert [(t.tipo, t.inicio, t.fin) for t in tr] == [
        ("vacaciones", D(2026, 11, 12), L16), ("vacaciones", D(2026, 11, 18), D(2026, 11, 18)),
        ("licencia", D(2026, 11, 19), D(2026, 11, 19)), (AUS.MEDIO_DIA, D(2026, 11, 24), D(2026, 11, 24)),
        ("vacaciones", D(2026, 12, 7), D(2026, 12, 9))]


def test_plan_vs_real_filas_de_ausencia_sin_cambiar_encabezados():
    corte = D(2026, 11, 8)
    fs = PVR.filas_ausencia(corte, "oficial", {("Ana", L9): 8.8, ("Ana", D(2027, 3, 1)): 8.8})
    assert len(fs) == 1 and fs[0]["proyecto"] == fs[0]["estado"] == PVR.AUSENCIA and fs[0]["horas_planificadas"] == 8.8
    assert set(fs[0]) == set(PVR.columnas()) - {"es_ultimo_corte"}
    final = PVR.fusionar([], fs, corte, "oficial")
    assert final[0]["es_ultimo_corte"] is True


def test_informe_excluye_adm07_de_asignado_y_registrado():
    e = {"duration": "3600000", "start": ms(L9), "at": ms(L9), "user": {"id": 1, "username": "Ana"}, "task": {"id": "t", "name": "x"},
         "task_location": {"list_id": "A", "list_name": "ADM-07 | Ausencias"}}
    assert IC.normalizar_entradas([e]) == []
    assert not IC.Tareas.desde([{"id": "t", "list": {"name": "ADM-07 | Ausencias"}}]).por_id


def test_iniciales_usa_siglas_aunque_no_tenga_ausencias():
    a = IC.Ausencias({}, {"Pablo Herrera": "PHT"})
    assert IC.iniciales("Pablo Herrera", a) == "PHT"


def test_list_code_reconoce_adm_de_dos_y_tres_digitos():
    assert list_code("ADM-07 | Ausencias") == "ADM-07"
    assert list_code("ADM-006 Elaboración de Propuestas") == "ADM-006"
