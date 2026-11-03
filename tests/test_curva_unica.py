"""TAREA_curva_programada_unica (2026-11-03): un solo modo de curva S para listas antiguas y v2. Programada desde las
tareas del presupuesto con respaldo al plazo de la lista, Rev. 0 con la primera hora registrada y estados de la curva
(sin presupuesto, presupuesto incoherente, retenida, recurrente)."""
import datetime as dt

from dep_clickup.config import TZ
from dep_clickup.models import ListInfo
from dep_reportes import linea_base as LB, metricas as MT, programada as PROG, reproceso as REP, run
from dep_reportes.calendario import SIN_FERIADOS
from dep_reportes.metricas import TareaMetrica
from dep_reportes.modos import por_nombre

from test_plan_vs_real import _e, _t

D = dt.date
CORTE = D(2026, 11, 1)                                    # domingo
AHORA = dt.datetime(2026, 11, 2, 8, tzinfo=TZ)
DEP = por_nombre("dep")
LISTA = ListInfo("L", "PJ-2026.0177 | Revisión estructural | U. de Los Lagos", "green", False, "F", "S", 9,
                 start=dt.datetime(2026, 10, 5, 4, tzinfo=TZ), due=dt.datetime(2026, 11, 27, 4, tzinfo=TZ))


def tm(id_, hh, s, d):
    return TareaMetrica(id_, id_, None, s, d, hh, None)


# --- programada.programar ----------------------------------------------------------------------------------------

def test_tareas_con_fechas_validas_se_reparten_con_sus_fechas():
    p = PROG.programar([tm("a", 10, D(2026, 10, 5), D(2026, 10, 9)), tm("b", 20, D(2026, 10, 12), D(2026, 10, 30))],
                       D(2026, 10, 5), D(2026, 11, 27), SIN_FERIADOS)
    assert p.modo == PROG.TAREAS and p.respaldo == [] and p.presupuesto == 30
    assert [(t.start, t.due) for t in p.tareas] == [(D(2026, 10, 5), D(2026, 10, 9)), (D(2026, 10, 12), D(2026, 10, 30))]


def test_respaldo_al_plazo_de_la_lista_por_cada_motivo():
    ini, fin = D(2026, 10, 5), D(2026, 11, 27)
    casos = {
        "sin fechas": tm("a", 8, None, None),
        "sin fecha de inicio": tm("b", 8, None, D(2026, 10, 9)),
        "sin fecha de término": tm("c", 8, D(2026, 10, 9), None),
        "inicio 20-10-2026 posterior al término 10-10-2026": tm("d", 8, D(2026, 10, 20), D(2026, 10, 10)),
        "inicio 01-08-2026 anterior al inicio de la lista 05-10-2026 (65 días)": tm("e", 8, D(2026, 8, 1), D(2026, 10, 9)),
        "inicio 04-09-2026 anterior al inicio de la lista 05-10-2026 (31 días)": tm("e31", 8, D(2026, 9, 4), D(2026, 10, 9)),
        "término 15-12-2026 posterior al término de la lista 27-11-2026": tm("f", 8, D(2026, 10, 9), D(2026, 12, 15)),
        "sin días hábiles entre 10-10-2026 y 11-10-2026": tm("g", 8, D(2026, 10, 10), D(2026, 10, 11)),   # sáb-dom
    }
    p = PROG.programar(list(casos.values()) + [tm("ok", 8, D(2026, 10, 5), D(2026, 10, 9))], ini, fin, SIN_FERIADOS)
    assert p.modo == PROG.MIXTA
    assert {x.task_id: x.motivo for x in p.respaldo} == {t.id: m for m, t in casos.items()}
    por_id = {t.id: t for t in p.tareas}
    assert all((por_id[t.id].start, por_id[t.id].due) == (ini, fin) for t in casos.values())
    assert (por_id["ok"].start, por_id["ok"].due) == (D(2026, 10, 5), D(2026, 10, 9))


