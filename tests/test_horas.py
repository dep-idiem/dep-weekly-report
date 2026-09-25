"""Reglas de conteo de horas (peritaje, seccion 7) y reglas por persona (fase 5)."""
import datetime as dt

from dep_clickup.config import TZ
from dep_reportes import horas as H, personas as PERS, proyecto as P
from dep_reportes.metricas import Horas, TareaMetrica
from dep_reportes.modos import por_nombre

D = dt.date
HOY = D(2026, 9, 25)


def _raw(i, uid=1, task="t1", inicio="2026-09-01 09:00", horas=2.0, source="clickup", lista="L"):
    ini = dt.datetime.strptime(inicio, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    ms = int(ini.timestamp() * 1000)
    dur = int(horas * 3_600_000)
    return {"id": str(i), "user": {"id": uid, "username": f"u{uid}"}, "task": {"id": task, "name": task},
            "task_location": {"list_id": lista}, "start": str(ms), "end": str(ms + max(dur, 0)),
            "duration": str(dur), "source": source, "at": str(ms)}


def test_depurar_clasifica_y_cuenta():
    raw = [_raw(1), _raw(2),                                   # 2 es duplicado exacto de 1
           _raw(3, horas=0), _raw(4, horas=-1),                # duracion <= 0 (timer corriendo)
           _raw(5, inicio="2026-10-01 09:00"),                 # futura
           _raw(6, source="api"),                              # importada
           _raw(7, task="t2"), _raw(8, inicio="2026-09-02 09:00")]
    d = H.depurar(raw, HOY)
    assert [e.id for e in d.nativas] == ["1", "7", "8"]
    assert [e.id for e in d.importadas] == ["6"]
    assert d.conteos() == {"n_importadas_excluidas": 1, "n_duplicadas_excluidas": 1,
                           "n_duracion_no_positiva_excluidas": 2, "n_futuras_excluidas": 1}


def _tt(tid, uid, fecha, horas, proyecto_idx=1, campo="Proyecto v0.1"):
    ms = int(dt.datetime(fecha.year, fecha.month, fecha.day, 8, tzinfo=dt.timezone.utc).timestamp() * 1000)
    opciones = [{"orderindex": 0, "name": "-"}, {"orderindex": 1, "name": "2025.0019 CMP Los Colorados"},
                {"orderindex": 2, "name": "00 Administración"}]
    return {"id": tid, "time_estimate": int(horas * 3_600_000), "assignees": [{"id": uid}] if uid else [],
            "custom_fields": [{"name": "Día ingreso", "type": "date", "value": str(ms)},
                              {"name": "Proyecto v0.1", "type": "drop_down", "value": proyecto_idx if campo == "Proyecto v0.1" else 0,
                               "type_config": {"options": opciones}},
                              {"name": "🧩 Proyecto", "type": "drop_down", "value": proyecto_idx if campo != "Proyecto v0.1" else None,
                               "type_config": {"options": opciones}}]}


def test_parse_timetracker():
    regs = H.parse_timetracker([_tt("a", 1, D(2025, 11, 3), 8), _tt("b", 2, D(2025, 11, 3), 4, campo="🧩 Proyecto"),
                                _tt("c", 1, D(2025, 11, 4), 3, proyecto_idx=2),        # sin codigo: fuera
                                _tt("d", 1, D(2025, 11, 5), 0),                         # sin horas: fuera
                                _tt("e", None, D(2025, 6, 16), 685.1)])                 # saldo mensual sin persona
    assert [(r.task_id, r.usuario_id, r.fecha, r.horas, r.codigo) for r in regs] == [
        ("a", 1, D(2025, 11, 3), 8.0, "2025.0019"), ("b", 2, D(2025, 11, 3), 4.0, "2025.0019"),
        ("e", None, D(2025, 6, 16), 685.1, "2025.0019")]


def test_saldo_historico_y_horas_sin_clickup():
    regs = [H.RegistroTT("a", 1, D(2026, 5, 10), 8, "x"), H.RegistroTT("b", 1, D(2026, 5, 17), 8, "x"),
            H.RegistroTT("c", 1, D(2026, 5, 18), 8, "x"),       # dia del corte historico, con entrada nativa
            H.RegistroTT("d", 2, D(2026, 6, 1), 5, "x"),        # posterior, sin entrada nativa
            H.RegistroTT("e", 2, D(2026, 10, 1), 5, "x")]       # posterior al corte del reporte
    nativas = H.depurar([_raw(1, uid=1, inicio="2026-05-18 09:00")], HOY).nativas
    ch = H.corte_historico(nativas)
    assert ch == D(2026, 5, 18)
    assert H.saldo_historico(regs, ch, D(2026, 9, 20)) == 16
    assert H.tt_sin_clickup(regs, ch, D(2026, 9, 20), nativas) == 5
    assert H.corte_historico(nativas, manual=D(2026, 6, 1)) == D(2026, 6, 1)
    assert H.saldo_historico(regs, None, D(2026, 9, 20)) == 29         # sin nativas: todo hasta el corte
    assert H.saldo_historico(regs, D(2026, 12, 1), D(2026, 5, 15)) == 8  # nunca pasa del corte del reporte


def _tm(id_, nombre, parent=None):
    return TareaMetrica(id_, nombre, parent, D(2026, 8, 1), D(2026, 9, 30), None, 0.0)


TAREAS = [_tm("f0", "00 Administración"), _tm("f4", "04 Análisis"), _tm("p", "4.4 Modelo", "f4"),
          _tm("h", "4.4.1 Losa", "p"), _tm("fx", "PJ-2025.0147 Informes Apilador")]
COMBINADA = TAREAS + [_tm("fy", "PJ-2025.0019 Informes MLC"), _tm("fz", "PJ-2025.0147/.0019 Informes Visitas")]


def test_horas_en_padres():
    horas = [Horas(D(2026, 9, 1), 5, "p"), Horas(D(2026, 9, 1), 2, "h"), Horas(D(2026, 9, 2), 1, "f4")]
    av = H.horas_en_padres(TAREAS, horas)
    assert [(a.tipo, a.task_id, a.datos["horas"]) for a in av] == [
        (P.ADV_HORAS_EN_PADRE, "p", 5), (P.ADV_HORAS_EN_PADRE, "f4", 1)]


def test_horas_en_administracion_sobre_el_umbral_y_el_minimo():
    horas = [Horas(D(2026, 9, 1), 30, "f0"), Horas(D(2026, 9, 1), 70, "h")]
    assert H.horas_en_administracion(TAREAS, horas, 0.2, 20)[0].datos["fraccion"] == 0.3
    assert H.horas_en_administracion(TAREAS, horas, 0.3, 20) == []            # no pasa del umbral
    pocas = [Horas(D(2026, 9, 1), 2, "f0")]                                      # 100 %, pero solo 2 h
    assert H.horas_en_administracion(TAREAS, pocas, 0.2, 20) == []
    assert H.horas_en_administracion(TAREAS, pocas, 0.2, 0)[0].datos["fraccion"] == 1


def test_horas_fuera_de_plazo():
    horas = [Horas(D(2026, 7, 31), 2, "h"), Horas(D(2026, 8, 15), 3, "h"), Horas(D(2026, 10, 2), 4, "h")]
    a = H.horas_fuera_de_plazo(horas, D(2026, 8, 1), D(2026, 9, 30))[0]
    assert (a.datos["n_antes"], a.datos["h_antes"], a.datos["n_despues"], a.datos["h_despues"]) == (1, 2, 1, 4)
    assert H.horas_fuera_de_plazo(horas[1:2], D(2026, 8, 1), None) == []


def test_codigos_en_nombre():
    assert H.codigos_en_nombre("PJ-2025.0019-0147 | Desarrollo Informes | CMP") == {
        "2025.0019-0147", "2025.0019", "2025.0147"}
    assert H.codigos_en_nombre("PJ-2026.0152 | Nestlé | NESTLE") == {"2026.0152"}


def test_fases_de_otro_proyecto_acepta_los_codigos_de_la_lista():
    assert H.fases_de_otro_proyecto(COMBINADA, "PJ-2025.0019-0147 | Informes | CMP") == []
    av = H.fases_de_otro_proyecto(COMBINADA, "PJ-2025.0019 | Monitoreo | CMP")
    assert [(a.task_id, a.datos["codigo_fase"]) for a in av] == [("fx", "2025.0147"), ("fz", "2025.0147")]


def test_lista_combinada():
    a = H.lista_combinada(COMBINADA)
    assert len(a) == 1 and a[0].tipo == P.ADV_LISTA_COMBINADA and a[0].datos["codigos"] == ["2025.0019", "2025.0147"]
    assert P.ADV_LISTA_COMBINADA in P.NIVEL_PROYECTO
    assert H.lista_combinada(TAREAS) == []                     # una sola fase con codigo


def test_aviso_tt_sin_clickup_con_minimo():
    assert H.aviso_tt_sin_clickup(0.2, D(2026, 5, 18)) == []
    assert H.aviso_tt_sin_clickup(12.0, D(2026, 5, 18))[0].tipo == P.ADV_TT_SIN_CLICKUP


def test_calcular_suma_el_saldo_historico_solo_en_metricas():
    tm = [TareaMetrica("a", "Tarea", None, D(2026, 9, 1), D(2026, 9, 30), 100.0, 0.5)]
    horas = [Horas(D(2026, 9, 10), 10, "a")]
    r0 = P.calcular(tm, tm, horas, D(2026, 9, 20), D(2026, 9, 30), por_nombre("dep"))
    r1 = P.calcular(tm, tm, horas, D(2026, 9, 20), D(2026, 9, 30), por_nombre("dep"), hh_historicas=500)
    assert r1.metricas["hh_gastadas_acum"] == r0.metricas["hh_gastadas_acum"] + 500 == 510
    assert r1.metricas["hh_historicas"] == 500
    assert r1.metricas["hh_estimadas_al_termino"] == r0.metricas["hh_estimadas_al_termino"] + 500
    assert r1.metricas["cpi"] == 50 / 510
    assert r1.fases == r0.fases                                                   # las fases no cambian
    # Sin fecha de corte historico, toda la serie de gastadas sube en el saldo
    assert [p.gastadas for p in r1.serie] == [None if g is None else g + 500 for g in (p.gastadas for p in r0.serie)]
    # Con fecha: vacia antes del corte historico, parte en el saldo y termina en el valor de metricas_semanales
    r2 = P.calcular(tm, tm, horas, D(2026, 9, 20), D(2026, 9, 30), por_nombre("dep"), hh_historicas=500,
                    desde_historico=D(2026, 9, 5))
    serie = {p.fecha: p for p in r2.serie}
    assert serie[D(2026, 9, 4)].gastadas is None and serie[D(2026, 9, 5)].gastadas == 500
    assert serie[D(2026, 9, 20)].gastadas == r2.metricas["hh_gastadas_acum"] == 510
    assert r2.serie[-1].proyectadas == r2.metricas["hh_estimadas_al_termino"]
    # Corte historico posterior al corte del reporte: la serie parte en el corte
    r3 = P.calcular(tm, tm, horas, D(2026, 9, 20), D(2026, 9, 30), por_nombre("dep"), hh_historicas=500,
                    desde_historico=D(2026, 9, 23))
    assert {p.fecha: p for p in r3.serie}[D(2026, 9, 20)].gastadas == 510


def test_para_hoja_filtra_time_estimate_y_muestra_padres():
    adv = [{"tipo": "hh_distinta_de_time_estimate", "task_id": "con_hh"},
           {"tipo": P.ADV_HORAS_EN_PADRE, "task_id": "sin_hh"},
           {"tipo": "hh_en_tarea_no_hoja", "task_id": "con_hh"}]
    assert [a["tipo"] for a in P.para_hoja(adv, {"con_hh"})] == [P.ADV_HORAS_EN_PADRE, "hh_en_tarea_no_hoja"]


# --- Reglas por persona (no van a la hoja) ------------------------------------------------------------

def test_reglas_por_persona():
    raw = [_raw(1, inicio="2026-09-01 08:00", horas=6), _raw(2, task="t2", inicio="2026-09-01 13:00", horas=4),
           _raw(3, task="t3", inicio="2026-09-02 08:00", horas=10.5), _raw(4, uid=2, inicio="2026-09-01 08:00", horas=6)]
    r = PERS.calcular(H.depurar(raw, HOY).nativas)
    assert [(d.usuario_id, d.fecha, d.horas) for d in r.dias_sobre_tope] == [(1, D(2026, 9, 1), 10), (1, D(2026, 9, 2), 10.5)]
    assert [(s.entrada_a, s.entrada_b, s.horas) for s in r.superposiciones] == [("1", "2", 1.0)]
    assert [(x.entrada, x.horas) for x in r.entradas_largas] == [("3", 10.5)]
