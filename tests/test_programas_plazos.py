"""Plazos de los programas: regla del dia 20 de los informes, pasos, visitas y su historial de fechas, oficios semanales
de AITO (programas.py) y reportes diarios (reportes_diarios.py)."""
import datetime as dt

from dep_clickup.config import TZ
from dep_clickup.models import CustomField, Task
from dep_reportes import esquema as E, programas as PG, reportes_diarios as RD

D = dt.date
CORTE = D(2026, 11, 3)

CONFIG = {
    "nombre": "Monitoreo", "cliente": "CMP",
    "contratos": {"0019": {"nombre": "MLC", "codigo": "PJ-2025.0019", "patron_fase": "0019|MLC",
                           "informe_ancla": {"numero": 8, "periodo": "2026-07"}},
                  "0147": {"nombre": "Apilador", "codigo": "PJ-2025.0147", "patron_fase": "0147|Apilador",
                           "informe_ancla": {"numero": 3, "periodo": "2026-07"}}},
    "lineas": {"informes": "Informes", "general": "General"},
    "listas": [{"list_id": "INF", "linea": "informes"}, {"list_id": "GEN", "linea": "general"}],
    "entregables": {"informe": {"patron": "^\\s*IM-\\d", "frecuencia": "mensual", "plazo_dia_mes_siguiente": 20,
                                "paso_entrega": "Informe\\s*Rev\\.?\\s*B\\b"},
                    "visita": {"patron": "^\\s*VT-\\d", "paso_terreno": "Trabajos en Terreno", "seguir_fechas": True}},
}
P = PG.desde_dict("CMP", CONFIG)


def _h(d):
    return dt.datetime(d.year, d.month, d.day, 12, tzinfo=TZ) if d else None


def tarea(tid, nombre, parent=None, status="to do", due=None, done=None, tipo="open", start=None, asignados=(),
          lista="INF", creada=None, cf=None):
    return Task(tid, nombre, parent, status, lista, _h(start), _h(due), None, tuple(asignados), cf or {},
                status_type=tipo, date_done=_h(done), date_created=creada)


def cerrada(tid, nombre, parent, done):
    return tarea(tid, nombre, parent, "completado", done=done, tipo="done")


INFORMES = [
    tarea("f19", "MLC 0019"), tarea("f147", "Apilador 0147"),
    # IM-10 MLC = septiembre: plazo 20-oct; Rev. B cerrada el 29-oct (9 dias tarde); falta B.8
    tarea("im10", "IM-10 Informe Mensual N°10", "f19", "en progreso", D(2026, 10, 30), start=D(2026, 10, 13)),
    cerrada("b1", "B.1 Obtención y Revisión", "im10", D(2026, 10, 15)),
    cerrada("b2", "B.2 Elaboración de Informe", "im10", D(2026, 10, 22)),
    tarea("b10", "B.10 Informe Rev.0", "im10"),
    cerrada("b7", "B.7 Informe Rev. B", "im10", D(2026, 10, 29)),
    tarea("b8", "B.8 Observaciones Mandante", "im10"),
    tarea("b9", "B.9 Levantamiento", "im10", "no aplica", tipo="custom"),
    # IM-11 MLC = octubre: plazo 20-nov, pendiente
    tarea("im11", "IM-11 Informe Mensual N°11", "f19", "to do", D(2026, 12, 2), start=D(2026, 11, 12)),
    # IM-04 Apilador = agosto: plazo 20-sep, sin subtareas, cerrado el 25-sep
    tarea("im4", "IM-04 Informe Mensual N°4", "f147", "completado", D(2026, 9, 24), D(2026, 9, 25), "done",
          start=D(2026, 9, 10)),
    # IM-06.0 no es mensual numerado: plazo = vencimiento de ClickUp
    tarea("laser", "IM-06.0 Informe Levantamiento Láser", "f19", "en progreso", D(2026, 9, 4)),
]


def test_periodo_por_ancla():
    c = P.contratos["0019"]
    assert c.periodo_informe(8) == D(2026, 7, 1) and c.periodo_informe(10) == D(2026, 9, 1)
    assert c.periodo_informe(13) == D(2026, 12, 1) and c.periodo_informe(14) == D(2027, 1, 1)
    assert c.periodo_informe(1) == D(2025, 12, 1)
    assert PG.desde_dict("X", {**CONFIG, "contratos": {"0019": {"nombre": "x"}}}).contratos["0019"].periodo_informe(3) \
        is None


