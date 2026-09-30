"""Reproceso desde fotos, marca de cortes reprocesados, hh_estimadas_a_entrega y grilla literal del modo legado."""
import datetime as dt
from pathlib import Path

import pytest

from dep_clickup.config import TZ
from dep_reportes import esquema as E, linea_base as LB, metricas as m, proyecto as P, reproceso as REP, run
from dep_reportes.metricas import Horas, TareaMetrica
from dep_reportes.modos import LEGADO, modo_dep

D = dt.date
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "Curva S - Proyecto 2026.0152.xlsx"
DEP = modo_dep(extra_csv=None)


def T(id_, s, d, hh, av=0.0, parent=None, estado=None):
    return TareaMetrica(id_, id_, parent, s, d, hh, av, estado)


def hora(y, mo, d, h=15, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=TZ)


@pytest.fixture(scope="module")
def fx():
    if not FIXTURE.exists():
        pytest.skip("fixture Excel no disponible")
    from dep_reportes import fixture_excel
    return fixture_excel.cargar(FIXTURE)


# --- Grilla literal del modo legado -------------------------------------------------------------------

def test_grilla_excel_igual_a_la_del_excel(fx):
    assert m.grilla_excel(fx.inicio, fx.fin) == fx.grilla


def test_grilla_excel_pasos_y_cierre_en_el_termino():
    g = m.grilla_excel(D(2026, 8, 14), D(2026, 10, 2))
    assert g[0] == D(2026, 8, 13) and g[-1] == D(2026, 10, 2)
    assert [(b - a).days for a, b in zip(g, g[1:])][:12] == [3] * 11 + [2]
    corta = m.grilla_excel(D(2026, 9, 1), D(2026, 9, 6))      # 31-08, 03-09, y el termino
    assert corta == [D(2026, 8, 31), D(2026, 9, 3), D(2026, 9, 6)]


def test_legado_parte_del_ultimo_punto_de_la_grilla():
    # Grilla desde 13-08: ..., 12-09, 15-09, 17-09 (fila 66, paso 2), 20-09. Con C = 19-09 el ultimo punto <= C es
    # el 17-09: la hora del 17-09 no entra en la base (el paso fijo de 3 dias llegaba al 18-09 y la contaba).
    t = [T("a", D(2026, 8, 14), D(2026, 10, 2), 100.0, 0.5)]
    horas = [Horas(D(2026, 9, 16), 2.0, "a"), Horas(D(2026, 9, 17), 1.0, "a")]
    r = P.calcular(t, t, horas, D(2026, 9, 19), D(2026, 10, 2), LEGADO)
    assert r.metricas["hh_estimadas_al_termino"] == pytest.approx(2.0 + 50.0)
    assert r.metricas["hh_gastadas_acum"] == pytest.approx(3.0)       # gastadas: horas < C, como antes


# --- hh_estimadas_a_entrega ---------------------------------------------------------------------------

def test_a_entrega_reproduce_g75_del_excel(fx):
    r = P.calcular(fx.programa, fx.avance, fx.horas, fx.control, fx.fin, LEGADO, entrega=fx.fin)
    assert r.metricas["hh_estimadas_a_entrega"] == pytest.approx(fx.serie[-1].proyectadas, abs=0.01)
    # El total sigue llegando hasta el ultimo pendiente (10.2, despues de la entrega).
    assert r.metricas["hh_estimadas_al_termino"] == pytest.approx(fx.serie[-1].proyectadas + 10.0, abs=0.01)


def test_a_entrega_valor_de_la_curva_en_la_fecha():
    lb = [T("a", D(2026, 9, 28), D(2026, 10, 2), 50.0), T("b", D(2026, 10, 5), D(2026, 10, 9), 50.0)]
    r = P.calcular(lb, lb, [Horas(D(2026, 9, 25), 4.0, "a")], D(2026, 9, 27), D(2026, 10, 9), DEP, entrega=D(2026, 10, 2))
    assert r.metricas["hh_estimadas_a_entrega"] == pytest.approx(4.0 + 50.0)
    assert r.metricas["hh_estimadas_al_termino"] == pytest.approx(104.0)
    punto = next(p for p in r.serie if p.fecha == D(2026, 10, 2))
    assert punto.proyectadas == pytest.approx(r.metricas["hh_estimadas_a_entrega"])


