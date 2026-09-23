import datetime as dt

import pytest

from dep_clickup.config import TZ
from dep_reportes import almacen as A, controles as CTL, esquema as E
from dep_reportes.worker import planificar

D = dt.date
UTC = dt.timezone.utc
OF, PR = E.OFICIAL, E.PRELIMINAR


def fila(corte, tipo, lid="L", v=0):
    return {"corte": corte, "tipo_corte": tipo, "list_id": lid, "v": v}


def correr(existentes, corte, tipo, lids=("L",), v=1, tabla="metricas_semanales", retencion=15):
    nuevas = [fila(corte, tipo, l, v) for l in lids]
    return A.completar(tabla, A.fusionar(tabla, existentes, nuevas, corte, None, tipo, retencion), {})


def resumen(filas):
    return sorted((f["corte"], f["tipo_corte"], f["v"], f["es_ultimo_corte"], f["es_ultimo_oficial"]) for f in filas)


# --- Modelo de datos: preliminar / oficial --------------------------------------------------------

def test_preliminar_sobre_preliminar_reemplaza_su_corte_y_conserva_15_dias():
    s = correr([], D(2026, 9, 21), PR, v=1)
    s = correr(s, D(2026, 9, 22), PR, v=2)
    s = correr(s, D(2026, 9, 22), PR, v=3)            # misma fecha de control: reemplaza
    assert resumen(s) == [(D(2026, 9, 21), PR, 1, False, False), (D(2026, 9, 22), PR, 3, True, False)]


def test_retencion_de_preliminares():
    s = []
    for d in range(1, 21):                            # 20 preliminares diarias (sin oficiales entre medio)
        s = correr(s, D(2026, 10, d), PR, v=d)
    cortes = sorted(f["corte"] for f in s)
    assert cortes[0] == D(2026, 10, 6) and cortes[-1] == D(2026, 10, 20) and len(cortes) == 15
    # la ventana es un parametro
    assert len(correr(s, D(2026, 10, 21), PR, retencion=3)) == 3


def test_oficial_sobre_preliminares_borra_las_de_su_domingo_o_antes():
    s = [fila(D(2026, 9, 26), PR, v=1), fila(D(2026, 9, 27), PR, v=2), fila(D(2026, 9, 28), PR, v=3),
         fila(D(2026, 9, 20), OF, v=0)]
    s = correr(s, D(2026, 9, 27), OF, v=9)
    assert resumen(s) == [(D(2026, 9, 20), OF, 0, False, False), (D(2026, 9, 27), OF, 9, False, True),
                          (D(2026, 9, 28), PR, 3, True, False)]


def test_oficial_repetida_es_idempotente():
    s = correr([fila(D(2026, 9, 20), OF)], D(2026, 9, 27), OF, v=5)
    assert correr(s, D(2026, 9, 27), OF, v=5) == s
    assert len([f for f in s if f["corte"] == D(2026, 9, 27)]) == 1


def test_preliminar_despues_de_oficial_no_toca_oficiales():
    s = correr([], D(2026, 9, 27), OF, v=1)
    s = correr(s, D(2026, 9, 29), PR, v=2)
    assert resumen(s) == [(D(2026, 9, 27), OF, 1, False, True), (D(2026, 9, 29), PR, 2, True, False)]


def test_banderas_a_igual_corte_la_preliminar_es_la_mas_reciente():
    s = correr([fila(D(2026, 9, 27), OF, v=1)], D(2026, 9, 27), PR, v=2)   # preliminar manual con el mismo corte
    assert resumen(s) == [(D(2026, 9, 27), OF, 1, False, True), (D(2026, 9, 27), PR, 2, True, False)]


def test_filas_antiguas_sin_tipo_son_oficiales():
    viejas = [{"corte": D(2026, 9, 20), "list_id": "L", "v": 0}]
    s = correr(viejas, D(2026, 9, 22), PR, v=1)
    assert resumen(s) == [(D(2026, 9, 20), OF, 0, False, True), (D(2026, 9, 22), PR, 1, True, False)]


def test_fotos_solo_en_oficiales():
    exist = [{"corte": D(2026, 9, 20), "list_id": "L", "task_id": "t"}]
    nuevas = [{"corte": D(2026, 9, 22), "list_id": "L", "task_id": "t"}]
    assert A.fusionar("fotos_tareas", exist, nuevas, D(2026, 9, 22), None, PR) == exist
    assert len(A.fusionar("fotos_tareas", exist, nuevas, D(2026, 9, 27), None, OF)) == 2


def test_serie_diaria_se_reemplaza_en_cualquier_corrida():
    exist = [{"corte": D(2026, 9, 20), "tipo_corte": OF, "list_id": "L", "fecha": D(2026, 9, 1)}]
    nuevas = [{"corte": D(2026, 9, 22), "tipo_corte": PR, "list_id": "L", "fecha": D(2026, 9, 1)}]
    assert A.fusionar("serie_diaria", exist, nuevas, D(2026, 9, 22), None, PR) == nuevas


