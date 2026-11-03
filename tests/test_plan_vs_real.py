"""TAREA_reportes_plan_vs_real (decisiones de Ale del 2026-11-02): presupuesto sin ancestros con HH, regla C del plan
semanal, plan vs real por persona, horas de la tarea SS, fechas heredadas y fecha contractual."""
import datetime as dt

from dep_clickup.config import TZ
from dep_clickup.models import CustomField, ListInfo, Task, TimeEntry
from dep_reportes import plan_semanal as PS, plan_vs_real as PVR, run
from dep_reportes.adaptador_clickup import a_tareas_metrica, con_ancestro_con_hh
from dep_reportes.calendario import Calendario
from dep_reportes.modos import por_nombre

D = dt.date
CAL = Calendario(frozenset({D(2026, 10, 12)}))           # feriado lunes 12-oct
CORTE = D(2026, 11, 1)                                    # domingo
AHORA = dt.datetime(2026, 11, 2, 8, tzinfo=TZ)


def _ms(d):
    return dt.datetime(d.year, d.month, d.day, 4, tzinfo=TZ) if d else None


def _t(id_, nombre, parent=None, hh=None, s=None, d=None, te_h=None, asignados=(), estado="to do", tipo="open",
       creada=D(2026, 10, 14)):
    cf = {"HH Presupuestadas": CustomField("1", "HH Presupuestadas", "number", hh, hh)} if hh else {}
    return Task(id_, nombre, parent, estado, "L", _ms(s), _ms(d), int(te_h * 3_600_000) if te_h else None,
                tuple(asignados), cf, status_type=tipo, date_created=_ms(creada))


def _e(id_, tarea, persona, d, h, lista="L", nombre_tarea="x"):
    st = dt.datetime(d.year, d.month, d.day, 9, tzinfo=TZ)
    return TimeEntry(id_, 1, persona, tarea, nombre_tarea, lista, st, st + dt.timedelta(hours=h), int(h * 3_600_000))


# --- Presupuesto: solo tareas sin ancestro con HH --------------------------------------------------------------

def test_hh_de_tareas_con_ancestro_con_hh_no_suman():
    ts = [_t("f", "05 Ingeniería"), _t("p", "5.1 Paquete", "f", hh=100), _t("h", "Porción", "p", hh=40),
          _t("n", "Nieta", "h", hh=5), _t("q", "5.2 Otro", "f", hh=30), _t("a", "00 Administración", hh=744),
          _t("x", "Hija de admin", "a", hh=3)]
    assert con_ancestro_con_hh(ts, v2=False) == {"h", "n"}           # 00 Administración no cuenta como ancestro
    tm = {t.id: t.hh for t in a_tareas_metrica(ts)}
    assert (tm["p"], tm["h"], tm["n"], tm["q"], tm["x"]) == (100, None, None, 30, 3)
    crudo = {t.id: t.hh for t in a_tareas_metrica(ts, solo_superiores=False)}
    assert crudo["h"] == 40                                           # el detector sigue viendo el doble conteo


# --- Regla C ---------------------------------------------------------------------------------------------------