def test_a_entrega_vacio_si_ya_paso_o_sin_linea_base():
    t = [T("a", D(2026, 9, 1), D(2026, 9, 30), 10.0)]
    assert P.calcular(t, t, [], D(2026, 9, 27), D(2026, 9, 30), DEP, entrega=D(2026, 9, 25)).metricas["hh_estimadas_a_entrega"] is None
    assert P.calcular(None, t, [], D(2026, 9, 27), D(2026, 9, 30), DEP, entrega=D(2026, 9, 30)).metricas["hh_estimadas_a_entrega"] is None
    assert P.calcular(t, t, [], D(2026, 9, 27), D(2026, 9, 30), DEP).metricas["hh_estimadas_a_entrega"] is None


# --- Marca de cortes reprocesados ---------------------------------------------------------------------

def ej(corte, cuando, modo="escritura", resultado="ok", n=15, detalle=""):
    return {"ejecutado_en": cuando, "corte": corte, "tipo_corte": "oficial", "modo": modo, "n_proyectos": n,
            "resultado": resultado, "detalle_error": detalle}


HISTORIAL = ([ej(D(2026, 9, 20), hora(2026, 9, 23, 15, 57), n=16), ej(D(2026, 9, 20), hora(2026, 9, 25, 15, 37), n=16),
              ej(D(2026, 9, 27), hora(2026, 9, 28, 8, 22)), ej(D(2026, 9, 27), hora(2026, 9, 29, 15, 13)),
              ej(D(2026, 10, 4), hora(2026, 10, 5, 4, 0)), ej(D(2026, 10, 4), hora(2026, 10, 5, 5, 0), modo="dry_run"),
              ej(D(2026, 10, 4), hora(2026, 10, 5, 6, 0), resultado="error")])


def test_reprocesado_en_desde_el_historial():
    assert REP.reprocesado_en(D(2026, 9, 20), HISTORIAL) == hora(2026, 9, 25, 15, 37)
    assert REP.reprocesado_en(D(2026, 9, 27), HISTORIAL) == hora(2026, 9, 29, 15, 13)
    assert REP.reprocesado_en(D(2026, 10, 4), HISTORIAL) is None      # una sola escritura ok (dry-run y error no cuentan)
    assert REP.ya_escrito(D(2026, 10, 4), HISTORIAL) and not REP.ya_escrito(D(2026, 10, 11), HISTORIAL)


def test_marcar_filas_y_ejecuciones_idempotente():
    filas = [{"corte": D(2026, 9, 20), "tipo_corte": "oficial", "list_id": "1"},
             {"corte": D(2026, 9, 27), "tipo_corte": "preliminar", "list_id": "1"},
             {"corte": D(2026, 10, 4), "tipo_corte": "oficial", "list_id": "1"}]
    out = REP.marcar(filas, HISTORIAL)
    assert [f["reprocesado_en"] for f in out] == [hora(2026, 9, 25, 15, 37), None, None]
    marcas = REP.filas_marca(HISTORIAL, hora(2026, 10, 1, 10, 0))
    assert [(f["corte"], f["detalle_error"], f["n_proyectos"]) for f in marcas] == [
        (D(2026, 9, 20), "reprocesado con datos de 2026-09-25 15:37", 16),
        (D(2026, 9, 27), "reprocesado con datos de 2026-09-29 15:13", 15)]
    assert all(f["modo"] == REP.MARCA and f["resultado"] == REP.REPROCESADO for f in marcas)
    assert REP.filas_marca(HISTORIAL + marcas, hora(2026, 10, 2, 10, 0)) == []
    # Las filas de marca no son escrituras: no cambian el momento de los datos.
    assert REP.reprocesado_en(D(2026, 9, 20), HISTORIAL + marcas) == hora(2026, 9, 25, 15, 37)


# --- Recalculo desde fotos ----------------------------------------------------------------------------

CORTE = D(2026, 9, 27)
LB_ROWS = [LB.FilaLB("L1", 0, "normal", hora(2026, 9, 1), "m", D(2026, 9, 1), D(2026, 10, 2), tid, tid, "06 Fase", hh, s, d)
           for tid, hh, s, d in (("a", 40.0, D(2026, 9, 1), D(2026, 9, 18)), ("b", 60.0, D(2026, 9, 21), D(2026, 10, 9)))]


