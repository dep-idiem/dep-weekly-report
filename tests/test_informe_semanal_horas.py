"""Informe semanal de horas: reglas de semanas, estados, asignación, ausencias, exclusiones y versiones por JP."""
from __future__ import annotations

import datetime as dt
import json

import pytest
from openpyxl import Workbook

from dep_clickup.config import TZ
from dep_reportes.calendario import Calendario
from informe_semanal_horas import core
from informe_semanal_horas.__main__ import corre_ahora, parametros
from informe_semanal_horas.drive import publicar

D = dt.date
CAL = Calendario(frozenset({D(2026, 10, 12)}))
HOY = D(2026, 11, 5)     # jueves


def ms(d: dt.date, hora: int = 12) -> str:
    return str(int(dt.datetime(d.year, d.month, d.day, hora, tzinfo=TZ).timestamp() * 1000))


def entrada(uid, fecha, horas, registro=None, lista="PJ-2026.0001 | X", lista_id="L1", task="T1", nombre=None, source="clickup"):
    return {"id": f"{uid}{fecha}{task}", "duration": str(int(horas * 3_600_000)), "start": ms(fecha), "at": ms(registro or fecha),
            "source": source, "user": {"id": uid, "username": nombre or f"P{uid}"},
            "task": {"id": task, "name": f"tarea {task}"}, "task_location": {"list_id": lista_id, "list_name": lista}}


def tarea(tid, h=0, start=None, due=None, resp=(1,), lista="PJ-2026.0001 | X", lista_id="L1", parent=None, status="to do"):
    return {"id": tid, "name": f"tarea {tid}", "parent": parent, "time_estimate": int(h * 3_600_000) or None,
            "start_date": ms(start, 8) if start else None, "due_date": ms(due, 18) if due else None, "status": status,
            "assignees": [{"id": a, "username": f"P{a}"} for a in resp], "list": {"id": lista_id, "name": lista}}


def miembro(uid, nombre=None, ingreso=D(2025, 11, 1)):
    return {"id": uid, "nombre": nombre or f"Persona Numero{uid}", "email": "", "ingreso_ms": ms(ingreso)}


def params(hoy=HOY, ultimo=None, **kw):
    return core.Parametros(hoy, ultimo or hoy - dt.timedelta(days=1), **kw)


def construir(entradas=(), tareas=(), miembros=None, ausencias=None, p=None):
    return core.construir(core.normalizar_entradas(entradas, [D(2026, 5, 4)]), core.Tareas.desde(tareas),
                          miembros or [miembro(1)], ausencias, CAL, p or params())


def test_semanas_y_ventana_del_job():
    assert core.semanas(HOY) == [D(2026, 10, 26), D(2026, 11, 2), D(2026, 11, 9)]
    assert corre_ahora(dt.datetime(2026, 11, 5, 7, 0))
    assert corre_ahora(dt.datetime(2026, 11, 5, 8, 59))
    assert not corre_ahora(dt.datetime(2026, 11, 5, 9, 0))
    assert not corre_ahora(dt.datetime(2026, 11, 5, 6, 59))
    assert not corre_ahora(dt.datetime(2026, 11, 4, 7, 0))


def test_dia_en_curso_solo_con_la_fecha_real():
    assert parametros(HOY, HOY, {}).ultimo_dia == D(2026, 11, 4)
    assert parametros(D(2026, 10, 23), HOY, {}).ultimo_dia == D(2026, 10, 23)


def test_estados_del_dia_y_futuro():
    datos = construir([entrada(1, D(2026, 11, 2), 4), entrada(1, D(2026, 11, 3), 3.9), entrada(1, D(2026, 11, 5), 8)])
    dias = datos["personas"][0]["semanas"][1]["dias"]
    assert [x["e"] for x in dias] == ["ok", "bajo", "sin", "futuro", "futuro"]
    assert datos["personas"][0]["semanas"][1]["reg"] == 7.9     # el día en curso no cuenta


def test_feriado_ausencia_y_medio_dia():
    aus = core.Ausencias({"Persona Numero1": {D(2026, 10, 13): ("vacaciones", 1.0), D(2026, 10, 14): ("administrativo", 0.5),
                                              D(2026, 10, 15): ("administrativo", 0.5)}}, {})
    es = [entrada(1, D(2026, 10, 14), 2), entrada(1, D(2026, 10, 15), 1.9)]
    dias = construir(es, ausencias=aus, p=params(D(2026, 10, 23), D(2026, 10, 23)))["personas"][0]["semanas"][0]["dias"]
    assert [x["e"] for x in dias] == ["feriado", "ausente", "ok", "bajo", "sin"]
    assert dias[1]["t"] == "vacaciones"


