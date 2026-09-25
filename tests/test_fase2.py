import datetime as dt
from pathlib import Path

import pytest

from dep_clickup.config import TZ
from dep_clickup.fields import resolve_custom_fields
from dep_clickup.models import ListInfo, Task
from dep_reportes import almacen as A, esquema as E, linea_base as LB, proyecto as P
from dep_reportes.calendario import Calendario, calendario_chile, leer_dias_no_habiles
from dep_reportes.metricas import Horas, TareaMetrica
from dep_reportes.modos import LEGADO, modo_dep
from dep_reportes.run import fecha_corte, ultimo_domingo

D = dt.date
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "Curva S - Proyecto 2026.0152.xlsx"


def T(id_, s, d, hh, av=0.0, parent=None, estado=None):
    return TareaMetrica(id_, id_, parent, s, d, hh, av, estado)


# --- Calendario ---------------------------------------------------------------------------------

def test_feriados_chile_2026():
    cal = calendario_chile(extra_csv=None)
    assert not cal.es_habil(D(2026, 9, 18))       # Fiestas Patrias (viernes)
    assert cal.es_habil(D(2026, 9, 17))
    assert cal.networkdays(D(2026, 9, 14), D(2026, 9, 18)) == 4


def test_dias_no_habiles_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("fecha,motivo\n2026-09-17,Aniversario IDIEM\n", encoding="utf-8")
    assert leer_dias_no_habiles(p) == {D(2026, 9, 17): "Aniversario IDIEM"}
    assert not calendario_chile(extra_csv=p).es_habil(D(2026, 9, 17))
    assert leer_dias_no_habiles(tmp_path / "no_existe.csv") == {}


# --- Corte --------------------------------------------------------------------------------------

def test_corte_domingo():
    assert fecha_corte("2026-09-20", D(2026, 9, 23)) == D(2026, 9, 20)
    assert fecha_corte(None, D(2026, 9, 23)) == D(2026, 9, 20)
    assert ultimo_domingo(D(2026, 9, 20)) == D(2026, 9, 20)
    with pytest.raises(SystemExit):
        fecha_corte("2026-09-19", D(2026, 9, 23))


# --- Modo legado reproduce el Excel via proyecto.calcular ------------------------------------

@pytest.fixture(scope="module")
def fx():
    if not FIXTURE.exists():
        pytest.skip("fixture Excel no disponible")
    from dep_reportes import fixture_excel
    return fixture_excel.cargar(FIXTURE)


def test_legado_reproduce_excel(fx):
    r = P.calcular(fx.programa, fx.avance, fx.horas, fx.control, fx.fin, LEGADO)
    assert r.metricas["total_hh"] == 605
    assert r.metricas["avance_prog"] == pytest.approx(fx.avance_programado, abs=1e-12)
    assert r.metricas["avance_real"] == pytest.approx(fx.avance_real, abs=1e-12)
    # El Excel corta la curva en el termino (02-10); estimadas_al_termino incluye tambien las 10 HH de
    # "10.2 Levantamiento de Observaciones" (13 al 16-10), posteriores al termino.
    serie = {p.fecha: p for p in r.serie}
    assert serie[fx.fin].proyectadas == pytest.approx(fx.serie[-1].proyectadas, abs=0.01)
    assert r.metricas["hh_estimadas_al_termino"] == pytest.approx(234.25 + 162, abs=0.01)
    prog = {p.fecha: p.programadas for p in r.serie}
    for p in fx.serie:
        if p.fecha in prog:
            assert prog[p.fecha] == pytest.approx(p.programadas, abs=0.01)


# --- Cambios de logica del modo dep -------------------------------------------------------------

def test_base_de_proyeccion_en_control_inclusive():
    C = D(2026, 9, 20)
    horas = [Horas(D(2026, 9, 16), 2), Horas(D(2026, 9, 18), 3), Horas(D(2026, 9, 20), 1)]
    tareas = [T("a", D(2026, 9, 1), D(2026, 9, 30), 10, 0.5)]
    dep = P.calcular(tareas, tareas, horas, C, D(2026, 9, 30), modo_dep(None))
    assert dep.metricas["hh_gastadas_acum"] == 6          # incluye el domingo
    assert dep.metricas["hh_estimadas_al_termino"] == pytest.approx(6 + 5)
    serie = {p.fecha: p for p in dep.serie}
    assert serie[C].proyectadas == pytest.approx(6)       # la proyeccion parte de las gastadas a C
    assert serie[D(2026, 9, 21)].gastadas is None


