"""Programas de servicio continuo (programas.py): contrato y linea, horas, consumo frente al plan y entregables."""
import datetime as dt

import pytest

from dep_clickup.config import TZ
from dep_clickup.models import Task
from dep_reportes import almacen as A, esquema as E, programas as PG
from dep_reportes.config_reportes import PROGRAMAS_JSON, cortes_historicos

D = dt.date
CORTE = D(2026, 10, 1)

CONFIG = {
    "nombre": "Monitoreo", "cliente": "CMP",
    "contratos": {
        "0019": {"nombre": "Los Colorados", "codigo": "PJ-2025.0019", "patron_fase": "0019|MLC",
                 "presupuesto": {"hh_periodo": 1200, "periodo_inicio": "2026-01-15", "periodo_fin": "2026-12-10"}},
        "0147": {"nombre": "Apilador", "codigo": "PJ-2025.0147", "patron_fase": "0147|Apilador",
                 "presupuesto": {"hh_mes": 50, "periodo_inicio": "2026-07-01", "periodo_fin": "2026-12-31"}},
    },
    "lineas": {"general": "General", "informes": "Informes"},
    "listas": [{"list_id": "G19", "linea": "general", "contrato": "0019"},
               {"list_id": "INF", "linea": "informes"},
               {"list_id": "FIN", "linea": "general", "contrato": "0147", "solo_consumo": True}],
    "entregables": {"informe": "^IM-\\d"},
    "advertencias_omitidas": ["proyecto_con_termino_vencido"],
}
P = PG.desde_dict("CMP", CONFIG)


def tarea(tid, nombre, parent=None, status="to do", due=None, done=None, tipo="open"):
    h = lambda d: dt.datetime(d.year, d.month, d.day, 12, tzinfo=TZ) if d else None
    return Task(tid, nombre, parent, status, "INF", None, h(due), None, (), {}, status_type=tipo, date_done=h(done))


TAREAS_INF = [tarea("f19", "PJ-2025.0019 Informes MLC"), tarea("f147", "PJ-2025.0147 Informes Apilador"),
              tarea("fvis", "PJ-2025.0147/.0019 Visitas"), tarea("fgen", "Tareas Generales"),
              tarea("im1", "IM-01 Informe Mensual N°1", "f19", "completado", D(2026, 8, 20), D(2026, 8, 21), "done"),
              tarea("im2", "IM-02 Informe Mensual N°2", "f19", "completado", D(2026, 9, 20), D(2026, 9, 18), "done"),
              tarea("im3", "IM-01 Informe Mensual N°1", "f147", "to do", D(2026, 9, 25)),
              tarea("im4", "IM-02 Informe Mensual N°2", "f147", "to do", D(2026, 10, 20)),
              tarea("im5", "IM-03 Informe Mensual N°3", "f147", "to do"),
              tarea("x", "Revisión de datos", "fvis")]


def test_la_config_del_repo_carga():
    progs = PG.cargar(PROGRAMAS_JSON)
    assert progs and all(p.listas and p.contratos for p in progs.values())
    PG.por_lista(progs)                       # ninguna lista en dos programas


def test_config_invalida():
    with pytest.raises(ValueError, match="contrato 9999"):
        PG.desde_dict("X", {**CONFIG, "listas": [{"list_id": "L", "linea": "general", "contrato": "9999"}]})
    with pytest.raises(ValueError, match="línea otra"):
        PG.desde_dict("X", {**CONFIG, "listas": [{"list_id": "L", "linea": "otra"}]})
    with pytest.raises(ValueError, match="dos programas"):
        PG.por_lista({"a": P, "b": PG.desde_dict("b", CONFIG)})