def test_informe_plazo_dia_20_y_entrega_por_rev_b():
    por = {f["task_id"]: f for f in PG.filas_entregables(P, "INF", INFORMES, CORTE, E.PRELIMINAR, "x")}
    assert set(por) == {"im10", "im11", "im4", "laser"}
    f = por["im10"]
    assert (f["contrato"], f["periodo"], f["plazo"], f["origen_plazo"]) == ("0019", D(2026, 9, 1), D(2026, 10, 20),
                                                                           PG.REGLA)
    assert (f["entregado"], f["fecha_entregado"], f["situacion"], f["dias_atraso"]) == (True, D(2026, 10, 29),
                                                                                       PG.ATRASADO, 9)
    assert (f["pasos_total"], f["pasos_cerrados"], f["avance"]) == (5, 3, 0.6)       # B.9 no aplica
    assert f["paso_actual"] == "B.8 Observaciones Mandante"                          # orden por codigo: B.8 antes que B.10
    assert (f["inicio"], f["dias_elaboracion"]) == (D(2026, 10, 13), 16)
    assert f["fecha_entrega"] == D(2026, 10, 30) and f["fecha_cierre"] is None       # ClickUp, sin cambios
    assert (por["im11"]["plazo"], por["im11"]["situacion"]) == (D(2026, 11, 20), PG.PENDIENTE)
    g = por["im4"]
    assert (g["contrato"], g["periodo"], g["plazo"], g["situacion"], g["dias_atraso"]) == (
        "0147", D(2026, 8, 1), D(2026, 9, 20), PG.ATRASADO, 5)
    assert (g["avance"], g["pasos_total"]) == (1.0, None)
    h = por["laser"]
    assert (h["periodo"], h["plazo"], h["origen_plazo"], h["situacion"]) == (None, D(2026, 9, 4), PG.CLICKUP_DUE,
                                                                             PG.VENCIDO)
    assert set(f) == set(E.columnas("programa_entregables"))


def test_pasos_en_orden_y_dias_entre_cierres():
    entregables = PG.filas_entregables(P, "INF", INFORMES, CORTE, E.PRELIMINAR, "x")
    pasos = [f for f in PG.filas_pasos(P, entregables, INFORMES) if f["task_id"] == "im10"]
    assert [f["paso"].split()[0] for f in pasos] == ["B.1", "B.2", "B.7", "B.8", "B.9", "B.10"]
    assert [f["dias_desde_anterior"] for f in pasos] == [None, 7, 7, None, None, None]
    assert pasos[4]["no_aplica"] and not pasos[4]["cerrado"]
    assert set(pasos[0]) == set(E.columnas("programa_pasos"))


VISITAS = [tarea("g", "MLC 0019", lista="GEN"),
           tarea("vt3", "VT-03 Visita de Mantención", "g", "en progreso", D(2026, 10, 30), lista="GEN",
                 asignados=("Fernando",)),
           tarea("a1", "A.1 Preparación y Logística", "vt3", lista="GEN"),
           tarea("a5", "A.5 Trabajos en Terreno", "vt3", start=D(2026, 11, 10), due=D(2026, 11, 12), lista="GEN",
                 asignados=("Luciano", "Matías"))]


def test_visita_terreno_y_historial_de_fechas():
    [v] = PG.filas_entregables(P, "GEN", VISITAS, CORTE, E.PRELIMINAR, "x")
    assert (v["terreno_inicio"], v["terreno_fin"], v["asignados_terreno"]) == (D(2026, 11, 10), D(2026, 11, 12),
                                                                              "Luciano, Matías")
    # Primera corrida: registra las fechas vigentes
    h1 = PG.filas_fechas([v], [], P.reglas, CORTE, E.PRELIMINAR)
    assert {(f["campo"], f["valor"], f["valor_anterior"]) for f in h1} == {
        ("vencimiento", D(2026, 10, 30), None), ("terreno_inicio", D(2026, 11, 10), None),
        ("terreno_fin", D(2026, 11, 12), None)}
    assert set(h1[0]) == set(E.columnas("programa_fechas"))
    # Sin cambios: nada nuevo
    assert PG.filas_fechas([v], h1, P.reglas, D(2026, 11, 4), E.PRELIMINAR) == []
    # Se reagenda el terreno
    v2 = {**v, "terreno_inicio": D(2026, 11, 17), "terreno_fin": D(2026, 11, 19)}
    h2 = PG.filas_fechas([v2], h1, P.reglas, D(2026, 11, 5), E.PRELIMINAR)
    assert {(f["campo"], f["valor_anterior"]) for f in h2} == {("terreno_inicio", D(2026, 11, 10)),
                                                              ("terreno_fin", D(2026, 11, 12))}
    r = PG.reprogramaciones([*h1, *h2])["vt3"]
    assert (r["n"], r["fecha_original"]) == (2, D(2026, 11, 10))
    # Los informes no llevan historial
    assert PG.filas_fechas(PG.filas_entregables(P, "INF", INFORMES, CORTE, E.PRELIMINAR, "x"), [], P.reglas, CORTE,
                           E.PRELIMINAR) == []