def test_feriado_saca_hh_del_dia():
    t = [T("a", D(2026, 9, 17), D(2026, 9, 18), 8)]
    leg = P.calcular(t, t, [], D(2026, 9, 20), D(2026, 9, 30), LEGADO)
    dep = P.calcular(t, t, [], D(2026, 9, 20), D(2026, 9, 30), modo_dep(None))
    s_leg = {p.fecha: p.programadas for p in leg.serie}
    s_dep = {p.fecha: p.programadas for p in dep.serie}
    assert s_leg[D(2026, 9, 17)] == 4 and s_dep[D(2026, 9, 17)] == 8


def test_proyecto_vencido_al_primer_habil():
    C = D(2026, 9, 13)
    t = [T("a", D(2026, 9, 1), D(2026, 9, 4), 10, 0.2)]
    r = P.calcular(t, t, [], C, D(2026, 9, 10), modo_dep(None))
    assert {a.tipo for a in r.avisos} >= {P.ADV_TERMINO_VENCIDO}
    assert P.pendientes_tarea(t[0], C, D(2026, 9, 10), modo_dep(None)) == {D(2026, 9, 14): pytest.approx(8)}
    # Con el 18-09 feriado, el primer habil despues del domingo 13 sigue siendo el lunes 14; despues del 17 es el 21
    assert P.primer_habil_despues(D(2026, 9, 17), calendario_chile(extra_csv=None)) == D(2026, 9, 21)


def test_no_aplica_fuera_del_universo():
    t = [T("a", D(2026, 9, 1), D(2026, 9, 4), 10, 1.0), T("b", D(2026, 9, 1), D(2026, 9, 4), 10, 0.0, estado="No Aplica")]
    dep = P.calcular(None, t, [], D(2026, 9, 20), D(2026, 9, 30), modo_dep(None))
    leg = P.calcular(None, t, [], D(2026, 9, 20), D(2026, 9, 30), LEGADO)
    assert dep.metricas["avance_real"] == 1.0 and leg.metricas["avance_real"] == 0.5
    assert P.ADV_NO_APLICA_CON_HH in {a.tipo for a in dep.avisos}


def test_programado_solo_de_linea_base_y_spi_cpi():
    lb = [T("a", D(2026, 9, 14), D(2026, 9, 17), 8)]
    act = [T("a", D(2026, 9, 21), D(2026, 9, 24), 10, 0.5)]   # fechas y HH cambiaron en ClickUp
    r = P.calcular(lb, act, [Horas(D(2026, 9, 15), 2)], D(2026, 9, 20), D(2026, 9, 30), modo_dep(None))
    m = r.metricas
    assert m["total_hh"] == 8 and m["hh_prog_acum"] == 8 and m["hh_actuales_clickup"] == 10
    assert m["ev"] == 4 and m["spi"] == 0.5 and m["cpi"] == 2
    assert P.ADV_HH_CAMBIARON in {a.tipo for a in r.avisos}


def test_sin_linea_base_sin_programado():
    act = [T("a", D(2026, 9, 14), D(2026, 9, 17), 8, 0.5)]
    m = P.calcular(None, act, [], D(2026, 9, 20), D(2026, 9, 30), modo_dep(None)).metricas
    assert m["total_hh"] is None and m["hh_prog_acum"] is None and m["spi"] is None and m["ev"] is None
    assert m["avance_real"] == 0.5


# --- Linea base ---------------------------------------------------------------------------------

def task(id_, name, parent=None, status="to do", tipo="open", hh=None, s=None, d=None):
    cf = resolve_custom_fields([{"id": "hh", "name": "HH Presupuestadas", "type": "number", "value": hh}] if hh else [])
    ms = lambda x: dt.datetime.combine(x, dt.time(4), TZ) if x else None
    return Task(id_, name, parent, status, "L", ms(s), ms(d), None, (), cf, status_type=tipo)


def proyecto_tipo(estado_12="to do", tipo_12="open"):
    return [task("f0", "00 Administración"), task("f1", "01 Planificación"),
            task("t12", "1.2 Plan de Trabajo", "f1", estado_12, tipo_12),
            task("f2", "02 Ejecución"), task("x", "2.1 Algo", "f2", hh=10, s=D(2026, 9, 1), d=D(2026, 9, 4)),
            task("na", "2.2 Otro", "f2", "no aplica", "done", hh=5, s=D(2026, 9, 1), d=D(2026, 9, 4))]


LISTA = ListInfo("L", "PJ-2026.9999 | X", "green", False, "F", "S", 6, due=dt.datetime(2026, 10, 2, 4, tzinfo=TZ))
AHORA = dt.datetime(2026, 9, 23, 12, tzinfo=TZ)