def test_contrato_fijo_o_por_fase():
    assert P.contrato_de("G19", "05 Reportes") == "0019"                  # fijo en la lista
    assert P.contrato_de("INF", "PJ-2025.0019 Informes MLC") == "0019"
    assert P.contrato_de("INF", "PJ-2025.0147 Informes Apilador") == "0147"
    assert P.contrato_de("INF", "PJ-2025.0147/.0019 Visitas") == PG.COMPARTIDO   # calza con los dos
    assert P.contrato_de("INF", "Tareas Generales") == PG.COMPARTIDO             # no calza con ninguno
    assert P.contrato_de("INF", None) == PG.COMPARTIDO                           # tarea que ya no esta en la lista
    # Lista "General" fusionada (sin contrato fijo): el contrato sale de la fase
    fusion = PG.desde_dict("F", {**CONFIG, "listas": [{"list_id": "GEN", "linea": "general"}]})
    assert fusion.contrato_de("GEN", "MLC 0019") == "0019" and fusion.contrato_de("GEN", "Apilador 0147") == "0147"


def test_contrato_por_defecto_de_la_lista_general():
    gen = PG.desde_dict("F", {**CONFIG, "listas": [{"list_id": "GEN", "linea": "general", "contrato_por_defecto": "0019"}]})
    assert gen.contrato_de("GEN", "Apilador 0147") == "0147"                    # la fase manda
    assert gen.contrato_de("GEN", "00 Administración") == "0019"                # no calza: por defecto
    assert gen.contrato_de("GEN", "PJ-2025.0147/.0019 Visitas") == "0019"       # calza con los dos: por defecto
    assert gen.contrato_de("GEN", None) == "0019"
    hist = PG.horas_de_lista(gen, "GEN", [], [], [(D(2025, 5, 2), 10.0)])
    assert [(x.origen, x.contrato) for x in hist] == [(PG.TIMETRACKER, "0019")]  # el saldo historico tambien
    with pytest.raises(ValueError, match="contrato_por_defecto 9999"):
        PG.desde_dict("X", {**CONFIG, "listas": [{"list_id": "L", "linea": "general", "contrato_por_defecto": "9999"}]})
    with pytest.raises(ValueError, match="contrato fijo y contrato_por_defecto"):
        PG.desde_dict("X", {**CONFIG, "listas": [{"list_id": "L", "linea": "general", "contrato": "0019",
                                                  "contrato_por_defecto": "0147"}]})


def test_la_config_del_repo_tiene_la_regla_de_general_y_los_entregables():
    p = PG.cargar(PROGRAMAS_JSON)["CMP-SHM"]
    gen = p.listas["901326875156"]
    assert gen.contrato is None and gen.contrato_por_defecto == "0019"
    assert p.frecuencias == {"informe": PG.MENSUAL, "visita": PG.EVENTO, "reporte_diario": PG.MENSUAL,
                             "reporte_alerta": PG.EVENTO}
    assert p.entregables["reporte_diario"].search("RD-03 Reportes diarios sep 2026")
    assert p.entregables["reporte_alerta"].search("RA-01 Reporte de alerta E4")
    assert p.entregables["reporte_alerta"].search("RE-01 Reporte de Evento - FECHA 14/07 al 20/07")   # RE = alias de RA
    l147 = p.listas["901327109633"]
    assert l147.contrato == "0147" and l147.solo_consumo        # vacía tras la migración; su saldo histórico cuenta
    # sin entradas nativas desde la migración: el corte histórico de 0147 se fija a mano (su primera nativa)
    assert cortes_historicos()["PJ-2025.0147"] == D(2026, 6, 3)


def test_ritmo_planificado():
    c19, c147 = P.contratos["0019"], P.contratos["0147"]
    assert c19.meses_periodo == 12 and c19.ritmo == 100 and c19.hh_total_periodo == 1200
    assert c147.meses_periodo == 6 and c147.ritmo == 50 and c147.hh_total_periodo == 300
    sin = PG.desde_dict("S", {**CONFIG, "contratos": {"0019": {"nombre": "x", "patron_fase": "0019"}}, "listas": []})
    assert sin.contratos["0019"].ritmo is None and sin.contratos["0019"].hh_total_periodo is None


