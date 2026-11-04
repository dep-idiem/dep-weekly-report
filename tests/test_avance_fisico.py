"""Avance físico calculado (dep_reportes/avance.py, TAREA_avance_fisico 2026-11-04)."""
import datetime as dt

from dep_clickup.client import parse_task
from dep_clickup.config import TZ
from dep_clickup.models import CustomField, ListInfo, Task, TimeEntry
from dep_reportes import avance as AV, esquema as E, mensajes_jp as MJ, presentacion as PR, reproceso as REP, run
from dep_reportes.modos import por_nombre

D = dt.date
CORTE = D(2026, 11, 1)
AHORA = dt.datetime(2026, 11, 2, 8, tzinfo=TZ)
DEP = por_nombre("dep")
LISTA = ListInfo("L", "PJ-2026.0177 | Revisión estructural | U. de Los Lagos", "green", False, "F", "S", 9,
                 start=dt.datetime(2026, 10, 1, tzinfo=TZ), due=dt.datetime(2026, 11, 27, tzinfo=TZ))
H = 3_600_000


def _ms(d):
    return dt.datetime(d.year, d.month, d.day, 9, tzinfo=TZ) if d else None


def _t(id_, nombre, parent=None, hh=None, s=None, d=None, te=None, estado="to do", tipo="custom", avance=None,
       chk=(0, 0)):
    cf = {"HH Presupuestadas": CustomField("1", "HH Presupuestadas", "number", hh, hh),
          "Avance Real": CustomField("2", "Avance Real", "manual_progress", avance, avance)}
    return Task(id_, nombre, parent, estado, "L", _ms(s), _ms(d), int(te * H) if te else None, (), cf,
                status_type=tipo, checklist_total=chk[0], checklist_resueltos=chk[1])


def _cerrada(id_, nombre, parent, te, d=None):
    return _t(id_, nombre, parent, te=te, d=d, estado="completado", tipo="done")


def _calc(ts, horas=None, corte=CORTE):
    hh = {t.id: t.cf("HH Presupuestadas") for t in ts if t.cf("HH Presupuestadas")}
    return AV.calcular(ts, hh, horas or {}, corte), hh


# --- A. Definición por tarea -------------------------------------------------------------------------------------

def test_cerrada_vale_100_aunque_tenga_porciones_abiertas():
    av, _ = _calc([_t("p", "5.1", hh=10, estado="completado", tipo="done"), _t("x", "Modelación", "p", te=8)])
    assert (av["p"].avance, av["p"].modo) == (1.0, AV.CERRADA)


def test_porciones_ponderadas_por_estimate_de_cualquier_nivel_sin_no_aplica():
    ts = [_t("p", "5.2", hh=40),
          _cerrada("a", "Modelación · 05-oct", "p", 12),
          _t("g", "Agrupador", "p"),                                   # sin estimate: se baja a sus hijas
          _cerrada("b", "Cálculo · 12-oct", "g", 4),
          _t("c", "Informe · 19-oct", "g", te=8),
          _t("n", "Planos · 26-oct", "p", te=20, estado="no aplica", tipo="closed"),   # fuera del denominador
          _t("k", "Visita", "p", te=6, estado="cancelado", tipo="closed")]
    av, _ = _calc(ts)
    assert av["p"].modo == AV.PORCIONES
    assert av["p"].avance == (12 + 4) / (12 + 4 + 8)
    assert (av["p"].hh_porciones, av["p"].hh_cerradas) == (24, 16)


def test_porcion_con_porciones_debajo_no_cuenta_dos_veces():
    ts = [_t("p", "5.3", hh=10), _t("g", "Semana", "p", te=10), _cerrada("a", "Lun", "g", 4), _t("b", "Mar", "g", te=6)]
    av, _ = _calc(ts)
    assert av["p"].avance == 4 / 10 and av["p"].hh_porciones == 10


def test_sin_porciones_usa_checklist_propio():
    av, _ = _calc([_t("c", "08 Revisión", hh=10, chk=(4, 1))])
    assert (av["c"].avance, av["c"].modo) == (0.25, AV.CHECKLIST)


def test_porciones_mandan_sobre_checklist():
    av, _ = _calc([_t("c", "08 Revisión", hh=10, chk=(4, 4)), _t("x", "Revisión · 26-oct", "c", te=5)])
    assert (av["c"].avance, av["c"].modo) == (0.0, AV.PORCIONES)


def test_todas_las_porciones_no_aplica_cae_al_checklist_o_consumo():
    ts = [_t("c", "6.1", hh=10), _t("x", "No va", "c", te=5, estado="no aplica", tipo="closed")]
    av, _ = _calc(ts, {"c": 4.0})
    assert (av["c"].avance, av["c"].modo) == (0.4, AV.CONSUMO)


def test_consumo_con_tope_90_y_el_manual_solo_informativo():
    av, _ = _calc([_t("c", "6.1", hh=10, avance=0.7), _t("d", "6.2", hh=10)], {"c": 3.0, "d": 25.0})
    assert (av["c"].avance, av["c"].modo, av["c"].manual) == (0.3, AV.CONSUMO, 0.7)
    assert av["d"].avance == 0.9


