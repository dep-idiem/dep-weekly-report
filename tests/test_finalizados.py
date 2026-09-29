"""Proyectos finalizados: situacion por corte, fila de cierre, fusion de cierres, estado_proyecto en la hoja y
procesamiento de una lista del folder Proyectos Finalizados."""
import datetime as dt

from dep_clickup.config import TZ
from dep_clickup.models import CustomField, ListInfo, Task, TimeEntry
from dep_reportes import almacen as A, esquema as E, finalizados as FIN, linea_base as LB, proyecto as P, run
from dep_reportes.calendario import Calendario
from dep_reportes.modos import por_nombre

D = dt.date
C1, C2, C3 = D(2026, 9, 13), D(2026, 9, 20), D(2026, 9, 27)
AHORA = dt.datetime(2026, 9, 28, 4, tzinfo=TZ)


# --- situacion --------------------------------------------------------------------------------------

def test_lista_en_pj_ingenieria_esta_en_curso():
    s = FIN.situacion("L", False, C3, True, {}, {C1, C2})
    assert s == FIN.Situacion() and s.estado == FIN.EN_CURSO and s.emite_semanales and not s.avisar


def test_cambio_de_folder_emite_su_ultima_semana_y_el_cierre():
    s = FIN.situacion("L", True, C3, True, {}, {C1, C2})
    assert s.estado == FIN.FINALIZADO and s.tipo_cierre == FIN.CAMBIO and s.corte_cierre == C3
    assert s.emite_semanales and s.nuevo_cierre and s.avisar and not s.congelado
    assert s.ultimo_corte_en_curso == C2


def test_incorporado_ya_finalizado_no_inventa_semanas():
    s = FIN.situacion("L", True, C3, True, {}, set())
    assert s.tipo_cierre == FIN.INCORPORADO and not s.emite_semanales and s.nuevo_cierre and s.avisar


def test_cierre_de_un_corte_anterior_queda_congelado():
    cierres = {"L": {"list_id": "L", "corte_cierre": C2, "tipo_cierre": FIN.CAMBIO, "ultimo_corte_en_curso": C1}}
    s = FIN.situacion("L", True, C3, True, cierres, {C1})
    assert s.congelado and s.corte_cierre == C2 and not s.emite_semanales and not s.nuevo_cierre and not s.avisar


def test_reprocesar_el_corte_del_cierre_da_lo_mismo():
    # Tras escribir C3, las filas de C3 quedan como finalizado: los cortes en curso siguen siendo C1 y C2.
    metricas = [{"list_id": "L", "corte": C1, "estado_proyecto": None},
                {"list_id": "L", "corte": C2, "estado_proyecto": FIN.EN_CURSO},
                {"list_id": "L", "corte": C3, "estado_proyecto": FIN.FINALIZADO}]
    cierres = {"L": {"list_id": "L", "corte_cierre": C3, "tipo_cierre": FIN.CAMBIO}}
    s = FIN.situacion("L", True, C3, True, cierres, FIN.cortes_en_curso(metricas)["L"])
    assert s == FIN.situacion("L", True, C3, True, {}, {C1, C2})


def test_preliminar_no_escribe_cierre():
    s = FIN.situacion("L", True, C3, False, {}, {C2})
    assert s.finalizado and s.emite_semanales and not s.nuevo_cierre


# --- fila de cierre y fusion ------------------------------------------------------------------------

def test_fila_de_cierre():
    s = FIN.situacion("L", True, C3, True, {}, {C2})
    f = FIN.fila_cierre(list_id="L", ident={"codigo": "PJ-2026.0001", "proyecto": "2026.0001 · X"}, sit=s,
                        metricas={"hh_gastadas_acum": 120.0, "hh_historicas": 20.0, "avance_real": 1.0, "avance_prog": 0.95},
                        presupuesto={"hh_contrato": 150.0}, hh_linea_base=100.0, rev_linea_base=0,
                        fecha_inicio=D(2026, 9, 1), fecha_ultima_hora=D(2026, 9, 18), entrega_linea_base=None,
                        termino_vigente=D(2026, 9, 11), cal=Calendario(), ahora=AHORA)
    assert f["duracion_real_dias_habiles"] == 14 and f["duracion_contractual_dias_habiles"] == 9
    assert f["diferencia_duracion_dias_habiles"] == 5 and f["entrega_contractual_origen"] == "vencimiento_lista"
    assert f["hh_sobre_linea_base"] == 20.0 and f["pct_linea_base_usado"] == 1.2
    assert f["hh_sobre_contrato"] == -30.0 and f["pct_contrato_usado"] == 0.8
    assert f["tipo_cierre"] == FIN.CAMBIO and f["ultimo_corte_en_curso"] == C2 and f["estado_proyecto"] == FIN.FINALIZADO
    assert set(f) == set(E.columnas("cierres"))