def test_horas_de_lista_y_por_linea():
    nat = [(D(2026, 8, 3), 4.0, "im1"), (D(2026, 8, 4), 2.0, "im3"), (D(2026, 9, 1), 1.0, "x"), (D(2026, 9, 2), 3.0, "borrada")]
    h = PG.horas_de_lista(P, "INF", TAREAS_INF, nat, [])
    assert [(x.contrato, x.linea, x.horas) for x in h] == [("0019", "informes", 4.0), ("0147", "informes", 2.0),
                                                           (PG.COMPARTIDO, "informes", 1.0), (PG.COMPARTIDO, "informes", 3.0)]
    hist = PG.horas_de_lista(P, "G19", [], [(D(2026, 8, 5), 5.0, "t")], [(D(2025, 5, 2), 10.0), (D(2025, 5, 9), 6.0)])
    assert {(x.linea, x.origen, x.contrato) for x in hist} == {("general", PG.CLICKUP, "0019"),
                                                               (PG.HISTORIAL, PG.TIMETRACKER, "0019")}
    fin = PG.horas_de_lista(P, "FIN", [], [(D(2026, 8, 6), 7.0, "t")], [])
    assert not fin[0].en_vista and fin[0].contrato == "0147"
    filas = PG.filas_horas(P, h + hist + fin, CORTE, E.PRELIMINAR, {"INF": "Luciano", "G19": "Fernando"})
    assert sum(f["hh"] for f in filas) == 4 + 2 + 1 + 3 + 5 + 16          # la lista solo_consumo no entra
    may = [f for f in filas if f["mes"] == D(2025, 5, 1)]
    assert may == [{**may[0], "contrato": "0019", "linea": PG.HISTORIAL, "linea_nombre": PG.NOMBRE_HISTORIAL,
                    "responsable_linea": "", "origen": PG.TIMETRACKER, "hh": 16.0}]
    assert {f["responsable_linea"] for f in filas if f["linea"] == "informes"} == {"Luciano"}
    assert set(filas[0]) == set(E.columnas("programa_horas"))
    assert A.duplicados("programa_horas", filas) == 0


def test_consumo_frente_al_plan():
    horas = [PG.HoraPrograma("G19", PG.HISTORIAL, "0019", D(2025, 12, 10), 30.0, PG.TIMETRACKER),
             PG.HoraPrograma("G19", "general", "0019", D(2026, 1, 20), 80.0),
             PG.HoraPrograma("G19", "general", "0019", D(2026, 3, 2), 120.0),
             PG.HoraPrograma("INF", "informes", PG.COMPARTIDO, D(2026, 3, 3), 99.0),      # no cuenta en ningun contrato
             PG.HoraPrograma("FIN", "general", "0147", D(2026, 8, 1), 20.0, en_vista=False),   # solo consumo: si cuenta
             PG.HoraPrograma("G19", "general", "0019", D(2026, 10, 5), 500.0)]               # despues del corte
    filas = PG.filas_contratos(P, horas, CORTE, E.OFICIAL)
    c19 = {f["mes"]: f for f in filas if f["contrato"] == "0019"}
    assert min(c19) == D(2025, 12, 1) and max(c19) == D(2026, 12, 1)         # del primer mes con horas al fin del periodo
    dic, ene, mar, oct_, nov = (c19[D(2025, 12, 1)], c19[D(2026, 1, 1)], c19[D(2026, 3, 1)], c19[D(2026, 10, 1)],
                                c19[D(2026, 11, 1)])
    assert dic["hh_acum"] == 30 and dic["hh_acum_periodo"] is None and dic["hh_plan_acum"] is None and not dic["en_periodo"]
    assert ene["hh_acum"] == 110 and ene["hh_acum_periodo"] == 80 and ene["hh_plan_acum"] == 100 and ene["hh_plan_mes"] == 100
    assert mar["hh_acum_periodo"] == 200 and mar["hh_plan_acum"] == 300 and mar["pct_consumido"] == pytest.approx(200 / 1200, abs=1e-6)
    assert oct_["hh_mes"] == 0 and oct_["hh_acum"] == 230 and not oct_["es_futuro"]   # las del 05-10 no cuentan
    assert nov["es_futuro"] and nov["hh_mes"] is None and nov["hh_acum"] is None and nov["hh_plan_acum"] == 1100
    assert c19[D(2026, 12, 1)]["hh_plan_acum"] == 1200
    c147 = {f["mes"]: f for f in filas if f["contrato"] == "0147"}
    assert min(c147) == D(2026, 7, 1) and c147[D(2026, 8, 1)]["hh_acum"] == 20 and c147[D(2026, 8, 1)]["hh_plan_acum"] == 100
    assert set(filas[0]) == set(E.columnas("programa_contratos"))
    assert A.duplicados("programa_contratos", filas) == 0


