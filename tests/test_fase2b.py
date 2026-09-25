"""Fase 2b: capa de porciones, linea base incremental, presupuesto contractual y plan semanal."""
import datetime as dt

from dep_clickup.config import TZ
from dep_clickup.models import CustomField, ListInfo, Task
from dep_reportes import controles as CTL, estructura as EST, linea_base as LB, metricas as MT, plan_semanal as PS
from dep_reportes import presentacion as PR, presupuesto as PRES, proyecto as P
from dep_reportes.adaptador_clickup import a_tareas_metrica, es_administracion
from dep_reportes.metricas import Horas
from dep_reportes.modos import por_nombre

D = dt.date


def ms(d):
    return dt.datetime(d.year, d.month, d.day, 9, tzinfo=TZ) if d else None


def T(id_, nombre, parent=None, hh=None, s=None, d=None, te=None, avance=None, estado="to do", tipo="custom",
      creada=D(2026, 7, 1)):
    cf = {"HH Presupuestadas": CustomField("1", "HH Presupuestadas", "number", hh, hh),
          "Avance Real": CustomField("2", "Avance Real", "manual_progress", avance, avance)}
    return Task(id_, nombre, parent, estado, "L", ms(s), ms(d), int(te * 3_600_000) if te else None, (), cf,
                status_type=tipo, date_created=ms(creada))


# --- 1. Clasificacion (casos del informe de estructura) -------------------------------------------------------

def test_visitas_mensuales_de_0008_son_paquetes_recurrentes():
    ts = [T("f4", "04 Visitas"), T("v", "4.3 Visitas Revisor Técnico", "f4"),
          T("a", "Visita 2/2 Jul 2027 CASR", "v", hh=5, te=5), T("b", "Visita 1/2 Jul 2027 CASR", "v", hh=5, te=5)]
    c = EST.clasificar(ts)
    assert (c["a"].tipo, c["a"].recurrente, c["a"].porcion_con_hh) == (EST.PAQUETE, True, False)
    assert c["f4"].tipo == EST.FASE and c["v"].tipo == EST.OTRA


def test_analisis_mecanico_semanal_de_0235_es_porcion():
    ts = [T("f5", "05 Análisis"), T("p", "5.1 Análisis Mecánico", "f5"),
          T("a", "Análisis Mecánico", "p", te=36, s=D(2026, 10, 5), d=D(2026, 10, 9)),
          T("b", "Análisis Mecánico", "p", te=44, s=D(2026, 9, 28), d=D(2026, 10, 2))]
    c = EST.clasificar(ts)
    assert c["a"].tipo == c["b"].tipo == EST.PORCION and c["a"].paquete is None      # 5.1 no tiene HH
    assert c["p"].tipo == EST.OTRA


def test_hijas_36_72_de_4_3_en_0152_son_paquetes_y_se_advierten():
    ts = [T("f4", "04 Terreno"), T("p", "4.3 Levantamiento Condición Actual", "f4"),
          T("a", "Levantamiento Condición Actual", "p", hh=72, te=36, s=D(2026, 8, 24), d=D(2026, 8, 27)),
          T("b", "Levantamiento Condición Actual", "p", hh=36, te=9, s=D(2026, 8, 24), d=D(2026, 8, 24))]
    c = EST.clasificar(ts)
    assert c["a"].tipo == c["b"].tipo == EST.PAQUETE and c["a"].porcion_con_hh and c["b"].porcion_con_hh
    assert MT.total_hh(a_tareas_metrica(ts)) == 108                         # el universo no cambia


def test_porcion_bajo_paquete_y_tareas_de_plantilla():
    ts = [T("f5", "05 Ingeniería"), T("p", "5.2 Modelación", "f5", hh=45, s=D(2026, 7, 21), d=D(2026, 8, 7)),
          T("pa", "5.2.a Modelo de Cubierta", "p"),
          T("x", "Modelo de Cubierta", "pa", te=18, s=D(2026, 7, 21), d=D(2026, 7, 24)),
          T("y", "5.2.b Revisión Cruzada", "p", te=6, s=D(2026, 8, 3), d=D(2026, 8, 7)),       # numerada: no es porcion
          T("z", "Seguimiento EP N°1", "f5", s=D(2026, 7, 21), d=D(2026, 10, 9))]              # larga: otra
    c = EST.clasificar(ts)
    assert c["p"].tipo == EST.PAQUETE and c["x"].tipo == EST.PORCION and c["x"].paquete == "p"
    assert c["pa"].tipo == EST.OTRA and c["y"].tipo == EST.OTRA and c["z"].tipo == EST.OTRA
    assert EST.porciones_de(c) == {"p": ["x"]}
    assert EST.solo_porciones_debajo(ts, c) == {"pa"}