def test_jornada_parcial_escala_el_umbral():
    p = params(D(2026, 10, 30), D(2026, 10, 30), jornadas={"Persona Numero1": 11})
    es = [entrada(1, D(2026, 10, 26), 2, task="A"), entrada(1, D(2026, 10, 27), 0.5, task="B")]
    datos = construir(es, p=p)["personas"][0]
    assert datos["jornada"] == 11
    assert [x["e"] for x in datos["semanas"][1]["dias"]] == ["ok", "bajo", "sin", "sin", "sin"]


def test_jornada_cumplida_no_deja_dias_en_rojo():
    p = params(D(2026, 10, 30), D(2026, 10, 30), jornadas={"Persona Numero1": 11})
    es = [entrada(1, D(2026, 10, 28), 5, task="A"), entrada(1, D(2026, 10, 29), 6, task="B")]
    dias = construir(es, p=p)["personas"][0]["semanas"][1]["dias"]
    assert [x["e"] for x in dias] == ["ausente", "ausente", "ok", "ok", "ausente"]
    assert dias[0]["t"] == "jornada cumplida"


def test_sin_dias_fijos_no_marca_rojo_en_la_semana_en_curso():
    p = params(jornadas={"Persona Numero1": 11}, sin_dias_fijos=("Persona Numero1",))    # corte jueves: registros hasta el miércoles
    semanas_ = construir([entrada(1, D(2026, 10, 29), 3)], p=p)["personas"][0]["semanas"]
    assert [x["e"] for x in semanas_[1]["dias"]] == ["ausente", "ausente", "ausente", "futuro", "futuro"]
    assert [x["e"] for x in semanas_[0]["dias"]] == ["sin", "sin", "sin", "ok", "sin"]    # semana cerrada: se evalúa


def test_sin_dias_fijos_no_alcanza_a_los_demas():
    p = params(jornadas={"Persona Numero1": 22})
    dias = construir(p=p)["personas"][0]["semanas"][1]["dias"]
    assert [x["e"] for x in dias] == ["sin", "sin", "sin", "futuro", "futuro"]


class _Resp:
    def __init__(self, datos):
        self.status_code, self.text, self._d = 200, "", datos

    def json(self):
        return self._d


class _Sesion:
    def __init__(self):
        self.llamadas = []

    def post(self, url, **kw):
        self.llamadas.append(("post", url))
        return _Resp({"id": f"nuevo{len(self.llamadas)}", "name": "x"})

    def patch(self, url, **kw):
        self.llamadas.append(("patch", url))
        return _Resp({"id": "ya"})


class _Drive:
    def __init__(self, hijos):
        self.s, self._h = _Sesion(), hijos

    def hijos(self, fid):
        return self._h.get(fid, [])


def test_publicar_crea_una_carpeta_por_destino():
    dr = _Drive({"RAIZ": []})
    carpetas, enlaces = publicar({"g.html": b"x", "j.html": b"y"}, {"g.html": "General", "j.html": "Ana Mena"}, "RAIZ", dr)
    assert [m for m, _ in dr.s.llamadas] == ["post"] * 4
    assert set(carpetas) == {"General", "Ana Mena"}
    assert carpetas["General"].endswith("/folders/nuevo1") and enlaces["g.html"].endswith("/d/nuevo2/view")


def test_publicar_reemplaza_si_ya_existe():
    general = {"id": "GEN", "name": "General", "mimeType": "application/vnd.google-apps.folder"}
    dr = _Drive({"RAIZ": [general], "GEN": [{"id": "F1", "name": "a.html"}]})
    _, enlaces = publicar({"a.html": b"x", "b.html": b"y"}, {"a.html": "General", "b.html": "General"}, "RAIZ", dr)
    assert [m for m, _ in dr.s.llamadas] == ["patch", "post"]
    assert enlaces["a.html"].endswith("/d/F1/view")