def foto(tid, hh, s, d, av, horas, estado="en progreso", parent="f"):
    return {"corte": CORTE, "list_id": "L1", "task_id": tid, "parent_id": parent, "task_nombre": tid, "fase": "06 Fase",
            "estado": estado, "hh": hh, "start": s, "due": d, "avance_real": av, "hh_gastadas_acum": horas}


FOTOS = [foto("f", None, D(2026, 9, 1), D(2026, 10, 9), 0.0, 0.0, parent=""),
         foto("a", 40.0, D(2026, 9, 1), D(2026, 9, 25), 0.75, 30.0), foto("b", 60.0, D(2026, 9, 21), D(2026, 10, 9), 0.2, 12.5)]


def fila_guardada(**kw):
    tm = [T(f["task_id"], f["start"], f["due"], f["hh"], f["avance_real"], f["parent_id"] or None, f["estado"]) for f in FOTOS]
    horas = [Horas(D(2026, 9, 10), 30.0, "a"), Horas(D(2026, 9, 24), 12.5, "b")]
    lb_t, fase_lb = LB.a_tareas(LB_ROWS)
    r = P.calcular(lb_t, tm, horas, CORTE, D(2026, 10, 9), DEP, fase_lb, hh_historicas=5.0, entrega=D(2026, 10, 2))
    fila = {"corte": CORTE, "tipo_corte": "oficial", "list_id": "L1", "codigo": "PJ-1", "rev_linea_base": 0,
            "modo_calculo": "dep", **{c: r.metricas.get(c) for c, _ in E.METRICAS}, "hh_contrato": 300.0,
            "fecha_termino_usada": D(2026, 10, 9)}
    fila.update(kw)
    return fila, r


def test_recalcular_desde_fotos_da_lo_mismo_que_el_corte():
    fila, r = fila_guardada()
    nueva, fases = REP.recalcular(CORTE, fila, FOTOS, LB_ROWS, DEP)
    for c in REP.RECALCULADAS:
        assert nueva[c] == pytest.approx(r.metricas[c]) if isinstance(r.metricas[c], float) else nueva[c] == r.metricas[c], c
    assert nueva["hh_estimadas_a_entrega"] is not None and nueva["hh_contrato"] == 300.0     # conserva lo no recalculado
    assert sum(f["hh_gastadas_acum"] for f in fases) == pytest.approx(42.5)
    assert sum(f["hh_linea_base"] or 0 for f in fases) == pytest.approx(100.0)


def test_recalcular_con_linea_base_corregida():
    fila, _ = fila_guardada()
    lb2 = [LB.FilaLB(**{**f.fila(), "hh": f.hh * 2}) for f in LB_ROWS]
    nueva, _ = REP.recalcular(CORTE, fila, FOTOS, lb2, DEP)
    assert nueva["total_hh"] == 200.0 and nueva["hh_gastadas_acum"] == pytest.approx(fila["hh_gastadas_acum"])


@pytest.mark.parametrize("cambio, texto", [
    ({"fecha_termino_usada": None}, "fecha_termino_usada"),
    ({"hh_gastadas_acum": 60.0}, "horas en tareas que no están en fotos_tareas"),
])
def test_recalcular_falta_dato(cambio, texto):
    fila, _ = fila_guardada(**cambio)
    with pytest.raises(REP.Falta, match=texto):
        REP.recalcular(CORTE, fila, FOTOS, LB_ROWS, DEP)
    with pytest.raises(REP.Falta, match="fotos_tareas del corte"):
        REP.recalcular(CORTE, fila_guardada()[0], [], LB_ROWS, DEP)


def test_linea_base_del_corte_ignora_revisiones_posteriores():
    rev1 = [LB.FilaLB(**{**f.fila(), "rev": 1, "fecha_captura": hora(2026, 10, 1)}) for f in LB_ROWS]
    assert {f.rev for f in REP.lb_del_corte(LB_ROWS + rev1, "L1", hora(2026, 9, 29, 15, 13))} == {0}
    assert {f.rev for f in REP.lb_del_corte(LB_ROWS + rev1, "L1", None)} == {1}


# --- ejecutar: un corte oficial ya escrito no consulta ClickUp ----------------------------------------