def test_plan_regla_c_prorrateo_feriados_y_exclusiones():
    ts = [_t("f", "05 Ingeniería"),
          # 4 hábiles: jue 8, vie 9, (lun 12 feriado), mar 13, mié 14 -> 2 en la semana del 05-oct, 2 en la del 12-oct
          _t("a", "Modelo", "f", s=D(2026, 10, 8), d=D(2026, 10, 14), te_h=40, asignados=("Ana",)),
          # sin start: entera en la semana del due
          _t("b", "Revisión", "f", d=D(2026, 10, 21), te_h=6, asignados=("Ana", "Luis")),
          # padre con hija estimada: no cuenta; la hija sí
          _t("c", "Paquete", "f", s=D(2026, 10, 19), d=D(2026, 10, 30), te_h=99, asignados=("Luis",)),
          _t("c1", "Porción", "c", s=D(2026, 10, 19), d=D(2026, 10, 19), te_h=8, asignados=("Luis",)),
          # sin responsable: va a «(sin responsable)», no al total
          _t("d", "Sin asignar", "f", s=D(2026, 10, 26), d=D(2026, 10, 26), te_h=5),
          # No Aplica y sin fechas: fuera
          _t("e", "NA", "f", s=D(2026, 10, 26), d=D(2026, 10, 26), te_h=7, asignados=("Ana",), estado="no aplica"),
          _t("g", "Sin fechas", "f", te_h=7, asignados=("Ana",))]
    plan = PVR.plan_por_persona(ts, CAL)
    assert plan[("Ana", D(2026, 10, 5))] == 20 and plan[("Ana", D(2026, 10, 12))] == 20
    assert plan[("Ana", D(2026, 10, 19))] == 3 and plan[("Luis", D(2026, 10, 19))] == 3 + 8
    assert plan[(PVR.SIN_RESPONSABLE, D(2026, 10, 26))] == 5
    assert ("Ana", D(2026, 10, 26)) not in plan
    tot = PVR.plan_semanal_total(plan)
    assert tot == {D(2026, 10, 5): 20, D(2026, 10, 12): 20, D(2026, 10, 19): 14}


def test_plan_semanal_usa_regla_c_y_columna_ss():
    from dep_reportes.metricas import Horas
    fs = PS.filas({D(2026, 10, 26): 240.0}, [Horas(D(2026, 10, 27), 100, "x")], CORTE, [Horas(D(2026, 10, 28), 6, "ss")])
    f = next(x for x in fs if x["semana"] == D(2026, 10, 26))
    assert (f["hh_planificadas"], f["hh_registradas"], f["hh_registradas_ss"]) == (240.0, 100, 6)
    assert next(x for x in fs if x["semana"] == D(2026, 11, 2))["hh_registradas_ss"] is None


# --- Plan vs real por persona ----------------------------------------------------------------------------------

def test_estados():
    s = D(2026, 10, 26)
    assert PVR.estado(s, CORTE, 10, 8) == PVR.OK
    assert PVR.estado(s, CORTE, 10, 5) == PVR.PARCIAL
    assert PVR.estado(s, CORTE, 10, 4.9) == PVR.SIN_REGISTRO
    assert PVR.estado(s, CORTE, 0, 3) == PVR.SIN_PLAN
    assert PVR.estado(D(2026, 11, 2), CORTE, 10, 0) == PVR.FUTURO


def test_filas_ventana_personas_ss_y_necesarias():
    plan = {("Ana", D(2026, 10, 26)): 10.0, ("Ana", D(2026, 11, 2)): 8.0, ("Luis", D(2026, 10, 26)): 10.0}
    regs = (PVR.registros([_e("1", "t", "Ana", D(2026, 10, 27), 9), _e("2", "t", "Pedro", D(2026, 10, 28), 4),
                           _e("3", "t", "Ana", D(2026, 9, 1), 5)], PVR.ORIGEN_PJ)       # fuera de la ventana
            + PVR.registros([_e("4", "ss", "Luis", D(2026, 10, 29), 2)], PVR.ORIGEN_SS))
    fs = PVR.filas(CORTE, "oficial", "L", "2026.0225", "Correa", "Sebastián", plan, regs, {D(2026, 11, 2): 50.0})
    assert PVR.semanas(CORTE)[0] == D(2026, 10, 5) and PVR.semanas(CORTE)[-1] == D(2026, 12, 7)
    por = {(f["semana_inicio"], f["persona"]): f for f in fs}
    a = por[(D(2026, 10, 26), "Ana")]
    assert (a["fecha_corte"], a["horas_registradas"], a["cumplimiento"], a["estado"]) == (D(2026, 11, 2), 9, 0.9, "ok")
    l = por[(D(2026, 10, 26), "Luis")]
    assert (l["horas_registradas"], l["horas_registradas_ss"], l["estado"]) == (0, 2, "sin_registro")
    assert por[(D(2026, 10, 26), "Pedro")]["estado"] == "sin_plan"
    fut = por[(D(2026, 11, 2), "Ana")]
    assert (fut["horas_registradas"], fut["cumplimiento"], fut["estado"]) == (None, None, "futuro")
    p = por[(D(2026, 11, 2), PVR.PROYECTO)]
    assert p["horas_necesarias_semana"] == 50 and p["horas_planificadas"] is None
    assert not any(f["semana_inicio"] < D(2026, 10, 5) for f in fs)