# --- Proyecto: ponderado por HH, modo, manual, vencidas ----------------------------------------------------------

def test_resumen_ponderado_y_modo():
    ts = [_t("a", "5.1", hh=30), _cerrada("a1", "x", "a", 10), _t("a2", "y", "a", te=10),        # 50 % porciones
          _t("b", "5.2", hh=10, chk=(2, 2)),                                                     # 100 % checklist
          _t("c", "5.3", hh=60, estado="completado", tipo="done")]                               # 100 % cerrada
    av, hh = _calc(ts)
    r = AV.resumen(av, hh)
    assert r["avance_fisico"] == (0.5 * 30 + 10 + 60) / 100
    assert r["avance_fisico_modo"] == AV.MIXTO
    assert r["avance_manual"] is None                                   # nadie usa el campo
    assert AV.resumen(av, {"a": 30, "c": 60})["avance_fisico_modo"] == AV.PORCIONES   # las cerradas no cuentan
    assert AV.resumen(av, {"c": 60})["avance_fisico_modo"] == AV.CERRADA
    assert AV.resumen({}, {})["avance_fisico"] is None


def test_vencida_abierta_con_mitad_de_horas_y_avance_si_se_cierran():
    ts = [_t("p", "5.1", hh=40),
          _cerrada("a", "Modelación · 12-oct", "p", 8, D(2026, 10, 16)),
          _t("b", "Modelación · 19-oct", "p", te=12, d=D(2026, 10, 23)),     # 11 de 12 h: se avisa
          _t("c", "Modelación · 26-oct", "p", te=10, d=D(2026, 10, 30)),     # 4 de 10 h: no
          _t("d", "Modelación · 02-nov", "p", te=10, d=D(2026, 11, 6))]      # no ha vencido
    av, hh = _calc(ts, {"b": 11.0, "c": 4.0, "d": 9.0})
    v = av["p"].vencidas
    assert [x.task_id for x in v] == ["b"] and (v[0].horas, v[0].estimado, v[0].due) == (11.0, 12.0, D(2026, 10, 23))
    r = AV.resumen(av, hh)
    assert r["avance_fisico"] == 8 / 40
    assert (r["n_porciones_vencidas_abiertas"], r["hh_porciones_vencidas_abiertas"]) == (1, 12)
    assert r["avance_fisico_si_cerradas"] == 20 / 40
    assert PR.mensaje("porcion_vencida_abierta", None, {"nombre": "Modelación · 19-oct", "due": D(2026, 10, 23),
                                                        "horas": 11.0, "estimado": 12.0}) == \
        "“Modelación · 19-oct” venció el 23-10, lleva 11 de 12 h y sigue abierta: si terminó, cerrarla"


def test_parse_task_lee_checklists():
    t = parse_task({"id": "1", "name": "08 Revisión", "checklists": [
        {"name": "Pasos", "items": [{"name": "a", "resolved": True}, {"name": "b", "resolved": False}]},
        {"name": "Otro", "items": [{"name": "c", "resolved": True}]}]})
    assert (t.checklist_total, t.checklist_resueltos) == (3, 2)
    assert (parse_task({"id": "2", "name": "x"}).checklist_total, parse_task({"id": "2", "name": "x"}).checklist_resueltos) == (0, 0)


# --- Integración con run -----------------------------------------------------------------------------------------

def _e(id_, tarea, d, horas):
    ini = dt.datetime(d.year, d.month, d.day, 9, tzinfo=TZ)
    return TimeEntry(id_, 1, "Ana", tarea, tarea, "L", ini, ini + dt.timedelta(hours=horas), int(horas * H))


def _tareas():
    return [_t("f", "05 Ingeniería"),
            _t("p", "5.1 Modelo", "f", hh=40, s=D(2026, 10, 5), d=D(2026, 11, 20), avance=0.9),
            _cerrada("a", "Modelación · 12-oct", "p", 8, D(2026, 10, 16)),
            _t("b", "Modelación · 19-oct", "p", te=12, d=D(2026, 10, 23)),
            _t("c", "Modelación · 02-nov", "p", te=20, d=D(2026, 11, 6)),
            _t("q", "5.2 Informe", "f", hh=10, s=D(2026, 11, 2), d=D(2026, 11, 20))]


def _procesar(tareas, entradas=()):
    return run.procesar_lista(LISTA, tareas, list(entradas), [], CORTE, DEP, [], True, False, AHORA)