def test_disparador_1_2():
    d = LB.decidir("L", proyecto_tipo(), [], observada_antes=True, primera_corrida=False)
    assert (d.accion, d.en_planificacion) == ("ninguna", True)
    d = LB.decidir("L", proyecto_tipo("completado", "done"), [], observada_antes=True, primera_corrida=False)
    assert (d.accion, d.tipo) == ("congelar", "normal")
    d = LB.decidir("L", proyecto_tipo("completado", "done"), [], observada_antes=False, primera_corrida=True)
    assert (d.accion, d.tipo) == ("congelar", "tardia")
    d = LB.decidir("L", proyecto_tipo("no aplica", "done"), [], observada_antes=False, primera_corrida=True)
    assert d.accion == "ninguna" and P.ADV_TAREA_12_NO_APLICA in {a.tipo for a in d.avisos}


def test_sin_tarea_1_2():
    sin = [t for t in proyecto_tipo() if t.id != "t12"]
    assert LB.decidir("L", sin, [], False, primera_corrida=True).tipo == "tardia"
    d = LB.decidir("L", sin, [], True, primera_corrida=False)
    assert d.accion == "ninguna" and P.ADV_SIN_TAREA_12 in {a.tipo for a in d.avisos}


def test_1_2_fuera_de_fase_01_no_cuenta():
    ts = [task("f2", "02 Ejecución"), task("t", "1.2 Plan de Trabajo", "f2", "completado", "done")]
    assert LB.tareas_12(ts) == []


def test_congelar_excluye_no_aplica_y_guarda_contractual():
    filas = LB.congelar(LISTA, proyecto_tipo("completado", "done"), 0, "tardia", "m", AHORA)
    assert [f.task_id for f in filas] == ["x"]
    assert filas[0].fase == "02 Ejecución" and filas[0].fecha_entrega_contractual == D(2026, 10, 2)
    assert filas[0].fecha_inicio == D(2026, 9, 1)   # la lista no tiene inicio: start mas temprano


def test_linea_base_existente_no_se_recongela_y_vigente_es_la_mayor():
    r0 = LB.congelar(LISTA, proyecto_tipo("completado", "done"), 0, "tardia", "m", AHORA)
    r1 = LB.congelar(LISTA, proyecto_tipo("completado", "done"), 1, "revision", "cambio", AHORA)
    assert LB.decidir("L", proyecto_tipo("completado", "done"), r0, True, False).accion == "ninguna"
    assert LB.vigente(r0 + r1, "L")[0] == 1


def test_importar_excel(fx):
    filas = LB.importar_excel(ListInfo("901328186343", "PJ-2026.0152", None, False, None, None, 55), [],
                              FIXTURE, D(2026, 10, 2), AHORA)
    assert sum(f.hh for f in filas) == 605 and len(filas) == 20
    assert {f.tipo for f in filas} == {"importada_excel"}


# --- Almacen: tipos e idempotencia ---------------------------------------------------------------

def test_serial_fechas():
    assert A.a_serial(D(2026, 9, 20)) == 46285
    assert A.desde_serial(46285, E.FECHA) == D(2026, 9, 20)
    t = dt.datetime(2026, 9, 20, 18, 0, tzinfo=TZ)
    assert A.desde_serial(A.a_serial(t), E.FECHA_HORA) == t
    assert A.celda_sheets(None, E.NUMERO) == "" and A.celda_sheets("3", E.NUMERO) == 3.0
    assert A.celda_sheets("=SUMA(1)", E.TEXTO) == "=SUMA(1)"   # RAW: nunca se interpreta como formula


def test_fusion_idempotente():
    C = D(2026, 9, 20)
    viejas = [{"corte": D(2026, 9, 13), "list_id": "L"}, {"corte": C, "list_id": "L", "v": 1}]
    nuevas = [{"corte": C, "list_id": "L", "v": 2}]
    una = A.fusionar("metricas_semanales", viejas, nuevas, C)
    dos = A.fusionar("metricas_semanales", una, nuevas, C)
    assert una == dos == [viejas[0], nuevas[0]]


def test_fusion_con_alcance_solo():
    C = D(2026, 9, 20)
    exist = [{"corte": C, "list_id": "A"}, {"corte": C, "list_id": "B", "v": 1}]
    out = A.fusionar("fotos_tareas", exist, [{"corte": C, "list_id": "B", "v": 2}], C, alcance={"B"})
    assert out == [{"corte": C, "list_id": "A"}, {"corte": C, "list_id": "B", "v": 2}]
    assert A.fusionar("proyectos", [{"list_id": "A"}, {"list_id": "B"}], [{"list_id": "B", "x": 1}], C, {"B"}) == \
        [{"list_id": "A"}, {"list_id": "B", "x": 1}]


