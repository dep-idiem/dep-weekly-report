"""Mensajes por JP (texto para enviar a mano)."""
import datetime as dt
from pathlib import Path

from dep_reportes import mensajes_jp as M, resolucion as RES

C = dt.date(2026, 9, 20)
CFG = {"responsable_administracion": "Administración DEP", "enlace_reporte": "https://ejemplo/reporte",
       "fecha_primer_reporte_oficial": "2026-09-28"}
PLANTILLA = (Path(__file__).resolve().parents[1] / "config" / "plantilla_mensaje_jp.txt").read_text(encoding="utf-8")


def _ms(lid, cod, jp, lb):
    return {"corte": C, "tipo_corte": "oficial", "list_id": lid, "codigo": cod, "proyecto": f"{cod[3:]} · Proyecto {lid}",
            "jp_nombre": jp, "tiene_linea_base": lb, "es_ultimo_corte": True}


def _adv(lid, tipo, task="", lb=True, tarea=None):
    ctx = RES.Contexto(tarea, f"Proyecto {lid}", lb, {"falta": "start y due"})
    return {"corte": C, "tipo_corte": "oficial", "list_id": lid, "tipo": tipo, "task_id": task,
            "mensaje": f"«{tarea}» algo" if tarea else "algo", **RES.resolver(tipo, ctx)}


def _tablas():
    adv = [_adv("1", "en_planificacion", lb=False)]
    adv += [_adv("2", "hh_sin_start_o_due", f"t{i}", tarea=f"Tarea {i}") for i in range(20)]
    adv += [_adv("2", "horas_sin_avance", "h1", tarea="7.2 Revisión JP"),
            _adv("2", "hh_cambiaron_vs_linea_base"),                     # JP, informativa: no va
            _adv("2", "linea_base_tardia"),                              # informativa: no va
            _adv("2", "hh_distinta_de_time_estimate", "t0"),             # pendiente de definir: no va
            _adv("3", "sin_jp", lb=False), _adv("3", "codigo_duplicado_en_clickup", lb=False)]
    return {"metricas_semanales": [_ms("2", "PJ-2026.0002", "Ana Pérez", True), _ms("1", "PJ-2026.0001", "Ana Pérez", False),
                                   _ms("3", "PJ-2026.0003", "Sin JP", False), _ms("4", "PJ-2026.0004", "Luis Soto", True)],
            "advertencias": adv,
            "fotos_tareas": [{"corte": C, "list_id": "2", "task_id": "t3", "task_nombre": "Nombre desde la foto"}]}


def test_un_mensaje_por_jp_y_uno_para_administracion():
    out = M.generar(_tablas(), C, "oficial", CFG, PLANTILLA)
    assert set(out) == {"Ana Pérez.txt", "Luis Soto.txt", "_administracion.txt"}


def test_contenido_del_mensaje():
    txt = M.generar(_tablas(), C, "oficial", CFG, PLANTILLA)["Ana Pérez.txt"]
    assert txt.startswith("Hola, Ana:") and "https://ejemplo/reporte" in txt and "28-09-2026" in txt
    # primero el proyecto sin curva S
    assert txt.index("2026.0001 · Proyecto 1") < txt.index("2026.0002 · Proyecto 2")
    assert "Todavía no tiene curva S porque el proyecto está en planificación" in txt
    assert "Estado: Tiene curva S." in txt
    # repeticiones agrupadas, 8 nombres y el resto contado; nombre desde fotos_tareas
    assert "a estas 20 tareas:" in txt and "y 12 más (el detalle está en el reporte, sección Para revisar)" in txt
    assert "«Nombre desde la foto»" in txt and "«Tarea 8»" not in txt
    # distorsiona despues; informativas, pendientes y de administracion no van
    assert txt.index("20 tareas") < txt.index("Avance Real de «7.2 Revisión JP»")
    for fuera in ("revisión de línea base; si fue un error", "plan original", "time estimate", "renombra", "código"):
        assert fuera not in txt, fuera


def test_sin_observaciones_y_sin_jp():
    out = M.generar(_tablas(), C, "oficial", CFG, PLANTILLA)
    assert "Puntos a corregir: Sin observaciones." in out["Luis Soto.txt"]
    adm = out["_administracion.txt"]
    assert "asigna el responsable (JP)" in adm and "corrige el código" in adm
    assert "Proyectos sin JP" in adm and "2026.0003 · Proyecto 3" in adm
    assert "Sin JP.txt" not in out


def test_enlace_pendiente_si_falta_en_config():
    txt = M.generar(_tablas(), C, "oficial", {**CFG, "enlace_reporte": ""}, PLANTILLA)["Luis Soto.txt"]
    assert M.ENLACE_PENDIENTE in txt


def test_sin_voseo():
    for txt in M.generar(_tablas(), C, "oficial", CFG, PLANTILLA).values():
        for v in ("tenés", "podés", "revisá", "asigná", "corregí", "respondé", "vos "):
            assert v not in txt.lower()


def test_lista_tareas():
    assert RES.lista_tareas(["a", "b"]) == "«a»; «b»"
    assert RES.lista_tareas([str(i) for i in range(9)]).endswith("«7» y 1 más (el detalle está en el reporte, "
                                                                  "sección Para revisar)")


def test_nombre_de_archivo_seguro():
    assert M.archivo('Ana/Pérez: "JP"') == "Ana_Pérez_ _JP"