def test_jornada_estandar_no_cambia_nada():
    p = params(D(2026, 10, 30), D(2026, 10, 30))
    es = [entrada(1, D(2026, 10, 26), 44, task="A")]
    fila = construir(es, p=p)["personas"][0]
    assert fila["jornada"] == 44
    assert [x["e"] for x in fila["semanas"][1]["dias"]] == ["ok", "sin", "sin", "sin", "sin"]


def test_cargado_tarde_es_despues_del_lunes_siguiente():
    lunes_sig = D(2026, 11, 2)
    es = [entrada(1, D(2026, 10, 26), 3, registro=lunes_sig, task="A"), entrada(1, D(2026, 10, 27), 5, registro=D(2026, 11, 3), task="B")]
    dias = construir(es)["personas"][0]["semanas"][0]["dias"]
    assert (dias[0]["tarde"], dias[1]["tarde"]) == (0.0, 5.0)


def test_entrada_movida_por_orden_adm_no_es_tarde():
    e = entrada(1, D(2026, 10, 26), 3, registro=D(2026, 11, 9), source="api", task="A")
    e["description"] = "movida desde 02 Gestión administrativa y correos el 2026-11-09"
    dias = construir([e, entrada(1, D(2026, 10, 27), 5, registro=D(2026, 11, 9), task="B")])["personas"][0]["semanas"][0]["dias"]
    assert (dias[0]["tarde"], dias[1]["tarde"]) == (0.0, 5.0)


def test_solo_excluye_la_carga_historica_por_api():
    es = [entrada(1, D(2026, 3, 2), 8, registro=D(2026, 5, 4), source="api", task="A"),
          entrada(1, D(2026, 9, 2), 2, registro=D(2026, 10, 27), source="api", task="B")]
    n = core.normalizar_entradas(es, [D(2026, 5, 4)])
    assert [x.task_id for x in n] == ["B"]


def test_etiquetas():
    assert core.etiqueta("PJ-2025.0019-0147 | CMP-SHM Modelos") == "2025.0019-0147"
    assert core.etiqueta("PR-2026.0215 | Algo") == "2026.0215"
    assert core.etiqueta("PJ-2025.00SC | Edificio") == "2025.00SC"
    assert core.etiqueta("ADM-01 | Administración") == "ADM-01"
    assert core.etiqueta("SS_REGISTRO", "901324495476") == core.PROPUESTAS
    assert core.etiqueta("Time Tracking") == "Time Tracking"


def test_asignado_prorratea_por_habiles_y_no_divide_entre_responsables():
    # 10 h de jueves a miércoles siguiente = 5 hábiles (2 en una semana, 3 en la otra); el estimate es por persona
    t = tarea("A", 10, D(2026, 10, 29), D(2026, 11, 4), resp=(1, 2))
    a = core.calcular_asignado(core.Tareas.desde([t]), CAL, core.semanas(HOY))
    assert a[(1, D(2026, 10, 26))].horas == pytest.approx(4)
    assert a[(2, D(2026, 10, 26))].horas == pytest.approx(4)
    assert a[(2, D(2026, 11, 2))].horas == pytest.approx(6)
    assert a[(1, D(2026, 11, 2))].tareas[0]["h"] == 6.0
    assert a[(1, D(2026, 11, 2))].tareas[0]["d"] == "2–4 nov"


def test_padre_con_hija_estimada_no_cuenta_y_cajon_es_el_primer_nivel():
    tareas = [tarea("C", resp=()), tarea("P", 50, D(2026, 11, 9), D(2026, 11, 13), parent="C"),
              tarea("H", 10, D(2026, 11, 9), D(2026, 11, 13), parent="P")]
    fila = construir(tareas=tareas)["personas"][0]["semanas"][2]
    assert fila["asig"] == 10
    assert fila["tareas_prog"] == [{"p": "2026.0001", "c": "tarea C", "t": "tarea H", "h": 10.0, "d": "9–13 nov"}]


def test_fechas_incompletas():
    assert core.ventana(tarea("A", 1, None, D(2026, 11, 4))) == (D(2026, 11, 4), D(2026, 11, 4))
    assert core.ventana(tarea("A", 1, D(2026, 11, 4), None)) == (D(2026, 11, 4), D(2026, 11, 4))
    assert core.ventana(tarea("A", 1, D(2026, 11, 6), D(2026, 11, 4))) == (D(2026, 11, 4), D(2026, 11, 4))
    assert core.ventana(tarea("A", 1)) is None
    assert core.rango_dias(D(2026, 11, 30), D(2026, 12, 2)) == "30 nov–2 dic"