# --- 2. Avance del paquete -------------------------------------------------------------------------------------

def test_toda_tarea_con_hh_es_paquete_incluso_de_nivel_0():
    ts = [T("adm", "00 Administración", hh=3000), T("f", "06 Informe Final", hh=44),
          T("g", "05 Informe de Avance N°1", hh=30, s=D(2026, 8, 3), d=D(2026, 8, 7)), T("h", "07 Cierre")]
    c = EST.clasificar(ts)
    assert c["adm"].tipo == EST.FASE and c["h"].tipo == EST.FASE              # presupuesto y fase sin HH
    assert (c["f"].tipo, c["f"].es_fase) == (EST.PAQUETE, True)
    assert (c["g"].tipo, c["g"].recurrente, c["g"].es_fase) == (EST.PAQUETE, True, True)
    rev0 = LB.congelar(LISTA, ts[:1], 0, "normal", "Rev. 0", dt.datetime(2026, 8, 1, tzinfo=TZ))
    base = LB.congelar(LISTA, [ts[2]], 0, "normal", "Rev. 0", dt.datetime(2026, 7, 1, tzinfo=TZ))
    nueva = T("n", "08 Extra", hh=10, s=D(2026, 10, 1), d=D(2026, 10, 9), creada=D(2026, 9, 1))
    paq = {k for k, x in EST.clasificar(ts + [nueva]).items() if x.tipo == EST.PAQUETE}
    inc = LB.incrementales(LISTA, ts + [nueva], paq, base, dt.datetime(2026, 9, 2, tzinfo=TZ))
    assert [f.task_id for f in inc] == ["n"]                      # «06 Informe Final» espera fechas
    assert rev0 == []                                             # 00 Administración no entra al universo


def test_avance_efectivo_por_origen():
    ts = [T("f", "05 Ing"),
          T("m", "5.1 Manual", "f", hh=10, avance=0.4), T("m1", "Manual", "m", te=5, s=D(2026, 9, 1), d=D(2026, 9, 4)),
          T("p", "5.2 Por porciones", "f", hh=10),
          T("p1", "Porciones", "p", te=5, s=D(2026, 9, 1), d=D(2026, 9, 4), tipo="closed"),
          T("p2", "Porciones", "p", te=5, s=D(2026, 9, 7), d=D(2026, 9, 11)),
          T("p3", "Porciones", "p", te=5, s=D(2026, 9, 14), d=D(2026, 9, 18), estado="no aplica"),
          T("s", "5.3 Sin dato", "f", hh=10)]
    av = EST.avance_efectivo(ts, EST.clasificar(ts))
    assert av == {"m": (0.4, EST.MANUAL), "p": (0.5, EST.PORCIONES), "s": (None, EST.SIN_DATO)}


# --- 4. 00 Administracion: presupuesto, fuera del universo -------------------------------------------------------

def test_00_administracion_fuera_del_universo_y_como_presupuesto():
    ts = [T("adm", "00 Administración", hh=3000), T("f", "05 Ing"), T("a", "5.1 Tarea", "f", hh=100),
          T("sub", "0.1 Gestión", "adm", hh=20)]
    assert es_administracion(ts[0]) and not es_administracion(ts[3])
    tm = {t.id: t for t in a_tareas_metrica(ts)}
    assert tm["adm"].hh is None and MT.total_hh(tm.values()) == 120
    assert PRES.hh_contrato(ts) == 3000 and PRES.hh_contrato(ts, manual=4000) == 4000
    assert PRES.hh_contrato(ts[1:]) is None