def test_inicio_hasta_30_dias_antes_de_la_lista_usa_sus_fechas():
    ini, fin = D(2026, 10, 26), D(2026, 12, 3)
    p = PROG.programar([tm("a", 79, D(2026, 10, 15), D(2026, 11, 26)),        # 11 días antes
                        tm("b", 23, D(2026, 9, 26), D(2026, 10, 16)),          # 30 días: límite, y termina antes
                        tm("c", 10, D(2026, 9, 25), D(2026, 10, 30)),          # 31 días: respaldo
                        tm("d", 5, D(2026, 10, 20), D(2026, 12, 4))], ini, fin, SIN_FERIADOS)   # término: estricto
    assert {x.task_id for x in p.respaldo} == {"c", "d"} and p.modo == PROG.MIXTA
    assert [(x.task_id, x.dias) for x in p.anticipadas] == [("a", 11), ("b", 30)]
    por_id = {t.id: t for t in p.tareas}
    assert (por_id["a"].start, por_id["a"].due) == (D(2026, 10, 15), D(2026, 11, 26))
    assert (por_id["b"].start, por_id["b"].due) == (D(2026, 9, 26), D(2026, 10, 16))
    assert p.inicio_ventana == D(2026, 9, 26) and p.inicio == ini
    # «d» empieza antes, pero cae al respaldo por el término: no es anticipada
    assert PROG.programar([tm("d", 5, D(2026, 10, 20), D(2026, 12, 4))], ini, fin, SIN_FERIADOS).anticipadas == []


def test_advertencia_informativa_de_inicio_anterior():
    ts = [_t("f", "05 Ingeniería"), _t("a", "5.1 Revisión", "f", hh=20, s=D(2026, 9, 28), d=D(2026, 10, 16))]
    r = _procesar(ts)
    assert r.programada.modo == PROG.TAREAS and r.programada.respaldo == []
    adv = [a for a in r.advertencias if a["tipo"] == "inicio_anterior_contractual"]
    assert len(adv) == 1 and adv[0]["prioridad"] == "baja" and adv[0]["responsable_accion"] == "Informativa"
    assert adv[0]["mensaje"].startswith("«5.1 Revisión» empieza 7 días antes del inicio de la lista (05-10-2026)")
    assert not [a for a in r.advertencias if a["tipo"] == "fechas_fuera_de_lista"]
    assert r.resultado.serie[0].fecha == D(2026, 9, 28)                     # la ventana parte en ese inicio


def test_todas_al_respaldo_es_lineal_entre_inicio_y_termino_de_la_lista():
    ini, fin = D(2026, 10, 5), D(2026, 10, 16)               # 10 días hábiles
    p = PROG.programar([tm("a", 30, None, None), tm("b", 70, D(2026, 1, 1), D(2026, 1, 9))], ini, fin, SIN_FERIADOS)
    assert p.modo == PROG.LINEAL
    diario = MT.hh_programadas_diarias(p.tareas, SIN_FERIADOS)
    assert set(round(v, 9) for v in diario.values()) == {10.0} and sum(diario.values()) == 100


def test_sin_fechas_de_lista_el_respaldo_usa_las_tareas_con_fechas_propias():
    p = PROG.programar([tm("a", 10, D(2026, 10, 5), D(2026, 10, 9)), tm("b", 10, None, None)], None, None, SIN_FERIADOS)
    assert p.modo == PROG.MIXTA and [(t.start, t.due) for t in p.tareas][1] == (D(2026, 10, 5), D(2026, 10, 9))
    solo = PROG.programar([tm("b", 10, None, None)], None, None, SIN_FERIADOS)
    assert solo.modo == PROG.LINEAL and (solo.tareas[0].start, solo.tareas[0].due) == (None, None)   # sin con qué


def test_sin_presupuesto_no_hay_programada():
    p = PROG.programar([tm("a", None, D(2026, 10, 5), D(2026, 10, 9))], D(2026, 10, 5), D(2026, 11, 27), SIN_FERIADOS)
    assert p.modo is None and p.tareas == [] and p.presupuesto == 0