def test_linea_base_solo_agrega():
    exist = [{"list_id": "L", "rev": 0, "task_id": "a"}]
    out = A.fusionar("linea_base", exist, [{"list_id": "L", "rev": 0, "task_id": "a"},       # ya estaba: no se repite
                                           {"list_id": "L", "rev": 0, "task_id": "b"},       # incremental de la Rev. 0
                                           {"list_id": "L", "rev": 1, "task_id": "a"}], D(2026, 9, 20))
    assert out == exist + [{"list_id": "L", "rev": 0, "task_id": "b"}, {"list_id": "L", "rev": 1, "task_id": "a"}]


def test_encabezados_distintos_abortan():
    with pytest.raises(RuntimeError):
        A.filas_desde_valores("proyectos", [["otra", "cosa"]])


def test_ida_y_vuelta_de_valores():
    fila = {"corte": D(2026, 9, 20), "tipo_corte": "oficial", "es_ultimo_corte": True, "es_ultimo_oficial": True,
            "list_id": "901", "codigo": "PJ-2026.0152",
            "nombre_corto": "Evaluación estructural", "cliente": "NESTLE", "proyecto": "2026.0152 · Evaluación estructural",
            "jp_nombre": "Ana", "jp_email": "ana@x.cl", "rev_linea_base": 0, "tiene_linea_base": True,
            "modo_calculo": "dep", **{c: 1.5 for c, _ in E.METRICAS}, "desviacion_pts": -1.1,
            "pct_presupuesto_usado": 0.4, "titular": "Avance real 73,2 % frente a 74,3 % programado: 1,1 puntos bajo el plan.",
            "n_advertencias": 3, "hh_contrato": 3000.0, "pct_contrato_usado": 0.81, "ritmo_semanal": 40.0,
            "semanas_restantes_al_ritmo": 14.5, "fecha_agotamiento_estimada": D(2027, 1, 12)}
    ti = E.tipos("metricas_semanales")
    valores = [E.columnas("metricas_semanales"), [A.celda_sheets(fila[c], ti[c]) for c in E.columnas("metricas_semanales")]]
    assert A.filas_desde_valores("metricas_semanales", valores) == [fila]


def test_sin_datos_por_persona_en_el_esquema():
    prohibidas = {"user_id", "usuario", "persona", "username", "assignee", "assignees"}
    for t, cols in E.TABLAS.items():
        assert not prohibidas & {c for c, _ in cols}, t


def test_advertencias_para_la_hoja():
    adv = [{"tipo": "avance_sin_horas", "task_id": "sin_hh"}, {"tipo": "avance_sin_horas", "task_id": "con_hh"},
           {"tipo": P.ADV_TERMINO_VENCIDO, "task_id": ""}, {"tipo": "hh_en_padre_y_subtarea", "task_id": "x"},
           {"tipo": P.ADV_SIN_JP, "task_id": ""}, {"tipo": P.ADV_HH_CAMBIARON, "task_id": ""}]
    assert [a["task_id"] or a["tipo"] for a in P.para_hoja(adv, {"con_hh"})] == \
        ["con_hh", P.ADV_TERMINO_VENCIDO, "x", P.ADV_SIN_JP, P.ADV_HH_CAMBIARON]


def test_migracion_de_encabezado_anterior():
    viejo = ["corte", "list_id", "tipo", "task_id", "detalle"]
    filas = A.filas_desde_valores("advertencias", [viejo, [46285, "901", "sin_jp", "", "x"]])
    assert filas[0]["codigo"] is None and filas[0]["es_ultimo_corte"] is None and filas[0]["corte"] == D(2026, 9, 20)
    assert list(filas[0]) == E.columnas("advertencias")
    with pytest.raises(RuntimeError):
        A.filas_desde_valores("advertencias", [viejo + ["columna_desconocida"]])