def test_fusion_de_cierres():
    viejo = [{"list_id": "A", "corte_cierre": C2}, {"list_id": "B", "corte_cierre": C2}, {"list_id": "R", "corte_cierre": C2}]
    nuevo = [{"list_id": "B", "corte_cierre": C3}, {"list_id": "N", "corte_cierre": C3}]
    out = FIN.fusionar_cierres(viejo, nuevo, en_curso={"R"}, oficial=True)
    assert [(f["list_id"], f["corte_cierre"]) for f in out] == [("A", C2), ("B", C3), ("N", C3)]
    assert FIN.fusionar_cierres(viejo, nuevo, {"R"}, oficial=False) == viejo
    assert A.fusionar("cierres", viejo, nuevo, C3, tipo_corte=E.PRELIMINAR) == viejo


def test_estado_proyecto_se_actualiza_en_todo_el_historial():
    ident = {"L": {"codigo": "PJ-1", "estado_proyecto": FIN.FINALIZADO}}
    filas = [{"corte": C1, "tipo_corte": "oficial", "list_id": "L", "codigo": "PJ-1"},
             {"corte": C2, "tipo_corte": "oficial", "list_id": "L", "codigo": "PJ-1", "estado_proyecto": FIN.EN_CURSO},
             {"corte": C2, "tipo_corte": "oficial", "list_id": "Z", "codigo": "PJ-2"}]
    out = A.completar("metricas_fase", filas, ident)
    assert [f.get("estado_proyecto") for f in out] == [FIN.FINALIZADO, FIN.FINALIZADO, None]
    fotos = A.completar("fotos_tareas", [{"corte": C1, "list_id": "L", "task_id": "t"}], ident)
    assert fotos[0]["estado_proyecto"] == FIN.FINALIZADO
    assert {"estado_proyecto"} <= set(E.columnas("proyectos")) and "fotos_tareas" in E.CON_ESTADO


def test_advertencia_proyecto_finalizado_es_informativa_y_de_proyecto():
    from dep_reportes import presentacion as PR, resolucion as RES
    assert PR.nivel(P.ADV_PROYECTO_FINALIZADO) == "proyecto"
    r = RES.resolver(P.ADV_PROYECTO_FINALIZADO, RES.Contexto(lista="2026.0001 · X"))
    assert r["impacto"] == RES.INFORMATIVA and r["responsable_accion"] == RES.INFORMATIVA
    assert "Proyectos Finalizados" in PR.mensaje(P.ADV_PROYECTO_FINALIZADO, None, {"ultimo_corte_en_curso": C2})


# --- procesar una lista finalizada ------------------------------------------------------------------

def _ms(d):
    return dt.datetime(d.year, d.month, d.day, 9, tzinfo=TZ) if d else None


def _t(id_, nombre, parent=None, hh=None, s=None, d=None, estado="to do", tipo="custom"):
    cf = {"HH Presupuestadas": CustomField("1", "HH Presupuestadas", "number", hh, hh),
          "Avance Real": CustomField("2", "Avance Real", "manual_progress", None, None)}
    return Task(id_, nombre, parent, estado, "L", _ms(s), _ms(d), None, (), cf, status_type=tipo,
                date_created=_ms(D(2026, 8, 1)))


LISTA = ListInfo("L", "PJ-2026.0001 | Proyecto | Cliente", None, False, "901318475416", None, None,
                 start=_ms(D(2026, 9, 1)), due=_ms(D(2026, 9, 11)))