def test_estado_de_la_curva():
    assert PROG.estado(0, 0, False, False, False) == PROG.SIN_PRESUPUESTO
    assert PROG.estado(22, 409, False, False, False) == PROG.INCOHERENTE
    assert PROG.estado(22, 409, True, False, False) == PROG.OK                # con Rev. 0 el exceso es desvío
    assert PROG.estado(100, 10, False, True, False) == PROG.RETENIDA
    assert PROG.estado(100, 10, True, True, False) == PROG.OK                 # retenida que ya tenía Rev. 0
    assert PROG.estado(0, 409, False, True, True) == PROG.RECURRENTE
    assert PROG.estado(100, 10, False, False, False) == PROG.OK


# --- Línea base: la programada se reconstruye con el plazo guardado -------------------------------------------

def test_programada_de_la_linea_base_usa_el_plazo_guardado_al_congelar():
    filas = [LB.FilaLB("L", 0, "normal", AHORA, "m", D(2026, 10, 5), D(2026, 11, 27), tid, tid, "05", hh, s, d)
             for tid, hh, s, d in (("a", 10.0, D(2026, 10, 5), D(2026, 10, 9)), ("b", 20.0, D(2025, 3, 1), D(2025, 3, 7)))]
    p = LB.programada(filas, SIN_FERIADOS)
    assert p.modo == PROG.MIXTA and [x.task_id for x in p.respaldo] == ["b"]
    assert (p.tareas[1].start, p.tareas[1].due) == (D(2026, 10, 5), D(2026, 11, 27))


# --- procesar_lista ----------------------------------------------------------------------------------------------

def _tareas(hh_b=30):
    return [_t("f", "05 Ingeniería"),
            _t("a", "5.1 Revisión", "f", hh=20, s=D(2026, 10, 5), d=D(2026, 10, 16)),
            _t("b", "5.2 Informe", "f", hh=hh_b, s=D(2025, 12, 1), d=D(2025, 12, 5)),   # fechas de plantilla
            _t("c", "Porción", "f", s=D(2026, 10, 19), d=D(2026, 10, 23), te_h=8, asignados=("Ana",))]


def _procesar(tareas, entradas=(), lb=(), retenidas=None, recurrente=False, lista=LISTA):
    return run.procesar_lista(lista, tareas, list(entradas), [], CORTE, DEP, list(lb), True, False, AHORA,
                              retenidas=retenidas, recurrente=recurrente)


def test_respaldo_mixta_con_advertencia_por_tarea_y_columnas_en_la_hoja():
    r = _procesar(_tareas(), [_e("1", "a", "Ana", D(2026, 10, 27), 4)])
    assert r.estado_curva == PROG.OK and r.programada.modo == PROG.MIXTA
    assert [x.task_id for x in r.programada.respaldo] == ["b"]
    adv = [a for a in r.advertencias if a["tipo"] == "fechas_fuera_de_lista"]
    assert len(adv) == 1 and adv[0]["task_id"] == "b" and adv[0]["responsable_accion"] == "JP"
    assert "anterior al inicio de la lista 05-10-2026" in adv[0]["mensaje"]
    # Rev. 0 con la primera hora registrada, guarda las fechas de ClickUp y el plazo de la lista
    assert {f.task_id: (f.start, f.due) for f in r.lb_nuevas} == {"a": (D(2026, 10, 5), D(2026, 10, 16)),
                                                                   "b": (D(2025, 12, 1), D(2025, 12, 5))}
    assert {(f.fecha_inicio, f.fecha_entrega_contractual) for f in r.lb_nuevas} == {(D(2026, 10, 5), D(2026, 11, 27))}
    fs = run.filas_de(r, CORTE, DEP, AHORA)
    for t in ("proyectos", "metricas_semanales"):
        assert (fs[t][0]["estado_curva"], fs[t][0]["programada_modo"]) == ("ok", "mixta")
    m = r.resultado.metricas
    # «a» completa (20) más la parte de «b» (30 HH repartidas en todo el plazo de la lista) hasta el corte
    assert m["total_hh"] == 50 and 20 < m["hh_prog_acum"] < 50


