"""Reportes sobre listas con estructura v2 (cajones; dep_reportes/v2.py, reportes/auditoria_v2.md)."""
import datetime as dt

from dep_clickup.client import parse_task
from dep_clickup.config import TZ
from dep_clickup.models import CustomField, ListInfo, Task, TimeEntry
from dep_reportes import estructura as EST, horas as H, linea_base as LB, presentacion as PR, presupuesto as PRES
from dep_reportes import resolucion as RES, run, v2 as V2
from dep_reportes.adaptador_clickup import a_tareas_metrica
from dep_reportes.metricas import Horas
from dep_reportes.modos import por_nombre

D = dt.date
CORTE = D(2026, 11, 8)
AHORA = dt.datetime(2026, 11, 8, 23, 0, tzinfo=TZ)


def _ms(d):
    return dt.datetime(d.year, d.month, d.day, 9, tzinfo=TZ) if d else None


def _t(id_, nombre, parent=None, hh=None, s=None, d=None, estado="to do", tipo="custom", avance=None,
       te=None, asignados=(), tags=(), creada=D(2026, 11, 2)):
    cf = {"HH Presupuestadas": CustomField("1", "HH Presupuestadas", "number", hh, hh),
          "Avance Real": CustomField("2", "Avance Real", "manual_progress", avance, avance)}
    return Task(id_, nombre, parent, estado, "L", _ms(s), _ms(d), te, tuple(asignados), cf, status_type=tipo,
                date_created=_ms(creada), tags=tuple(tags))


def _v2(*extra, admin="00 Administración y cierre", tags=()):
    return [_t("a0", admin, hh=9, s=D(2026, 11, 2), d=D(2026, 12, 14), tags=tags),
            _t("c6", "06 Análisis", hh=100, s=D(2026, 11, 4), d=D(2026, 12, 3)),
            _t("c7", "07 Informe", hh=20, s=D(2026, 12, 4), d=D(2026, 12, 9)),
            _t("h1", "◆ Entrega informe", d=D(2026, 12, 14)), *extra]


ANTIGUA = [_t("a0", "00 Administración", hh=300), _t("f1", "01 Planificación"),
           _t("f6", "06 Análisis"), _t("p1", "6.1 Modelo", "f6", 100, D(2026, 11, 4), D(2026, 11, 20)),
           _t("f9", "09 Review", hh=10, s=D(2026, 11, 23), d=D(2026, 11, 27))]


def _h(tarea, d, horas):
    return Horas(d, horas, tarea)


# --- Detección ------------------------------------------------------------------------------------

def test_deteccion_por_nombre_o_por_tag():
    assert V2.es_v2(_v2())
    assert V2.es_v2(_v2(admin="00  ADMINISTRACIÓN y cierre"))
    assert V2.es_v2(_v2(admin="00 Gestión", tags=("v2",)))
    assert not V2.es_v2(ANTIGUA)
    assert not V2.es_v2([_t("x", "6.1 Algo", "f", tags=("v2",))])        # el tag cuenta solo en primer nivel


def test_parse_task_lee_tags():
    t = parse_task({"id": "1", "name": "00 Administración y cierre", "tags": [{"name": "v2", "tag_fg": "#fff"}]})
    assert t.tags == ("v2",)
    assert parse_task({"id": "2", "name": "x"}).tags == ()


# --- Cambio 1: presupuesto y universo -------------------------------------------------------------

def test_presupuesto_v2_es_la_suma_de_los_cajones():
    assert PRES.hh_contrato(_v2()) == 129
    assert PRES.hh_contrato(_v2(), manual=500) == 500                      # config/presupuestos.json manda
    assert PRES.hh_contrato(ANTIGUA) == 300                                 # lista antigua: sin cambios


def test_00_administracion_y_cierre_entra_a_la_curva():
    hh = {t.id: t.hh for t in a_tareas_metrica(_v2())}
    assert hh["a0"] == 9 and hh["c6"] == 100
    assert {t.id: t.hh for t in a_tareas_metrica(ANTIGUA)}["a0"] is None   # antigua: presupuesto fuera del universo


# --- Cambio 3: cajón no es «fase con HH» -----------------------------------------------------------

def test_cajon_v2_es_paquete_sin_es_fase():
    c = EST.clasificar(_v2())
    assert c["c6"].tipo == EST.PAQUETE and not c["c6"].es_fase
    assert c["a0"].tipo == EST.PAQUETE and not c["a0"].es_fase
    assert c["h1"].tipo == EST.FASE                                          # hito sin HH
    assert EST.clasificar(ANTIGUA)["f9"].es_fase                             # antigua: sigue avisando