TAREAS = [_t("f1", "01 Planificación"), _t("t12", "1.2 Plan de Trabajo", "f1", estado="completado", tipo="done"),
          _t("f4", "04 Análisis"), _t("p1", "4.1 Modelo", "f4", 60, D(2026, 9, 1), D(2026, 9, 7), "completado", "done"),
          _t("p2", "4.2 Informe", "f4", 40, D(2026, 9, 8), D(2026, 9, 11), "completado", "done")]
ENTRADAS = [TimeEntry(f"e{i}", 1, "x", "p1" if i < 4 else "p2", "", "L", _ms(D(2026, 9, 1) + dt.timedelta(days=i)),
                      None, 10 * 3_600_000) for i in range(6)]


def _procesar(sit, lb_exist=(), corte=C3):
    return run.procesar_lista(LISTA, TAREAS, ENTRADAS, [], corte, por_nombre("dep"), list(lb_exist), False, False,
                              AHORA, "PJ-2026.0001", situacion=sit)


def test_finalizado_no_congela_linea_base_nueva_y_conserva_la_existente():
    r = _procesar(FIN.situacion("L", True, C3, True, {}, set()))
    assert r.lb_nuevas == [] and r.lb_filas == []
    lb = LB.congelar(LISTA, TAREAS, 0, "normal", "Rev. 0", AHORA)
    r = _procesar(FIN.situacion("L", True, C3, True, {}, {C2}), lb)
    assert r.lb_nuevas == [] and sum(f.hh for f in r.lb_filas) == 100


def test_incorporado_solo_proyectos_serie_cierre_y_advertencia():
    r = _procesar(FIN.situacion("L", True, C3, True, {}, set()))
    out = run.filas_de(r, C3, por_nombre("dep"), AHORA)
    assert set(t for t, f in out.items() if f) == {"proyectos", "serie_diaria", "cierres", "advertencias"}
    assert [a["tipo"] for a in out["advertencias"]] == [P.ADV_PROYECTO_FINALIZADO]
    c = out["cierres"][0]
    assert c["tipo_cierre"] == FIN.INCORPORADO and c["hh_gastadas_acum"] == 60 and c["fecha_ultima_hora"] == D(2026, 9, 6)
    assert out["proyectos"][0]["estado_proyecto"] == FIN.FINALIZADO and out["proyectos"][0]["corte_cierre"] == C3


def test_cambio_de_folder_emite_filas_semanales_y_cierre_con_linea_base():
    lb = LB.congelar(LISTA, TAREAS, 0, "normal", "Rev. 0", AHORA)
    r = _procesar(FIN.situacion("L", True, C3, True, {}, {C2}), lb)
    out = run.filas_de(r, C3, por_nombre("dep"), AHORA)
    assert out["metricas_semanales"][0]["estado_proyecto"] == FIN.FINALIZADO
    assert P.ADV_PROYECTO_FINALIZADO in {a["tipo"] for a in out["advertencias"]}
    c = out["cierres"][0]
    assert c["hh_linea_base"] == 100 and c["hh_sobre_linea_base"] == -40 and c["rev_linea_base"] == 0
    assert c["fecha_entrega_contractual"] == D(2026, 9, 11)


def test_ultima_hora_del_cierre_considera_el_timetracker():
    sit = FIN.situacion("L", True, C3, True, {}, set())
    r = run.procesar_lista(LISTA, TAREAS, ENTRADAS, [], C3, por_nombre("dep"), [], False, False, AHORA, "PJ-2026.0001",
                           conteo=run.Conteo(10.0, None, ultima_historica=D(2026, 9, 15)), situacion=sit)
    c = run.filas_de(r, C3, por_nombre("dep"), AHORA)["cierres"][0]
    assert c["fecha_ultima_hora"] == D(2026, 9, 15) and c["hh_gastadas_acum"] == 70 and c["hh_historicas"] == 10


def test_congelado_no_emite_semanales_ni_advertencias():
    cierres = {"L": {"list_id": "L", "corte_cierre": C2, "tipo_cierre": FIN.CAMBIO}}
    sit = FIN.situacion("L", True, C3, True, cierres, {C1})
    r = _procesar(sit, corte=C2)
    out = run.filas_de(r, C2, por_nombre("dep"), AHORA)
    assert set(t for t, f in out.items() if f) == {"proyectos", "serie_diaria"}
    assert out["serie_diaria"][0]["corte"] == C2