def test_necesarias_por_semana():
    cs = [PVR.Cajon("a", 100, D(2026, 11, 20), 40, False),     # 60 en 3 semanas: 02, 09 y 16-nov
          PVR.Cajon("b", 10, D(2026, 10, 15), 2, False),       # término pasado: todo a la primera semana
          PVR.Cajon("c", 50, D(2026, 11, 20), 60, False),      # sobregastado: 0
          PVR.Cajon("d", 30, D(2026, 11, 20), 0, True),        # cerrado
          PVR.Cajon("e", 30, None, 0, False)]                  # sin término
    n = PVR.necesarias_por_semana(cs, CORTE)
    assert n == {D(2026, 11, 2): 28.0, D(2026, 11, 9): 20.0, D(2026, 11, 16): 20.0}


def test_fusionar_guarda_cada_corte():
    f = lambda c, t: {"corte": c, "tipo_corte": t, "list_id": "L", "persona": "Ana"}
    viejas = [f(D(2026, 10, 25), "oficial"), f(D(2026, 10, 28), "preliminar")]
    out = PVR.fusionar(viejas, [f(CORTE, "oficial")], CORTE, "oficial")
    assert [(x["corte"], x["tipo_corte"], x["es_ultimo_corte"]) for x in out] == [
        (D(2026, 10, 25), "oficial", False), (CORTE, "oficial", True)]
    # repetir el corte oficial reemplaza solo ese corte
    assert len(PVR.fusionar(out, [f(CORTE, "oficial")], CORTE, "oficial")) == 2


# --- procesar_lista: fechas heredadas, contractual, SS, retenida -----------------------------------------------

LISTA = ListInfo("L", "PJ-2026.0225 | Correa 2741 | CMP", "green", False, "F", "S", 9,
                 start=dt.datetime(2026, 10, 15, 4, tzinfo=TZ), due=dt.datetime(2026, 12, 13, 4, tzinfo=TZ))


def _correa():
    return [_t("f0", "00 Administración", s=D(2026, 8, 21), d=D(2026, 8, 26)),
            _t("f3", "03 Antecedentes"), _t("t32", "3.2 Revisión de Documentos", "f3", d=D(2026, 8, 3)),
            _t("f5", "05 Ingeniería"),
            _t("p1", "Desarrollo Informe", "f5", hh=17, s=D(2026, 10, 19), d=D(2026, 10, 23), te_h=17,
               asignados=("Luciano",), estado="completado", tipo="done"),
            _t("p2", "Desarrollo Informe", "f5", hh=34, s=D(2026, 11, 2), d=D(2026, 11, 6), te_h=34,
               asignados=("Luciano",))]


def _procesar(tareas, entradas=(), ss=(), retenidas=None, lista=LISTA):
    return run.procesar_lista(lista, tareas, list(entradas), [], CORTE, por_nombre("dep"), [], True, False, AHORA,
                              entradas_ss=list(ss), retenidas=retenidas)


def test_fechas_heredadas_no_son_atraso_y_van_a_una_advertencia():
    r = _procesar(_correa(), [_e("1", "p1", "Luciano", D(2026, 10, 14), 4)])
    adv = [a for a in r.advertencias if a["tipo"] == "fechas_anteriores_al_inicio"]
    assert len(adv) == 1 and adv[0]["mensaje"].startswith("2 tarea(s) con fechas anteriores al inicio del proyecto "
                                                            "(14-10-2026)")
    assert set(r.heredadas) == {"f0", "t32"}
    fotos = {f["task_id"]: f for f in run.filas_de(r, CORTE, por_nombre("dep"), AHORA)["fotos_tareas"]}
    assert fotos["t32"]["dias_atraso"] is None and fotos["f0"]["dias_atraso"] is None