def test_situacion_de_un_entregable():
    assert PG.situacion(True, D(2026, 9, 20), D(2026, 9, 18), CORTE) == (PG.A_TIEMPO, 0)
    assert PG.situacion(True, D(2026, 9, 20), D(2026, 9, 20), CORTE) == (PG.A_TIEMPO, 0)
    assert PG.situacion(True, D(2026, 8, 20), D(2026, 8, 21), CORTE) == (PG.ATRASADO, 1)
    assert PG.situacion(False, D(2026, 9, 25), None, CORTE) == (PG.VENCIDO, 6)
    assert PG.situacion(False, D(2026, 10, 20), None, CORTE) == (PG.PENDIENTE, None)
    assert PG.situacion(False, None, None, CORTE) == (PG.SIN_FECHA, None)
    assert PG.situacion(True, D(2026, 9, 20), None, CORTE) == (PG.CERRADO_SIN_FECHA, None)


def test_entregables_por_contrato_y_linea():
    filas = PG.filas_entregables(P, "INF", TAREAS_INF, CORTE, E.PRELIMINAR, "Luciano")
    por = {f["task_id"]: f for f in filas}
    assert set(por) == {"im1", "im2", "im3", "im4", "im5"}                  # "Revisión de datos" no es entregable
    assert (por["im1"]["contrato"], por["im1"]["situacion"], por["im1"]["dias_atraso"]) == ("0019", PG.ATRASADO, 1)
    assert (por["im2"]["situacion"], por["im3"]["situacion"], por["im4"]["situacion"]) == (PG.A_TIEMPO, PG.VENCIDO,
                                                                                          PG.PENDIENTE)
    assert por["im3"]["contrato"] == "0147" and por["im5"]["situacion"] == PG.SIN_FECHA and por["im5"]["mes"] is None
    assert por["im1"]["mes"] == D(2026, 8, 1) and por["im1"]["responsable_linea"] == "Luciano"
    assert set(filas[0]) == set(E.columnas("programa_entregables"))
    assert PG.filas_entregables(P, "FIN", TAREAS_INF, CORTE, E.PRELIMINAR, "x") == []     # solo_consumo: fuera de la vista
    assert {f["frecuencia"] for f in filas} == {PG.EVENTO}                   # forma corta del patron: evento