def test_presupuesto_ritmo_y_titular():
    corte = D(2026, 9, 20)
    horas = [Horas(corte - dt.timedelta(days=i), 40 / 7) for i in range(28)]     # 40 h por semana
    m = PRES.metricas(3000, 2420, horas, corte)
    assert round(m["ritmo_semanal"], 6) == 40 and round(m["pct_contrato_usado"], 4) == 0.8067
    assert round(m["semanas_restantes_al_ritmo"], 2) == 14.5 and m["fecha_agotamiento_estimada"] == D(2026, 12, 31)
    assert PRES.avisos(m) == []
    t = PR.titular(False, None, None, "x", m)
    assert t == "Sin curva programada. Consumidas 2.420 de 3.000 HH contratadas (81 %); al ritmo actual se agotan el 31-12-2026."
    a = PRES.avisos(PRES.metricas(3000, 2900, horas, corte))[0]                  # 2,5 semanas: alerta
    assert a.tipo == P.ADV_PRESUPUESTO_POR_AGOTARSE and not a.datos["superado"]
    sup = PRES.metricas(3000, 3100, horas, corte)
    assert PRES.avisos(sup)[0].datos["superado"] and sup["fecha_agotamiento_estimada"] is None
    assert PR.titular(False, None, None, "x", sup).endswith("(103 %): presupuesto superado.")
    assert PRES.avisos(PRES.metricas(None, 100, horas, corte))[0].tipo == P.ADV_SIN_PRESUPUESTO


# --- 3. Linea base incremental ------------------------------------------------------------------------------------

LISTA = ListInfo("L", "PJ-2026.0001 | Proyecto | Cliente", None, False, None, None, None, None, None, None, None)


def test_paquete_nuevo_se_congela_sin_advertencia_y_cambio_de_hh_si_advierte():
    t0 = dt.datetime(2026, 8, 1, 12, tzinfo=TZ)
    base = [T("f", "05 Ing", creada=D(2026, 7, 1)),
            T("a", "5.1 Diseño", "f", hh=40, s=D(2026, 8, 3), d=D(2026, 8, 14), creada=D(2026, 7, 1))]
    rev0 = LB.congelar(LISTA, base, 0, "normal", "Rev. 0", t0)
    nuevo = T("n", "Apoyo Asesoría Oct 2026", "f", hh=20, s=D(2026, 10, 1), d=D(2026, 10, 30), creada=D(2026, 9, 1))
    ts = base + [nuevo]
    paquetes = {k for k, c in EST.clasificar(ts).items() if c.tipo == EST.PAQUETE}
    inc = LB.incrementales(LISTA, ts, paquetes, rev0, dt.datetime(2026, 9, 2, tzinfo=TZ))
    assert [(f.task_id, f.rev, f.tipo, f.hh) for f in inc] == [("n", 0, "incremental", 20.0)]
    assert LB.incrementales(LISTA, ts, paquetes, rev0 + inc, dt.datetime(2026, 9, 3, tzinfo=TZ)) == []   # idempotente
    modo, corte = por_nombre("dep"), D(2026, 9, 20)
    lb0, _ = LB.a_tareas(rev0)
    lb1, _ = LB.a_tareas(rev0 + inc)
    r0 = P.calcular(lb0, a_tareas_metrica(base), [], corte, D(2026, 10, 30), modo)
    r1 = P.calcular(lb1, a_tareas_metrica(ts), [], corte, D(2026, 10, 30), modo)
    assert r1.metricas["total_hh"] == r0.metricas["total_hh"] + 20                  # la curva programada crece
    assert not any(a.tipo == P.ADV_HH_CAMBIARON for a in r1.avisos)
    cambiado = [T("a", "5.1 Diseño", "f", hh=55, s=D(2026, 8, 3), d=D(2026, 8, 14)), nuevo, base[0]]
    r2 = P.calcular(lb1, a_tareas_metrica(cambiado), [], corte, D(2026, 10, 30), modo)
    av = [a for a in r2.avisos if a.tipo == P.ADV_HH_CAMBIARON]
    assert len(av) == 1 and av[0].datos == {"n": 1, "actual": 55.0, "linea_base": 40.0}
    # Tarea antigua sin fechas o creada antes de la Rev. 0: no se congela como incremental
    vieja = T("v", "5.2 Vieja", "f", hh=10, s=D(2026, 8, 3), d=D(2026, 8, 7), creada=D(2026, 7, 1))
    assert [f.task_id for f in LB.incrementales(LISTA, ts + [vieja], paquetes | {"v"}, rev0, t0)] == ["n"]
    # Paquete desaparecido
    assert [f.task_id for f in LB.desaparecidos(rev0 + inc, [base[0], nuevo])] == ["a"]