def test_detalle_con_estimacion_y_acumulado_y_sin_fuga_de_otros():
    tareas = [tarea("T1", 10, D(2026, 10, 26), D(2026, 10, 30), status="completado")]
    es = [entrada(1, D(2026, 9, 1), 6), entrada(2, D(2026, 10, 27), 3, nombre="Otra"), entrada(1, D(2026, 10, 28), 2)]
    datos = construir(es, tareas, [miembro(1), miembro(2)])
    fila = next(x for x in datos["personas"] if x["nombre"] == "Persona Numero1")["semanas"][0]
    assert fila["tareas"] == [{"p": "2026.0001", "t": "tarea T1", "h": 2.0, "d": 1, "est": 10.0, "acum": 11.0}]
    assert datos["estimacion"][0] | {"_lista": ""} == {"p": "2026.0001", "t": "tarea T1", "est": 10.0, "reg": 11.0,
                                                        "estado": "completado", "_lista": ""}
    assert datos["proyectos"]["2026.0001"]["2026-10-26"] == {"h": 5.0, "n": 2}


def test_estimacion_con_o_sin_adm():
    tareas = [tarea("A", 5, None, D(2026, 10, 28), lista="ADM-01 | Administración", lista_id="LA")]
    assert len(construir(tareas=tareas)["estimacion"]) == 1
    assert construir(tareas=tareas, p=params(estimacion_sin_adm=True))["estimacion"] == []


def test_exclusiones_y_orden_por_dias_sin_registro():
    miembros = [miembro(1, "Zoe Ruiz"), miembro(2, "Ana Mena"), miembro(3, "Nuevo Ingreso", D(2026, 10, 20)),
                miembro(4, "Ale Toro Castro")]
    es = [entrada(1, D(2026, 10, d), 8, task=f"T{d}") for d in (26, 27, 28, 29, 30)]
    p = params(excluir=("Ale Toro",))
    datos = construir(es, miembros=miembros, p=p)
    assert [x["nombre"] for x in datos["personas"]] == ["Ana Mena", "Zoe Ruiz"]
    fuera = {m["nombre"]: m["motivo"] for m in core.personas_incluidas(miembros, p)[1]}
    assert set(fuera) == {"Nuevo Ingreso", "Ale Toro Castro"}


def test_incluir_gana_a_la_regla_de_nuevos_pero_no_a_excluir():
    miembros = [miembro(1, "Nuevo Ingreso", D(2026, 10, 20)), miembro(2, "Otra Nueva", D(2026, 10, 20)),
                miembro(3, "Ale Toro", D(2026, 10, 20))]
    dentro, fuera = core.personas_incluidas(miembros, params(incluir=("Nuevo Ingreso", "Ale Toro"), excluir=("Ale Toro",)))
    assert [m["nombre"] for m in dentro] == ["Nuevo Ingreso"]
    assert {m["nombre"] for m in fuera} == {"Otra Nueva", "Ale Toro"}


def test_cruce_de_nombres_tolerante():
    planilla = ["Javier Pérez Yáñez", "Franco Díaz", "Mario Ruiz", "Luis Álvarez", "Luis Ortega", "Fuenzalida Freitas Andre Luis"]
    assert core.cruzar_nombre("Javier Perez Yañez", planilla) == "Javier Pérez Yáñez"
    assert core.cruzar_nombre("Franco Diaz Torres", planilla) == "Franco Díaz"
    assert core.cruzar_nombre("Mario Patricio Jean Lui Ruiz", planilla) == "Mario Ruiz"
    assert core.cruzar_nombre("André Luis Fuenzalida", planilla) == "Fuenzalida Freitas Andre Luis"
    assert core.cruzar_nombre("Luis", planilla) is None
    assert core.cruzar_nombre("Leonardo Cavieres Martínez", planilla) is None