def test_oficios_semanales_solo_hojas():
    p = PG.desde_dict("AITO", {**CONFIG, "entregables": {
        "oficio": {"patron": "^\\s*Revisi[oó]n\\s+Oficios\\b", "frecuencia": "semanal", "solo_hojas": True}}})
    tareas = [tarea("f", "05 Revisión Oficios y Anexo II para EP"),
              tarea("ene", "Revisión Oficios Enero 2026", "f", "completado", D(2026, 1, 31), D(2026, 2, 2), "done"),
              tarea("oct", "Revisión Oficios Octubre 2026", "f"),
              tarea("s1", "Revisión Oficios Oct 2026 S1", "oct", "completado", D(2026, 10, 9), D(2026, 10, 9), "done"),
              tarea("s2", "Revisión Oficios Oct 2026 S2", "oct", "to do", D(2026, 10, 16))]
    por = {f["task_id"]: f for f in PG.filas_entregables(p, "INF", tareas, CORTE, E.PRELIMINAR, "x")}
    assert set(por) == {"ene", "s1", "s2"}                    # el mes dividido en semanas no cuenta aparte
    assert (por["s1"]["situacion"], por["s2"]["situacion"], por["s2"]["dias_atraso"]) == (PG.A_TIEMPO, PG.VENCIDO, 18)
    assert por["ene"]["frecuencia"] == PG.SEMANAL


def _tis(*estados):
    ms = lambda d: str(int(d.timestamp() * 1000))
    hist = [{"status": s, "total_time": {"by_minute": 1, "since": ms(d)}} for s, d in estados]
    return {"current_status": hist[-1], "status_history": hist}


def test_reportes_diarios_tiempos():
    t0 = dt.datetime(2026, 11, 3, 17, 6, tzinfo=TZ)
    m = lambda x: t0 + dt.timedelta(minutes=x)
    usuarios = lambda n: CustomField("x", n, "users", [n], None)
    rep = lambda tid, nombre, **kw: tarea(tid, nombre, lista="RD", creada=t0, **kw)
    tareas = [rep("r1", "Reporte diario · 03-nov-2026 · 1700", status="enviado",
                  cf={"Revisado por": usuarios("Fernando"), "Aprobada por": usuarios("Sergio")}),
              rep("r2", "Reporte diario · 03-nov-2026 · 0800", status="enviado"),
              rep("r3", "Reporte diario · 04-nov-2026 · 0800", status="pendiente revisión"),
              rep("r4", "Reporte diario · 02-nov-2026 · 1700", status="aprobado"),
              rep("r5", "Reporte diario · 01-nov-2026 · 0800", status="enviado",
                  cf={"Fecha aprobación": CustomField("x", "Fecha aprobación", "date", m(95), None)})]
    tis = {"r1": _tis(("pendiente revisión", t0), ("observado", m(30)), ("revisado", m(152)), ("aprobado", m(180)),
                      ("enviado", m(181))),
           "r2": _tis(("pendiente revisión", t0), ("enviado", m(300))),             # cerrado a mano: no se envio
           "r3": _tis(("pendiente revisión", t0)),
           "r4": _tis(("pendiente revisión", t0), ("aprobado", m(60))),             # sin «revisado»
           # «aprobado» menos de un minuto: no queda en el historial, pero si en «Fecha aprobación»
           "r5": _tis(("pendiente revisión", t0), ("revisado", m(70)), ("enviado", m(96)))}
    filas = RD.filas("CMP-SHM", "Monitoreo", "CMP", tareas, tis, CORTE, E.PRELIMINAR)
    assert [f["task_id"] for f in filas] == ["r5", "r4", "r2", "r1"]                    # sin el del 04-nov (> corte)
    por = {f["task_id"]: f for f in filas}
    a = por["r1"]
    assert (a["fecha"], a["turno"], a["observado"], a["enviado"]) == (D(2026, 11, 3), "17:00", True, True)
    assert (a["min_generacion_revision"], a["min_revision_aprobacion"], a["min_aprobacion_envio"],
            a["min_generacion_envio"]) == (152.0, 28.0, 1.0, 181.0)
    assert (a["revisado_por"], a["aprobado_por"]) == ("Fernando", "Sergio")
    b = por["r2"]
    assert (b["enviado"], b["cerrado_sin_aprobar"], b["enviado_en"], b["min_generacion_envio"]) == (False, True, None,
                                                                                                   None)
    c = por["r4"]
    assert (c["min_revision_aprobacion"], c["enviado"], c["cerrado_sin_aprobar"]) == (None, False, False)
    e = por["r5"]
    assert (e["enviado"], e["cerrado_sin_aprobar"], e["min_revision_aprobacion"], e["min_generacion_envio"]) == (
        True, False, 25.0, 96.0)
    assert set(a) == set(E.columnas("programa_reportes_diarios"))


def test_config_del_repo_tiene_las_reglas():
    progs = PG.cargar(PG.Path(__file__).resolve().parents[1] / "config" / "programas.json")
    cmp = progs["CMP-SHM"]
    assert cmp.reportes_diarios == "901329132533"
    assert cmp.reglas["informe"].plazo_dia_mes_siguiente == 20 and cmp.reglas["visita"].seguir_fechas
    assert cmp.contratos["0019"].periodo_informe(10) == D(2026, 9, 1)
    assert cmp.contratos["0147"].periodo_informe(5) == D(2026, 9, 1)
    for pid in ("AITO-HPC", "AITO-SOTERO"):
        assert progs[pid].reglas["oficio"].solo_hojas and progs[pid].reglas["visita"].seguir_fechas