def test_controles_aceptan_filas_incrementales():
    U, C = CTL.Umbrales(), D(2026, 9, 27)
    t_pub = dt.datetime(2026, 9, 21, 10, tzinfo=TZ)
    ejec = [{"corte": D(2026, 9, 20), "modo": "escritura", "resultado": "ok", "ejecutado_en": t_pub, "n_proyectos": 1}]
    previas = [{"list_id": "L", "rev_linea_base": 0, "total_hh": 100.0, "corte": D(2026, 9, 20)}]
    inc_viejo = (dt.datetime(2026, 9, 25, tzinfo=TZ), 20.0)          # capturado despues de publicar el 20-09
    ok = CTL.ProyectoControl("L", "L", 0, 120.0, 130.0, 10.0, 0.1, hh_incrementales_nuevas=10.0, incrementales=(inc_viejo,))
    assert CTL.verificar(C, [C], [ok], ejec, previas, U) == []
    malo = CTL.ProyectoControl("L", "L", 0, 120.0, 135.0, 10.0, 0.1, hh_incrementales_nuevas=10.0, incrementales=(inc_viejo,))
    assert len(CTL.verificar(C, [C], [malo], ejec, previas, U)) == 2


# --- 5. Plan semanal -------------------------------------------------------------------------------------------

def test_plan_semanal_filas_y_cumplimiento():
    corte = D(2026, 9, 20)                                   # domingo: semana del 14-09
    plan = [EST.PorcionPlan("x", "p", D(2026, 9, 14), D(2026, 9, 14), D(2026, 9, 18), 40),
            EST.PorcionPlan("y", "p", D(2026, 9, 7), D(2026, 9, 7), D(2026, 9, 11), 40),
            EST.PorcionPlan("z", "p", D(2026, 8, 31), D(2026, 8, 31), D(2026, 9, 4), 40),
            EST.PorcionPlan("w", "p", D(2026, 8, 24), D(2026, 8, 24), D(2026, 8, 28), 40),
            EST.PorcionPlan("f", "p", D(2026, 9, 28), D(2026, 9, 28), D(2026, 10, 2), 30)]
    horas = [Horas(D(2026, 9, 15), 10), Horas(D(2026, 9, 8), 15), Horas(D(2026, 9, 1), 70), Horas(D(2026, 8, 25), 40)]
    fs = PS.filas(plan, horas, corte)
    assert len(fs) == 12 and fs[7]["semana"] == D(2026, 9, 14) and fs[7]["cumplimiento"] == 0.25
    fut = [f for f in fs if f["semana"] > corte]
    assert [f["hh_planificadas"] for f in fut] == [0, 30, 0, 0] and all(f["hh_registradas"] is None for f in fut)
    a = PS.aviso_cumplimiento(fs, corte)                      # 25 %, 37,5 %, 175 % y 100 %: 3 fuera de rango
    assert len(a) == 1 and a[0].datos["n"] == 3 and a[0].datos["bajo"] == 2
    assert PS.aviso_cumplimiento(fs[:-6] + fs[-5:], corte) == []


def test_proyeccion_por_plan_semanal():
    cal = por_nombre("dep").cal
    plan = [EST.PorcionPlan("x", "a", D(2026, 9, 28), D(2026, 9, 28), D(2026, 10, 2), 30)]
    pend = PS.pendientes_por_paquete(plan, D(2026, 9, 20), cal)
    assert round(sum(pend["a"].values()), 6) == 30 and min(pend["a"]) == D(2026, 9, 28)
    tm = [MT.TareaMetrica("a", "5.1", None, D(2026, 9, 1), D(2026, 10, 30), 100.0, 0.5)]
    uni = P.calcular(tm, tm, [], D(2026, 9, 20), D(2026, 10, 30), por_nombre("dep"))
    ps = P.calcular(tm, tm, [], D(2026, 9, 20), D(2026, 10, 30), por_nombre("dep"), pendientes_plan=pend)
    assert uni.metricas["hh_estimadas_al_termino"] == 50 and ps.metricas["hh_estimadas_al_termino"] == 30


def test_advertencias_nuevas_de_nivel_proyecto_van_a_la_hoja():
    for tipo in (P.ADV_SIN_PRESUPUESTO, P.ADV_PRESUPUESTO_POR_AGOTARSE, P.ADV_CUMPLIMIENTO, P.ADV_PAQUETE_DESAPARECIDO):
        assert P.para_hoja([{"tipo": tipo, "task_id": ""}], set()) and PR.nivel(tipo) == "proyecto"