def test_lee_la_planilla_de_ausencias():
    wb = Workbook()
    ws = wb.active
    ws.cell(4, 3, dt.datetime(2026, 10, 1))
    ws.cell(4, 6, dt.datetime(2026, 11, 1))
    for col, dia in zip(range(3, 8), (30, 31, None, 1, 2)):
        if dia:
            ws.cell(5, col, float(dia))
    ws.cell(6, 1, "AAA")
    ws.cell(6, 2, " Ana Mena ")
    ws.cell(6, 3, 2.0)
    ws.cell(6, 4, 0.5)
    ws.cell(6, 6, 0.0)
    ws.cell(6, 7, " ")
    a = core.leer_ausencias(ws)
    assert a.dias["Ana Mena"] == {D(2026, 10, 30): ("vacaciones", 1.0), D(2026, 10, 31): ("administrativo", 0.5),
                                  D(2026, 11, 1): ("compensatorio", 1.0)}
    assert core.iniciales("Ana Paz Mena", a) == "AAA"
    assert core.iniciales("Otra Persona", a) == "OP"


def test_version_jp_filtra_personas_y_proyectos():
    listas = [{"id": "L1", "name": "PJ-2026.0001 | X", "jp": "Jefa Uno"}, {"id": "L2", "name": "PJ-2026.0002 | Y", "jp": "Jefa Dos"},
              {"id": "LT", "name": "PJ-TEST | Z", "jp": "Jefa Tres"}, {"id": "L3", "name": "PJ-2026.0003 | V", "jp": "Jefa Cuatro"}]
    jefes, _ = core.jefes(listas)
    assert set(jefes) == {"Jefa Uno", "Jefa Dos", "Jefa Cuatro"}
    tareas = core.Tareas.desde([tarea("T2", 8, D(2026, 11, 9), D(2026, 11, 13), resp=(3,), lista="PJ-2026.0002 | Y", lista_id="L2")])
    es = core.normalizar_entradas([entrada(1, D(2026, 10, 27), 4, task="A"),
                                   entrada(2, D(2026, 10, 27), 4, lista="PJ-2026.0002 | Y", lista_id="L2", task="B")])
    p = params()
    general = core.construir(es, tareas, [miembro(1), miembro(2), miembro(3)], None, CAL, p)
    dos = core.version_jp(general, jefes["Jefa Dos"], es, tareas, CAL)
    assert {x["id"] for x in dos["personas"]} == {2, 3}
    assert set(dos["proyectos"]) == {"2026.0002"} and set(dos["asg_next"]) == {"2026.0002"}
    assert dos["jp"] == "Jefa Dos"
    assert core.version_jp(general, jefes["Jefa Cuatro"], es, tareas, CAL) is None


def test_solo_los_jp_definidos_y_a_cargo_pasa_sus_listas():
    listas = [{"id": "L1", "name": "PJ-2026.0001 | X", "jp": "Fernando Munoz"}, {"id": "L2", "name": "PJ-2026.0002 | Y", "jp": "Felipe Yanez"},
              {"id": "L3", "name": "PJ-2026.0003 | Z", "jp": "Sergio Tapia"}, {"id": "L4", "name": "PJ-2026.0004 | V", "jp": "Sergio Tapia"}]
    jefes, sin_version = core.jefes(listas, {"Felipe Yañez": "Fernando Muñoz"}, ["Fernando Muñoz"])
    assert list(jefes) == ["Fernando Muñoz"]
    assert jefes["Fernando Muñoz"]["listas"] == {"L1", "L2"}
    assert sin_version == {"Sergio Tapia": 2}


def test_render_escapa_y_no_deja_marcador(tmp_path):
    datos = construir([entrada(1, D(2026, 10, 27), 4)], miembros=[miembro(1, "Ana <b>Mena</b>")])
    salida = core.render(datos, "Generado hoy")
    assert "__DATA__" not in salida and "<b>Mena" not in salida and "Ana &lt;b&gt;Mena" in salida
    bloque = salida.split("const D=", 1)[1].split(";\nconst DN", 1)[0]
    d = json.loads(bloque)
    assert d["generado"] == "Generado hoy" and "id" not in d["personas"][0]


def test_pdf_va_con_su_tipo_y_sin_desglose():
    from informe_semanal_horas import drive, pdf
    assert drive.tipo("horas_semana_DEP_2026-11-05.pdf") == "application/pdf"
    assert drive.tipo("horas_semana_DEP_2026-11-05.html") == "text/html"
    html = pdf.para_imprimir("<html><head><title>x</title></head><body></body></html>")
    assert ".band.det{display:none}" in html and html.index("@page") < html.index("</head>")