def test_reportes_diarios_y_de_alerta():
    p = PG.desde_dict("X", {**CONFIG, "entregables": {
        "informe": {"patron": "^IM-\\d", "frecuencia": "mensual"},
        "reporte_diario": {"patron": "^RD-\\d", "frecuencia": "mensual"},
        "reporte_alerta": {"patron": "^RA-\\d", "frecuencia": "evento"}}})
    tareas = [tarea("f19", "MLC 0019"),
              tarea("rd9", "RD-09 Reportes diarios sep 2026", "f19", "completado", D(2026, 9, 30), D(2026, 9, 30), "done"),
              *[tarea(f"rd9.{i}", f"RD-09.{i:02d} Reporte diario", "rd9", "completado", D(2026, 9, i), D(2026, 9, i), "done")
                for i in (1, 2, 3)],
              tarea("ra1", "RA-01 Reporte de alerta E4", "f19", "to do", D(2026, 9, 28)),
              tarea("ra2", "RA-02 Reporte de alerta E6", "f19", "completado", D(2026, 9, 10), D(2026, 9, 9), "done")]
    por = {f["task_id"]: f for f in PG.filas_entregables(p, "INF", tareas, CORTE, E.PRELIMINAR, "x")}
    assert set(por) == {"rd9", "ra1", "ra2"}                                  # los RD diarios van dentro del paquete
    assert (por["rd9"]["tipo_entregable"], por["rd9"]["frecuencia"], por["rd9"]["mes"]) == ("reporte_diario", PG.MENSUAL,
                                                                                            D(2026, 9, 1))
    assert (por["ra1"]["frecuencia"], por["ra1"]["situacion"], por["ra1"]["dias_atraso"]) == (PG.EVENTO, PG.VENCIDO, 3)
    assert por["ra2"]["situacion"] == PG.A_TIEMPO and por["ra2"]["contrato"] == "0019"
    with pytest.raises(ValueError, match="frecuencia semanal"):
        PG.desde_dict("X", {**CONFIG, "entregables": {"x": {"patron": "^X-", "frecuencia": "semanal"}}})


def test_fusion_de_las_pestanas_del_programa():
    viejas, nuevas = [{"programa": "CMP", "list_id": "INF", "mes": D(2026, 8, 1)}], [{"programa": "CMP", "list_id": "G19"}]
    for t in E.PROGRAMAS:
        assert A.fusionar(t, viejas, nuevas, CORTE) == nuevas                  # corrida completa: se reemplaza todo
        assert A.fusionar(t, viejas, [], CORTE, alcance={"INF"}) == viejas     # --solo: no se toca


def test_compartidas_en_contratos_y_por_fase():
    horas = PG.horas_de_lista(P, "INF", TAREAS_INF, [(D(2026, 8, 3), 4.0, "im1"), (D(2026, 8, 4), 1.5, "x"),
                                                     (D(2026, 9, 2), 2.0, "fgen"), (D(2026, 9, 3), 1.0, "borrada")], [])
    assert PG.compartidas_por_fase(horas, CORTE) == {("INF", "PJ-2025.0147/.0019 Visitas"): 1.5,
                                                     ("INF", "Tareas Generales"): 2.0,
                                                     ("INF", "(tarea que ya no está en la lista)"): 1.0}
    filas = PG.filas_contratos(P, horas, CORTE, E.OFICIAL)
    ago = [f for f in filas if f["mes"] == D(2026, 8, 1)]
    sep = [f for f in filas if f["mes"] == D(2026, 9, 1)]
    assert {f["contrato"] for f in ago} == {"0019", "0147"}
    assert all(f["hh_compartidas_mes"] == 1.5 and f["hh_compartidas_acum"] == 1.5 for f in ago)   # igual en cada contrato
    assert all(f["hh_compartidas_mes"] == 3.0 and f["hh_compartidas_acum"] == 4.5 for f in sep)
    assert all(f["hh_compartidas_mes"] is None for f in filas if f["es_futuro"])