def test_la_porcion_sola_no_congela_y_sin_horas_es_provisional():
    r = _procesar(_tareas())
    assert r.lb_nuevas == [] and run.provisional(r) and r.programada.modo == PROG.MIXTA


def test_sin_presupuesto_sin_programada_ni_linea_base_y_aviso_al_jp():
    ts = [_t("f", "05 Ingeniería"), _t("a", "5.1 Revisión", "f", s=D(2026, 10, 5), d=D(2026, 10, 16))]
    r = _procesar(ts, [_e("1", "a", "Ana", D(2026, 10, 27), 4)])
    assert r.estado_curva == PROG.SIN_PRESUPUESTO and r.lb_nuevas == [] and not run.provisional(r)
    assert r.programada is None and r.resultado.metricas["hh_prog_acum"] is None
    adv = next(a for a in r.advertencias if a["tipo"] == "proyecto_sin_presupuesto")
    assert adv["responsable_accion"] == "JP" and adv["prioridad"] == "alta"
    fs = run.filas_de(r, CORTE, DEP, AHORA)
    ms = fs["metricas_semanales"][0]
    assert ms["estado_curva"] == "sin_presupuesto" and ms["programada_modo"] is None
    assert ms["titular"].startswith("Sin curva programada: no hay tareas con HH Presupuestadas")
    assert not any(f["hh_prog_acum"] for f in fs["serie_diaria"])


def test_presupuesto_incoherente_no_congela():
    r = _procesar(_tareas(hh_b=2), [_e("1", "a", "Ana", D(2026, 10, 27), 30)])       # 30 h frente a 22 HH
    assert r.estado_curva == PROG.INCOHERENTE and r.lb_nuevas == [] and r.programada is None
    adv = next(a for a in r.advertencias if a["tipo"] == "presupuesto_incoherente")
    assert adv["mensaje"].startswith("Las horas registradas (30,0 h) superan el presupuesto (22,0 HH)")
    # con Rev. 0 ya congelada, el exceso es desvío
    lb = LB.congelar(LISTA, _tareas(hh_b=2), 0, "normal", "Rev. 0", AHORA)
    r = _procesar(_tareas(hh_b=2), [_e("1", "a", "Ana", D(2026, 10, 27), 30)], lb)
    assert r.estado_curva == PROG.OK and r.lb_filas


def test_retenida_calcula_todo_pero_no_congela():
    r = _procesar(_tareas(), [_e("1", "a", "Ana", D(2026, 10, 27), 4)], retenidas={"L": "lista de pruebas"})
    assert r.estado_curva == PROG.RETENIDA and r.lb_nuevas == [] and run.provisional(r)
    assert r.resultado.metricas["hh_prog_acum"] > 0


def test_recurrente_fuera_de_la_curva_aunque_tenga_linea_base():
    lb = LB.congelar(LISTA, _tareas(), 0, "tardia", "Rev. 0", AHORA)
    r = _procesar(_tareas(), [_e("1", "a", "Ana", D(2026, 10, 27), 4)], lb, recurrente=True)
    assert r.estado_curva == PROG.RECURRENTE and r.lb_nuevas == [] and r.lb_filas == [] and r.programada is None
    assert r.resultado.metricas["hh_prog_acum"] is None
    r = _procesar(_tareas(), [_e("1", "a", "Ana", D(2026, 10, 27), 4)], recurrente=True)
    assert r.lb_nuevas == [] and not run.provisional(r)