def test_contractual_es_el_vencimiento_de_la_lista_sin_linea_base():
    r = _procesar(_correa(), retenidas={"L": "presupuesto por confirmar"})
    fs = run.filas_de(r, CORTE, por_nombre("dep"), AHORA)
    ms = fs["metricas_semanales"][0]
    assert ms["fecha_entrega_contractual"] == D(2026, 12, 13) and ms["entrega_texto"] == "13-12-2026"
    assert fs["proyectos"][0]["fecha_entrega_contractual"] == D(2026, 12, 13)
    sin_fecha = ListInfo("L", LISTA.name, "green", False, "F", "S", 9, start=LISTA.start)
    ms = run.filas_de(_procesar(_correa(), lista=sin_fecha), CORTE, por_nombre("dep"), AHORA)["metricas_semanales"][0]
    assert ms["entrega_texto"] == "lista sin fecha de término" and ms["dias_habiles_para_entrega"] is None


def test_retenida_queda_provisional_aunque_haya_horas():
    r = _procesar(_correa(), [_e("1", "p1", "Luciano", D(2026, 10, 20), 4)], retenidas={"L": "presupuesto por confirmar"})
    assert not r.lb_nuevas and run.provisional(r)
    ms = run.filas_de(r, CORTE, por_nombre("dep"), AHORA)["metricas_semanales"][0]
    assert ms["titular"].startswith("Programado provisional (línea base retenida: presupuesto por confirmar). ")
    assert "linea_base_retenida" in {a["tipo"] for a in r.advertencias}
    assert "en_planificacion" not in {a["tipo"] for a in r.advertencias_todas}


def test_lista_antigua_con_horas_congela_tardia_y_el_titular_lo_dice():
    r = _procesar(_correa(), [_e("1", "p1", "Luciano", D(2026, 10, 20), 4)])
    assert {f.tipo for f in r.lb_nuevas} == {"tardia"} and {f.task_id for f in r.lb_nuevas} == {"p1", "p2"}
    ms = run.filas_de(r, CORTE, por_nombre("dep"), AHORA)["metricas_semanales"][0]
    assert ms["titular"].startswith("Línea base Rev. 0 congelada en este corte (tardía, con el plan de hoy; "
                                    "primera porción creada «Desarrollo Informe» el 14-10-2026). ")


def test_horas_ss_aparte_con_advertencia_fuera_de_la_curva():
    ss = [_e("9", "ss", "Sebastián", D(2026, 10, 21), 4.8, lista="SSR", nombre_tarea="2026.0225 | Correa")]
    r = _procesar(_correa(), [_e("1", "p1", "Luciano", D(2026, 10, 20), 4)], ss, retenidas={"L": "x"})
    assert r.resultado.metricas["hh_gastadas_acum"] == 4                        # la SS no entra a la curva
    assert next(a for a in r.advertencias if a["tipo"] == "horas_en_tarea_ss")["mensaje"].startswith("4,8 h registradas")
    sem = next(f for f in r.plan_semanal if f["semana"] == D(2026, 10, 19))
    assert (sem["hh_registradas"], sem["hh_registradas_ss"]) == (4, 4.8)
    seb = next(f for f in r.plan_vs_real if f["persona"] == "Sebastián")
    assert (seb["horas_registradas"], seb["horas_registradas_ss"], seb["estado"]) == (0, 4.8, None)


def test_codigo_ss():
    assert run.CODIGO_SS.match("2026.0225 | Ing. Detalles").group(1) == "2026.0225"
    assert run.CODIGO_SS.match("SS sin código") is None