def test_columnas_nuevas_de_la_fase_3():
    for t in ("metricas_semanales", "metricas_fase", "advertencias", "serie_diaria", "ejecuciones"):
        assert "tipo_corte" in E.columnas(t), t
    for t in ("metricas_semanales", "metricas_fase", "advertencias"):
        assert E.tipos(t)["es_ultimo_oficial"] == E.BOOLEANO
    assert "corte" in E.columnas("serie_diaria")


# --- Ventana horaria ------------------------------------------------------------------------------

def utc(*a):
    return dt.datetime(*a, tzinfo=UTC)


def test_offsets_de_chile_2026():
    assert dt.datetime(2026, 4, 4, 12, tzinfo=TZ).utcoffset() == dt.timedelta(hours=-3)
    assert dt.datetime(2026, 4, 6, 12, tzinfo=TZ).utcoffset() == dt.timedelta(hours=-4)   # termina el horario de verano
    assert dt.datetime(2026, 9, 5, 12, tzinfo=TZ).utcoffset() == dt.timedelta(hours=-4)
    assert dt.datetime(2026, 9, 7, 12, tzinfo=TZ).utcoffset() == dt.timedelta(hours=-3)   # empieza


@pytest.mark.parametrize("ahora, tipo, corte", [
    # Oficial, horario de verano (UTC-3): 07:00 UTC = 04:00 local
    (utc(2026, 9, 28, 7, 0), OF, D(2026, 9, 27)),
    (utc(2026, 9, 28, 8, 45), OF, D(2026, 9, 27)),        # 05:45 local, cron atrasado
    # Oficial, horario de invierno (UTC-4): 08:00 UTC = 04:00 local
    (utc(2026, 6, 1, 8, 0), OF, D(2026, 5, 31)),
    # Preliminar, verano: 22:00 UTC = 19:00 local; 23:00 UTC = 20:00
    (utc(2026, 9, 29, 22, 0), PR, D(2026, 9, 28)),
    (utc(2026, 9, 29, 23, 30), PR, D(2026, 9, 28)),
    # Preliminar, invierno: 23:00 UTC = 19:00 local
    (utc(2026, 6, 2, 23, 0), PR, D(2026, 6, 1)),
    # Domingo: preliminar con control sabado
    (utc(2026, 10, 4, 22, 0), PR, D(2026, 10, 3)),
    # Dia del cambio de horario de septiembre (domingo 6): 22:00 UTC = 19:00 local (ya en UTC-3)
    (utc(2026, 9, 6, 22, 0), PR, D(2026, 9, 5)),
    # Lunes siguiente al cambio de septiembre: 07:00 UTC = 04:00 local
    (utc(2026, 9, 7, 7, 0), OF, D(2026, 9, 6)),
    # Dia del cambio de horario de abril (domingo 5): 23:00 UTC = 19:00 local (ya en UTC-4)
    (utc(2026, 4, 5, 23, 0), PR, D(2026, 4, 4)),
    # Lunes siguiente al cambio de abril: 08:00 UTC = 04:00 local
    (utc(2026, 4, 6, 8, 0), OF, D(2026, 4, 5)),
])
def test_dentro_de_ventana(ahora, tipo, corte):
    p = planificar(ahora, "schedule")
    assert (p.ejecutar, p.tipo, p.corte) == (True, tipo, corte), p.motivo


@pytest.mark.parametrize("ahora", [
    utc(2026, 6, 1, 7, 0),     # lunes invierno: 03:00 local
    utc(2026, 9, 28, 9, 0),    # lunes 06:00 local
    utc(2026, 6, 2, 22, 0),    # martes invierno: 18:00 local
    utc(2026, 9, 29, 0, 5),    # martes 21:05 local (lunes 28 en UTC... es martes 29 00:05 UTC = lunes 21:05 local)
    utc(2026, 9, 28, 22, 0),   # lunes 19:00 local: no hay preliminar los lunes
    utc(2026, 9, 29, 7, 0),    # martes 04:00 local: la oficial es solo los lunes
    utc(2026, 4, 5, 22, 0),    # domingo del cambio de abril: 18:00 local
    utc(2026, 4, 6, 7, 0),     # lunes siguiente al cambio de abril: 03:00 local
])
def test_fuera_de_ventana(ahora):
    p = planificar(ahora, "schedule")
    assert not p.ejecutar and "Fuera de ventana" in p.motivo


def test_no_repite_una_corrida_exitosa_del_mismo_tipo_y_dia():
    hecha = [{"modo": "escritura", "resultado": "ok", "tipo_corte": PR,
              "ejecutado_en": dt.datetime(2026, 9, 29, 19, 2, tzinfo=TZ)}]
    assert not planificar(utc(2026, 9, 29, 23, 0), "schedule", hecha).ejecutar
    # una fallida o un dry-run no cuentan
    for otra in ({"resultado": "error"}, {"modo": "dry_run"}, {"resultado": "control_fallido"}):
        assert planificar(utc(2026, 9, 29, 23, 0), "schedule", [dict(hecha[0], **otra)]).ejecutar
    # otro tipo el mismo dia no bloquea
    assert planificar(utc(2026, 9, 28, 7, 0), "schedule", [dict(hecha[0], ejecutado_en=dt.datetime(
        2026, 9, 28, 1, tzinfo=TZ))]).ejecutar