def test_tarea_nueva_despues_de_la_rev0_no_cambia_la_programada():
    lb = LB.congelar(LISTA, _tareas(), 0, "normal", "Rev. 0", AHORA)
    extra = _t("n", "5.3 Adicional", "f", hh=40, s=D(2026, 11, 2), d=D(2026, 11, 13))
    r = _procesar(_tareas() + [extra], [_e("1", "a", "Ana", D(2026, 10, 27), 4)], lb)
    assert r.lb_nuevas == [] and r.resultado.metricas["total_hh"] == 50
    assert r.resultado.metricas["hh_actuales_clickup"] == 90


def test_reproceso_usa_la_misma_programada_que_la_corrida():
    lb = LB.congelar(LISTA, _tareas(), 0, "normal", "Rev. 0", AHORA)
    r = _procesar(_tareas(), [_e("1", "a", "Ana", D(2026, 10, 27), 4)], lb)
    fs = run.filas_de(r, CORTE, DEP, AHORA)
    nueva, _ = REP.recalcular(CORTE, fs["metricas_semanales"][0], fs["fotos_tareas"], lb, DEP)
    assert nueva["hh_prog_acum"] == r.resultado.metricas["hh_prog_acum"]
    assert nueva["avance_prog"] == r.resultado.metricas["avance_prog"]


# --- proyectos.ritmo_real y semanas_desfase ----------------------------------------------------------------------

def test_ritmo_real_promedia_las_dos_ultimas_semanas_cerradas():
    from dep_reportes import presupuesto as PRES
    from dep_reportes.metricas import Horas
    horas = [Horas(D(2026, 10, 12), 10), Horas(D(2026, 10, 19), 6), Horas(D(2026, 10, 25), 4),   # semana 19-25
             Horas(D(2026, 10, 26), 20), Horas(D(2026, 11, 1), 10), Horas(D(2026, 11, 3), 99)]
    assert PRES.ritmo_real(horas, D(2026, 11, 1)) == (10 + 30) / 2      # domingo: su semana ya está cerrada
    assert PRES.ritmo_real(horas, D(2026, 11, 3)) == (10 + 30) / 2      # martes: la semana en curso no cuenta
    assert PRES.ritmo_real(horas, D(2026, 10, 31)) == (10 + 10) / 2     # sábado: cuentan 12-18 y 19-25
    assert PRES.ritmo_real([], D(2026, 11, 1)) == 0


def test_semanas_desfase():
    from dep_reportes import presentacion as PR
    corte, fin = D(2026, 11, 1), D(2026, 11, 13)                      # 10 días hábiles = 2 semanas
    assert PR.semanas_desfase(60, 20, corte, fin, SIN_FERIADOS) == 1.0   # 3 semanas al ritmo, quedan 2
    assert PR.semanas_desfase(20, 20, corte, fin, SIN_FERIADOS) == -1.0  # sobra una semana
    assert PR.semanas_desfase(60, 0, corte, fin, SIN_FERIADOS) is None   # sin ritmo
    assert PR.semanas_desfase(60, 20, corte, None, SIN_FERIADOS) is None
    assert PR.semanas_desfase(10, 10, corte, D(2026, 10, 26), SIN_FERIADOS) == 1 + 5 / 5   # vencido hace 5 hábiles


def test_ritmo_y_desfase_en_proyectos():
    entradas = [_e("1", "a", "Ana", D(2026, 10, 20), 8), _e("2", "a", "Ana", D(2026, 10, 27), 12)]
    r = _procesar(_tareas(), entradas)
    p = run.filas_de(r, CORTE, DEP, AHORA)["proyectos"][0]
    assert p["ritmo_real"] == 10
    pend = r.resultado.metricas["hh_pendientes"]
    assert pend == 50                                                # sin avance real: todo el presupuesto
    habiles = DEP.cal.networkdays(D(2026, 11, 2), D(2026, 11, 27))
    assert p["semanas_desfase"] == pend / 10 - habiles / 5
    sin = run.filas_de(_procesar([_t("f", "05 Ingeniería")], entradas), CORTE, DEP, AHORA)["proyectos"][0]
    assert sin["ritmo_real"] == 10 and sin["semanas_desfase"] is None    # sin presupuesto: sin desfase