class HojaFalsa:
    id = "falsa"

    def __init__(self, tablas):
        self.tablas = {t: [dict(f) for f in fs] for t, fs in tablas.items()}
        self.peticiones = {}
        self.escrituras = []

    def leer(self, tablas):
        return {t: [dict(f) for f in self.tablas.get(t, [])] for t in tablas if t in self.tablas}

    def metadata(self):
        return {t: {"sheetId": i} for i, t in enumerate(self.tablas)}

    def escribir(self, finales, lb_nuevas, eliminar=()):
        self.escrituras.append(sorted(finales))
        self.tablas.update({t: [dict(f) for f in fs] for t, fs in finales.items()})


class SinClickUp:
    def __getattr__(self, nombre):
        raise AssertionError(f"el reproceso no debe consultar ClickUp ({nombre})")


def hoja(fila, fotos=FOTOS):
    return HojaFalsa({"metricas_semanales": [fila], "metricas_fase": [], "fotos_tareas": fotos,
                      "linea_base": [f.fila() for f in LB_ROWS], "advertencias": [],
                      "ejecuciones": [ej(CORTE, hora(2026, 9, 28, 8, 22)), ej(CORTE, hora(2026, 9, 29, 15, 13))]})


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RESPALDOS_DIR", tmp_path / "respaldos")
    monkeypatch.setattr(run, "DRY_RUN_DIR", tmp_path / "dry")


def test_ejecutar_reprocesa_desde_fotos_sin_clickup(dirs):
    fila, r = fila_guardada()
    fila["total_hh"] = 999.0                              # numero viejo: el reproceso lo corrige desde la linea base
    h = hoja(fila)
    c = run.ejecutar(CORTE, dry_run=False, modo=DEP, sheets=h, cu=SinClickUp())
    assert not c.reproceso.omitido and h.escrituras == [["ejecuciones", "metricas_fase", "metricas_semanales"]]
    sem = h.tablas["metricas_semanales"][0]
    assert sem["total_hh"] == 100.0 and sem["reprocesado_en"] == hora(2026, 9, 29, 15, 13)
    ej_ = h.tablas["ejecuciones"]
    assert [(e["modo"], e["resultado"]) for e in ej_[2:]] == [(REP.REPROCESO, "ok"), (REP.MARCA, REP.REPROCESADO)]
    assert all(v["ok"] for v in c.verificacion.values())
    # Un segundo reproceso no agrega otra marca ni cambia el momento de los datos.
    run.ejecutar(CORTE, dry_run=False, modo=DEP, sheets=h, cu=SinClickUp())
    assert sum(e["resultado"] == REP.REPROCESADO for e in h.tablas["ejecuciones"]) == 1
    assert h.tablas["metricas_semanales"][0]["reprocesado_en"] == hora(2026, 9, 29, 15, 13)


def test_ejecutar_omite_si_falta_un_dato_y_solo_marca(dirs):
    fila, _ = fila_guardada(fecha_termino_usada=None, total_hh=999.0)
    h = hoja(fila)
    c = run.ejecutar(CORTE, dry_run=False, modo=DEP, sheets=h, cu=SinClickUp())
    assert c.reproceso.omitido
    sem = h.tablas["metricas_semanales"][0]
    assert sem["total_hh"] == 999.0 and sem["reprocesado_en"] == hora(2026, 9, 29, 15, 13)
    omit = next(e for e in h.tablas["ejecuciones"] if e["resultado"] == REP.OMITIDO)
    assert "No se reescribió (el corte queda con datos de 2026-09-29 15:13)" in omit["detalle_error"]
    assert "fecha_termino_usada) en 1 proyecto (PJ-1)" in omit["detalle_error"]
    assert any(e["detalle_error"] == "reprocesado con datos de 2026-09-29 15:13" for e in h.tablas["ejecuciones"])


def test_ejecutar_dry_run_no_escribe(dirs):
    h = hoja(fila_guardada()[0])
    c = run.ejecutar(CORTE, dry_run=True, modo=DEP, sheets=h, cu=SinClickUp())
    assert h.escrituras == [] and c.nuevas["ejecuciones"][0]["modo"] == "dry_run"
    assert (run.DRY_RUN_DIR / CORTE.isoformat() / "metricas_semanales.csv").exists()