def test_manual_ignora_ventana_y_calcula_corte():
    p = planificar(utc(2026, 9, 30, 15, 0), "workflow_dispatch", tipo=OF)
    assert (p.ejecutar, p.corte) == (True, D(2026, 9, 27))
    p = planificar(utc(2026, 9, 28, 15, 0), "workflow_dispatch", tipo=OF)          # lunes: el domingo de ayer
    assert p.corte == D(2026, 9, 27)
    p = planificar(utc(2026, 9, 30, 15, 0), "workflow_dispatch", tipo=PR)
    assert p.corte == D(2026, 9, 29)
    p = planificar(utc(2026, 9, 30, 15, 0), "workflow_dispatch", tipo=PR, corte=D(2026, 9, 25))
    assert p.corte == D(2026, 9, 25)
    with pytest.raises(SystemExit):
        planificar(utc(2026, 9, 30, 15, 0), "workflow_dispatch", tipo=OF, corte=D(2026, 9, 26))


def test_manual_respeta_deduplicacion_salvo_dry_run():
    hecha = [{"modo": "escritura", "resultado": "ok", "tipo_corte": PR,
              "ejecutado_en": dt.datetime(2026, 9, 30, 10, tzinfo=TZ)}]
    assert not planificar(utc(2026, 9, 30, 15, 0), "workflow_dispatch", hecha, tipo=PR).ejecutar
    assert planificar(utc(2026, 9, 30, 15, 0), "workflow_dispatch", hecha, tipo=PR, dry_run=True).ejecutar


# --- Controles de cordura -------------------------------------------------------------------------

U = CTL.Umbrales()
C = D(2026, 9, 27)


def P(lid="L", rev=0, lb_hh=100.0, total=100.0, prog=10.0, av=0.1):
    return CTL.ProyectoControl(lid, lid, rev, lb_hh, total, prog, av)


def test_controles_ok():
    assert CTL.verificar(C, [D(2026, 9, 25)], [P()], [], [], U) == []


def test_cero_horas_en_7_dias():
    f = CTL.verificar(C, [D(2026, 9, 20)], [P()], [], [], U)
    assert len(f) == 1 and "Cero entradas" in f[0]
    assert CTL.verificar(C, [D(2026, 9, 21)], [P()], [], [], U) == []      # el 21 esta dentro de los 7 dias


def test_caida_de_proyectos():
    prev = [{"modo": "escritura", "resultado": "ok", "n_proyectos": 16, "ejecutado_en": dt.datetime(2026, 9, 21, tzinfo=TZ)}]
    ps = [P(str(i)) for i in range(12)]                                      # 16 -> 12 = 25 %
    assert any("cae" in x for x in CTL.verificar(C, [C], ps, prev, [], U))
    assert CTL.verificar(C, [C], ps + [P("x")], prev, [], U) == []          # 13 = 18,75 %
    assert CTL.verificar(C, [C], ps, prev, [], U, parcial=True) == []


def test_linea_base_sin_metricas_y_total_hh_cambiado():
    f = CTL.verificar(C, [C], [P(prog=None)], [], [], U)
    assert any("sin métricas" in x for x in f)
    f = CTL.verificar(C, [C], [P(total=110.0)], [], [], U)
    assert any("inmutable" in x for x in f)
    previas = [{"list_id": "L", "rev_linea_base": 0, "total_hh": 90.0, "corte": D(2026, 9, 20)}]
    assert any("publicado" in x for x in CTL.verificar(C, [C], [P()], [], previas, U))
    assert CTL.verificar(C, [C], [P(rev=None, lb_hh=None, total=None, prog=None, av=None)], [], [], U) == []


def test_umbrales_desde_config(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"dias_ventana_horas": 3, "caida_max_proyectos": 0.5}', encoding="utf-8")
    u = CTL.cargar_umbrales(p)
    assert (u.dias_ventana_horas, u.caida_max_proyectos) == (3, 0.5)


# --- Respaldo y restauracion ----------------------------------------------------------------------

def test_respaldo_csv_ida_y_vuelta(tmp_path):
    filas = {"metricas_semanales": [{c: None for c in E.columnas("metricas_semanales")} | {
        "corte": D(2026, 9, 20), "tipo_corte": OF, "es_ultimo_corte": True, "es_ultimo_oficial": False,
        "list_id": "901", "codigo": "PJ-1", "total_hh": 605.0, "n_advertencias": 3}],
        "ejecuciones": [{c: None for c in E.columnas("ejecuciones")} | {
            "ejecutado_en": dt.datetime(2026, 9, 23, 16, 13, 45, tzinfo=TZ), "corte": D(2026, 9, 20),
            "modo": "escritura", "n_proyectos": 16, "resultado": "ok"}]}
    A.AlmacenCsv(tmp_path).escribir(filas)
    assert A.AlmacenCsv(tmp_path).leer() == filas