def test_completar_ultimo_corte_e_identificacion():
    ident = {"901": {"codigo": "PJ-1", "jp_nombre": "Ana", "jp_email": "a@x.cl"}}
    filas = [{"corte": D(2026, 9, 13), "list_id": "901", "codigo": None}, {"corte": D(2026, 9, 20), "list_id": "901",
             "codigo": "PJ-1", "jp_nombre": "Otra", "jp_email": ""}]
    out = A.completar("metricas_semanales", filas, ident)
    assert [f["es_ultimo_corte"] for f in out] == [False, True]
    assert out[0]["jp_nombre"] == "Ana" and out[1]["jp_nombre"] == "Otra"   # no pisa lo ya escrito
    assert A.celda_sheets(True, E.BOOLEANO) is True and A.celda_csv(False, E.BOOLEANO) == "FALSE"
    assert A.desde_celda(True, E.BOOLEANO) is True and A.desde_celda("FALSE", E.BOOLEANO) is False


def test_duplicados():
    C = D(2026, 9, 20)
    assert A.duplicados("metricas_semanales", [{"corte": C, "list_id": "1"}, {"corte": C, "list_id": "2"}]) == 0
    assert A.duplicados("metricas_semanales", [{"corte": C, "list_id": "1"}, {"corte": C, "list_id": "1"}]) == 1


def test_identificacion_en_tablas_de_hechos():
    for t in ("serie_diaria", "metricas_semanales", "metricas_fase", "advertencias"):
        assert {"codigo", "jp_nombre", "jp_email"} <= set(E.columnas(t)), t
    for t in ("metricas_semanales", "metricas_fase", "advertencias"):
        assert E.tipos(t)["es_ultimo_corte"] == E.BOOLEANO


# --- Codigos unicos y estables ------------------------------------------------------------------

from dep_reportes import codigos as COD  # noqa: E402

L1 = ("901327788557", "PJ-2025.0019-0147 | Desarrollo Informes")
L2 = ("901327789240", "PJ-2025.0019-0147 | Calibración CMP")
L3 = ("901328186343", "PJ-2026.0152 | Nestlé")


def test_codigos_duplicados_reciben_sufijo_por_orden_de_creacion():
    # Estado real: la hoja tenia el mismo codigo para las dos listas
    a = COD.asignar([L2, L1, L3], {L1[0]: "PJ-2025.0019-0147", L2[0]: "PJ-2025.0019-0147", L3[0]: "PJ-2026.0152"})
    assert a.codigos == {L1[0]: "PJ-2025.0019-0147-A", L2[0]: "PJ-2025.0019-0147-B", L3[0]: "PJ-2026.0152"}
    assert a.duplicados == {"PJ-2025.0019-0147": [L1[0], L2[0]]}


def test_codigos_estables_entre_corridas():
    primera = COD.asignar([L1, L2, L3], {}).codigos
    assert COD.asignar([L1, L2, L3], primera).codigos == primera
    # La otra lista desaparece: la que queda conserva su sufijo
    assert COD.asignar([L2, L3], primera).codigos[L2[0]] == "PJ-2025.0019-0147-B"
    # Llega una tercera lista con el mismo codigo: las anteriores no cambian y la nueva toma la siguiente letra
    nueva = ("901399999999", "PJ-2025.0019-0147 | Otra")
    c = COD.asignar([L1, L2, nueva, L3], primera).codigos
    assert (c[L1[0]], c[L2[0]], c[nueva[0]]) == ("PJ-2025.0019-0147-A", "PJ-2025.0019-0147-B", "PJ-2025.0019-0147-C")
    # Renombrar la lista no cambia su codigo
    renombrada = (L1[0], "PJ-2025.0019-0147 | Informes (renombrada)")
    assert COD.asignar([renombrada, L2, L3], primera).codigos[L1[0]] == "PJ-2025.0019-0147-A"


def test_lista_nueva_con_codigo_ya_publicado_por_otra():
    # Una lista existente ya publico el codigo sin sufijo; la nueva recibe sufijo y la existente no cambia
    previos = {L3[0]: "PJ-2026.0152"}
    otra = ("901400000000", "PJ-2026.0152 | Adenda")
    c = COD.asignar([L3, otra], previos).codigos
    assert c[L3[0]] == "PJ-2026.0152" and c[otra[0]] == "PJ-2026.0152-A"
    assert len(set(c.values())) == 2


def test_completar_actualiza_codigo_en_filas_historicas():
    C0, C1 = D(2026, 9, 13), D(2026, 9, 20)
    ident = {"1": {"codigo": "X-A", "jp_nombre": "Nuevo", "jp_email": "n@x"}}
    filas = [{"corte": C0, "list_id": "1", "codigo": "X", "jp_nombre": "Antiguo", "jp_email": "a@x"}]
    out = A.completar("metricas_semanales", filas, ident)
    assert out[0]["codigo"] == "X-A" and out[0]["jp_nombre"] == "Antiguo"