def test_run_usa_avance_fisico_y_no_el_manual():
    r = _procesar(_tareas(), [_e("1", "a", D(2026, 10, 14), 8), _e("2", "b", D(2026, 10, 21), 11)])
    m = r.resultado.metricas
    assert m["avance_real"] == (8 / 40 * 40 + 0) / 50                  # avance_real (obsoleto) = avance_fisico
    assert r.avance["avance_fisico"] == m["avance_real"]
    assert r.avance["avance_fisico_modo"] == AV.MIXTO                  # porciones + consumo
    assert r.avance["avance_manual"] == 0.9 * 40 / 50
    assert r.origen_avance == {"p": AV.PORCIONES, "q": AV.CONSUMO}
    assert m["consumo_pct"] == 19 / 50
    out = run.filas_de(r, CORTE, DEP, AHORA)
    p, ms = out["proyectos"][0], out["metricas_semanales"][0]
    for f in (p, ms):
        assert {c for c, _ in E.AVANCE_FISICO} <= set(f)
        assert f["n_porciones_vencidas_abiertas"] == 1 and f["hh_porciones_vencidas_abiertas"] == 12
        assert f["avance_fisico_si_cerradas"] == 20 / 50 and f["consumo_pct"] == 19 / 50
    fase = out["metricas_fase"][0]
    assert fase["avance_fisico"] == fase["avance_real"] == m["avance_real"] and fase["avance_fisico_modo"] == AV.MIXTO
    adv = [a for a in out["advertencias"] if a["tipo"] == "porcion_vencida_abierta"]
    assert len(adv) == 1 and adv[0]["task_id"] == "b" and adv[0]["responsable_accion"] == "JP"
    assert adv[0]["mensaje"] == "“Modelación · 19-oct” venció el 23-10, lleva 11 de 12 h y sigue abierta: si terminó, cerrarla"
    tipos = {a["tipo"] for a in r.advertencias_todas}
    assert not tipos & {"horas_sin_avance", "avance_sin_horas"}       # miraban el campo manual
    assert "Avance físico 16,0 %" in ms["titular"] and "1 porción vencida sin cerrar (12 h)" in ms["titular"]


def test_curva_s_gastada_no_cambia_con_el_avance():
    """La curva «real» son horas gastadas: el avance (y el campo manual) no la mueven."""
    entradas = [_e("1", "a", D(2026, 10, 14), 8), _e("2", "b", D(2026, 10, 21), 11)]
    base = _procesar(_tareas(), entradas)
    otra = _tareas()
    otra[1] = _t("p", "5.1 Modelo", "f", hh=40, s=D(2026, 10, 5), d=D(2026, 11, 20), avance=0.1)
    otra[3] = _cerrada("b", "Modelación · 19-oct", "p", 12, D(2026, 10, 23))
    r2 = _procesar(otra, entradas)
    assert [p.gastadas for p in base.resultado.serie] == [p.gastadas for p in r2.resultado.serie]
    assert [p.programadas for p in base.resultado.serie] == [p.programadas for p in r2.resultado.serie]


def test_titular_con_vencidas():
    fila = {"rev_linea_base": 0, "avance_real": 0.42, "avance_prog": 0.5, "avance_fisico_modo": "porciones",
            "n_porciones_vencidas_abiertas": 9, "hh_porciones_vencidas_abiertas": 120, "avance_fisico_si_cerradas": 0.58}
    t = PR.derivadas_semanales(fila)["titular"]
    assert t == ("Avance físico 42,0 % frente a 50,0 % programado: 8,0 puntos bajo el plan. 9 porciones vencidas sin "
                 "cerrar (120 h): si se cierran, el avance sería 58,0 %.")
    viejo = PR.derivadas_semanales({"rev_linea_base": 0, "avance_real": 0.42, "avance_prog": 0.5})["titular"]
    assert viejo.startswith("Avance real 42,0 %")                       # filas anteriores al cambio


def test_mensaje_jp_resume_vencidas():
    ps = [MJ.Proyecto("1", "PJ-2026.0271", "2026.0271 · Muro", "Ana", True, n_vencidas=5, hh_vencidas=80),
          MJ.Proyecto("2", "PJ-2026.0225", "2026.0225 · Correa", "Ana", True, n_vencidas=4, hh_vencidas=40),
          MJ.Proyecto("3", "PJ-2026.0313", "2026.0313 · Otro", "Ana", True)]
    txt = MJ.resumen_vencidas(ps)
    assert txt.startswith("Porciones vencidas sin cerrar: 9 porciones vencidas (120 h) en 2 proyectos (")
    assert "2026.0225 · Correa: 4 (40 h); 2026.0271 · Muro: 5 (80 h)" in txt
    assert MJ.resumen_vencidas(ps[2:]) == ""
    msg = MJ.mensaje_jp("Ana", ps, {}, CORTE, "{proyectos}", {})
    assert msg.startswith("Porciones vencidas sin cerrar")


def test_reproceso_conserva_avance_fisico_de_las_fases():
    ident = {"corte": CORTE, "tipo_corte": "oficial", "list_id": "L"}
    fases = [{**ident, "fase": "05", "avance_real": 0.2, "avance_fisico": 0.2, "avance_fisico_modo": "porciones",
              "avance_manual": 0.9}]
    r = REP.Reproceso(CORTE, None)
    r.recalculadas = {"L": ({**ident}, [{**ident, "fase": "05", "avance_real": 0.2}])}
    _, fas = REP.aplicar(r, [{**ident}], fases)
    assert fas == fases