# --- Cambio 4: avance --------------------------------------------------------------------------------

def test_avance_v2_cerrado_manual_y_consumo():
    tareas = _v2(_t("c8", "08 Revisión", hh=10, estado="completado", tipo="done"),
                 _t("c3", "03 Antecedentes Cliente", hh=16, avance=0.5))
    av = EST.avance_efectivo(tareas, EST.clasificar(tareas), {"c6": 30.0, "c7": 50.0, "c3": 1.0})
    assert av["c8"] == (1.0, EST.CERRADO)
    assert av["c3"] == (0.5, EST.MANUAL)
    assert av["c6"] == (0.3, EST.CONSUMO)
    assert av["c7"] == (0.9, EST.CONSUMO)                                    # 250 % de consumo, tope 90 %
    assert av["a0"] == (0.0, EST.CONSUMO)


def test_avance_lista_antigua_sin_cambios():
    av = EST.avance_efectivo(ANTIGUA, EST.clasificar(ANTIGUA), {"p1": 99.0})
    assert av["p1"][1] == EST.SIN_DATO


def test_nota_de_consumo_en_el_titular():
    assert PR.avance_por_consumo({"a": "consumo", "b": "consumo"}) == "por consumo, tope 90 %"
    assert PR.avance_por_consumo({"a": "consumo", "b": "manual"}) == "parte por consumo, tope 90 %"
    assert PR.avance_por_consumo({"a": "manual"}) is None
    txt = PR.titular(True, 0.3, 0.4, consumo="por consumo, tope 90 %")
    assert txt.startswith("Avance real 30,0 % (por consumo, tope 90 %) frente a 40,0 % programado")


# --- Rev. 0 con la primera hora registrada, programado provisional antes ----------------------------
# Desde el 2026-11-03 (TAREA_curva_programada_unica) la primera porción ya no dispara la Rev. 0.

def test_evento_congelar():
    assert LB.evento_congelar([], CORTE) is None
    assert LB.evento_congelar([D(2026, 11, 20)], CORTE) is None          # hora posterior al corte
    ev = LB.evento_congelar([D(2026, 11, 6), D(2026, 11, 5)], CORTE)
    assert (ev.texto, ev.fecha) == ("primera hora registrada el 05-11-2026", D(2026, 11, 5))


def test_decidir_misma_regla_v2_y_antigua():
    for ts in (_v2(), ANTIGUA):
        d = LB.decidir("L", ts, [], True, False)
        assert (d.accion, d.estado, d.avisos) == ("ninguna", LB.PROVISIONAL, ())
        ev = LB.Evento("primera hora registrada el 05-11-2026", D(2026, 11, 5))
        d = LB.decidir("L", ts, [], False, False, evento=ev, corte=CORTE)
        assert (d.accion, d.tipo, d.estado) == ("congelar", "normal", "vigente")
        assert d.motivo == "Rev. 0 automática (normal: primera hora registrada el 05-11-2026)"


# --- Cambio 5: horas en administración -------------------------------------------------------------

def test_horas_en_administracion_no_cuenta_00_costeo():
    tm = a_tareas_metrica(_v2(_t("k", "00 Costeo (planilla)")))
    assert H.horas_en_administracion(tm, [_h("k", D(2026, 11, 3), 50), _h("c6", D(2026, 11, 3), 10)], 0.2) == []
    av = H.horas_en_administracion(tm, [_h("a0", D(2026, 11, 3), 50), _h("c6", D(2026, 11, 3), 10)], 0.2, v2=True)
    assert av and av[0].datos["v2"]
    assert "00 Administración y cierre" in PR.mensaje("horas_en_administracion", None, av[0].datos)


# --- Cambio 6: textos -------------------------------------------------------------------------------

def test_textos_de_presupuesto_v2():
    a = PRES.avisos({"hh_contrato": None}, v2=True)[0]
    assert "los cajones" in a.detalle
    assert "cajones" in PR.mensaje("sin_presupuesto_contractual", None, a.datos)
    r = RES.resolver("sin_presupuesto_contractual", RES.Contexto(None, "0271 · Grúa", False, a.datos))
    assert "de cada cajón" in r["como_resolver"]
    r = RES.resolver("presupuesto_por_agotarse", RES.Contexto(None, "0271 · Grúa", True, {"superado": True, "v2": True}))
    assert "cajones" in r["como_resolver"]
    antiguo = RES.resolver("sin_presupuesto_contractual", RES.Contexto(None, "0235 · X", False, {}))
    assert "«00 Administración»" in antiguo["como_resolver"]