def test_fase_compartida_aceptada_no_avisa_pero_suma():
    p = PG.desde_dict("X", {**CONFIG, "compartidas_aceptadas": [{"list_id": "INF", "fase": "tareas generales "}]})
    horas = PG.horas_de_lista(p, "INF", TAREAS_INF, [(D(2026, 8, 4), 1.5, "x"), (D(2026, 9, 2), 2.0, "fgen")], [])
    assert PG.compartidas_a_advertir(p, horas, CORTE) == {("INF", "PJ-2025.0147/.0019 Visitas"): 1.5}
    assert PG.compartidas_a_advertir(P, horas, CORTE) == PG.compartidas_por_fase(horas, CORTE)    # sin aceptadas
    sep = [f for f in PG.filas_contratos(p, horas, CORTE, E.OFICIAL) if f["mes"] == D(2026, 9, 1)]
    assert all(f["hh_compartidas_mes"] == 2.0 and f["hh_compartidas_acum"] == 3.5 for f in sep)   # la aceptada suma
    solo_aceptada = PG.horas_de_lista(p, "INF", TAREAS_INF, [(D(2026, 9, 2), 2.0, "fgen")], [])
    assert PG.compartidas_a_advertir(p, solo_aceptada, CORTE) == {}                                # sin advertencia
    with pytest.raises(ValueError, match="no es del programa"):
        PG.desde_dict("X", {**CONFIG, "compartidas_aceptadas": [{"list_id": "OTRA", "fase": "x"}]})
    cmp = PG.cargar(PROGRAMAS_JSON)["CMP-SHM"]
    assert cmp.compartida_aceptada("901327789240", "Desarrollo general")                         # decisión 2026-10-06
    assert not cmp.compartida_aceptada("901327788557", "Desarrollo general")


def test_linea_excluida_de_entregables_conserva_sus_horas():
    p = PG.desde_dict("X", {**CONFIG, "entregables_excluir_lineas": ["informes"]})
    assert PG.filas_entregables(p, "INF", TAREAS_INF, CORTE, E.PRELIMINAR, "x") == []
    assert sum(h.horas for h in PG.horas_de_lista(p, "INF", TAREAS_INF, [(D(2026, 8, 3), 4.0, "im1")], [])) == 4.0
    assert P.entregables_excluir_lineas == frozenset()
    assert "modelos" in PG.cargar(PROGRAMAS_JSON)["CMP-SHM"].entregables_excluir_lineas    # decision 2026-10-02


def _ent(tid, nombre, contrato="0147", situacion=PG.A_TIEMPO, due=None, cierre=None, lid="INF"):
    return {"task_id": tid, "nombre": nombre, "contrato": contrato, "situacion": situacion, "fecha_entrega": due,
            "fecha_cierre": cierre, "list_id": lid}


def test_revisar_entregables():
    filas = [_ent("a", "VT-02 Visita N°x - Feb 2026", situacion=PG.SIN_FECHA, lid="G"),
             _ent("b", "VT-02 Visita de Mantención e Inspección", situacion=PG.VENCIDO, due=D(2026, 8, 14), lid="G"),
             _ent("c", "VT-03 Visita N°y - Abr 2026", situacion=PG.A_TIEMPO, due=D(2026, 4, 6), cierre=D(2026, 4, 6), lid="G"),
             _ent("d", "IM-02 Informe Mensual N°2", due=D(2026, 8, 21), cierre=D(2026, 8, 14)),
             _ent("e", "IM-02 Informe Mensual N°3", due=D(2026, 8, 20), cierre=D(2026, 8, 21)),
             _ent("f", "IM-02 Informe Mensual N°2", contrato="0019", due=D(2026, 8, 14), cierre=D(2026, 5, 28)),
             _ent("g", "IM-06.0 Informe Levantamiento", contrato="0019"), _ent("h", "IM-06 Informe Mensual N°6", contrato="0019")]
    out = PG.revisar_entregables(P, filas)
    assert [(x.tipo, x.task_id) for x in out] == [("plantilla", "a"), ("duplicado", ""), ("fecha", "f")]
    dup = out[1]
    assert dup.tarea == "IM-02" and dup.datos["contrato"] == "Apilador" and len(dup.datos["nombres"]) == 2
    assert out[2].datos["dias"] == 78
    # La plantilla cerrada (c) no se avisa; la plantilla no cuenta como duplicado de VT-02 (b)
    assert PG.revisar_entregables(PG.desde_dict("X", {**CONFIG, "dias_cierre_anticipado": 90}), filas)[-1].tipo != "fecha"