# --- De punta a punta: procesar_lista y filas_de --------------------------------------------------

LISTA = ListInfo("L", "PJ-2026.0271 | Análisis estabilidad grúa | Ingevec", None, False, "901316452800", None, None,
                 start=_ms(D(2026, 11, 2)), due=_ms(D(2026, 12, 14)))


def _entrada(tarea, d, h):
    return TimeEntry(f"e{tarea}{d}", 1, "x", tarea, "", "L", _ms(d), None, int(h * 3_600_000))


def _procesar(tareas, entradas=(), lb=()):
    return run.procesar_lista(LISTA, tareas, list(entradas), [], CORTE, por_nombre("dep"), list(lb), True, False,
                              AHORA, "PJ-2026.0271")


def test_v2_sin_evento_programado_provisional():
    r = _procesar(_v2())
    assert r.lb_nuevas == [] and r.lb_filas == [] and run.provisional(r)
    tipos = {a["tipo"] for a in r.advertencias_todas}
    assert not tipos & {"fase_con_hh", "sin_tarea_1_2", "en_planificacion", "hh_distinta_de_time_estimate"}
    m = r.resultado.metricas
    assert m["total_hh"] == 129 and m["hh_actuales_clickup"] == 129 and m["hh_prog_acum"] > 0
    assert r.presupuesto["hh_contrato"] == 129
    filas = run.filas_de(r, CORTE, por_nombre("dep"), AHORA)
    assert filas["proyectos"][0]["estado_linea_base"] == "provisional"
    ms = filas["metricas_semanales"][0]
    assert ms["linea_base_provisional"] is True and ms["rev_linea_base"] is None and ms["tiene_linea_base"] is False
    assert ms["desviacion_pts"] is not None
    assert ms["titular"].startswith("Programado provisional (aún sin línea base congelada). Avance real 0,0 % "
                                    "(por consumo, tope 90 %)")
    assert any(f["hh_prog_acum"] for f in filas["serie_diaria"])
    assert filas.get("linea_base", []) == []


def test_v2_primera_hora_congela_rev0_con_todos_los_cajones():
    r = _procesar(_v2(), [_entrada("c6", D(2026, 11, 5), 30)])
    assert not run.provisional(r)
    assert {f.task_id: f.hh for f in r.lb_nuevas} == {"a0": 9, "c6": 100, "c7": 20}
    assert {f.tipo for f in r.lb_nuevas} == {"normal"}
    assert r.lb_nuevas[0].motivo == "Rev. 0 automática (normal: primera hora registrada el 05-11-2026)"
    assert r.origen_avance["c6"] == EST.CONSUMO
    assert not [a for a in r.advertencias_todas if a["tipo"] == "horas_sin_avance"]      # el consumo la reemplaza
    c6 = next(t for t in r.tm if t.id == "c6")
    assert c6.avance == 0.3
    ms = run.filas_de(r, CORTE, por_nombre("dep"), AHORA)["metricas_semanales"][0]
    assert ms["linea_base_provisional"] is False and ms["rev_linea_base"] == 0
    assert "(por consumo, tope 90 %)" in ms["titular"] and not ms["titular"].startswith("Programado provisional")
    # el titular del corte en que se congela lo dice
    assert ms["titular"].startswith("Línea base Rev. 0 congelada en este corte (primera hora registrada el 05-11-2026). ")


def test_v2_primera_porcion_ya_no_congela_rev0():
    porcion = _t("s1", "Modelación · 09-nov", "c6", te=8 * 3_600_000, asignados=("ana",), s=D(2026, 11, 9),
                 d=D(2026, 11, 13))
    r = _procesar(_v2(porcion))
    assert r.lb_nuevas == [] and run.provisional(r)


def test_reproceso_de_un_corte_provisional_queda_sin_curva():
    from dep_reportes import reproceso as REP
    fila = {"corte": CORTE, "tipo_corte": "oficial", "list_id": "L", "fecha_termino_usada": D(2026, 12, 14),
            "hh_historicas": 0.0, "hh_gastadas_acum": 0.0, "rev_linea_base": None, "linea_base_provisional": True,
            "total_hh": 129.0, "titular": "Programado provisional (...)"}
    fotos = [{"task_id": "c6", "task_nombre": "06 Análisis", "hh": 100.0, "start": D(2026, 11, 4),
              "due": D(2026, 12, 3), "hh_gastadas_acum": 0.0}]
    nueva, _ = REP.recalcular(CORTE, fila, fotos, [], por_nombre("dep"))
    assert nueva["linea_base_provisional"] is False and nueva["total_hh"] is None
    assert nueva["titular"].startswith("Sin curva programada")
