"""Como resolver cada advertencia, quien lo hace y que impacto tiene. Funciones puras.

Cada tipo de advertencia (proyecto.ADV_* y calidad.SEVERIDAD) debe estar en CATALOGO; los que aun no tienen
solucion acordada con Administracion DEP estan en PENDIENTES y dejan las tres columnas vacias.
docs/guia_advertencias.md se genera desde este modulo (scripts/guia_advertencias.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from . import presentacion as PR
from .config_reportes import parametros

JP, INFORMATIVA = "JP", "Informativa"
IMPIDE, DISTORSIONA = "Impide la curva S", "Distorsiona las cifras"
MAX_NOMBRE = 45                   # nombres de tarea o lista mas largos se recortan con …


def administracion() -> str:
    """Nombre del area que administra las lineas base (config/reportes.json)."""
    return parametros().get("responsable_administracion", "Administración DEP")


@dataclass(frozen=True)
class Contexto:
    tarea: str | None = None          # nombre de la tarea afectada
    lista: str | None = None          # etiqueta del proyecto ("2026.0152 · nombre")
    tiene_linea_base: bool = True
    datos: Mapping | None = None


@dataclass(frozen=True)
class Entrada:
    significado: str
    responsable: str                                    # JP, ADMIN (se reemplaza por administracion()) o INFORMATIVA
    impacto_con_lb: str
    impacto_sin_lb: str
    accion: Callable[[Contexto, str], str]              # (contexto, nombre de administracion) -> texto

    def impacto(self, tiene_linea_base: bool) -> str:
        return self.impacto_con_lb if tiene_linea_base else self.impacto_sin_lb


ADMIN = "__administracion__"


def _corto(txt: str | None, defecto: str) -> str:
    if not txt:
        return defecto
    txt = " ".join(txt.split())
    return txt if len(txt) <= MAX_NOMBRE else txt[:MAX_NOMBRE - 1].rstrip() + "…"


def _t(c: Contexto) -> str:
    return f"«{_corto(c.tarea, 'la tarea')}»" if c.tarea else "la tarea indicada"


def _l(c: Contexto) -> str:
    return f"«{_corto(c.lista, 'la lista')}»" if c.lista else "del proyecto"


def _doble_conteo(c: Contexto, adm: str) -> str:
    txt = (f"En ClickUp, deja las HH Presupuestadas solo en las subtareas de {_t(c)} y bórralas del padre; "
           "si el padre tenía el total, repártelo entre ellas.")
    return txt if c.tiene_linea_base else txt + f" Luego avisa a {adm}."


def _sin_fechas(c: Contexto, adm: str) -> str:
    falta = (c.datos or {}).get("falta")
    que = {"start": "fecha de inicio", "due": "fecha de término"}.get(falta, "fecha de inicio y de término")
    return f"En ClickUp, asigna {que} a {_t(c)}."


def _nombre_sin_formato(c: Contexto, adm: str) -> str:
    d = c.datos or {}
    if d.get("codigo") and d.get("nombre"):
        nuevo = f"{d['codigo']} | {_corto(d['nombre'], '')} | cliente"
    else:
        nuevo = "PJ-XXXX | nombre del proyecto | cliente"
    return f"En ClickUp, renombra la lista como «{nuevo}»."


def _tardia(c: Contexto, adm: str) -> str:
    f = (c.datos or {}).get("fecha")
    cuando = f"al {PR.fecha(f)}" if f else "a la fecha de captura"
    return (f"La línea base se tomó con el plan vigente {cuando}, no con el plan original; si no lo representa, "
            f"pide una revisión a {adm}.")


def _codigo_duplicado(c: Contexto, adm: str) -> str:
    cod = (c.datos or {}).get("codigo_base")
    return (f"En ClickUp, corrige el código {cod} en el nombre de una de las dos listas que lo usan." if cod else
            "En ClickUp, corrige el código en el nombre de una de las dos listas que lo comparten.")


CATALOGO: dict[str, Entrada] = {
    "hh_en_padre_y_subtarea": Entrada(
        "La tarea padre y sus subtareas tienen HH Presupuestadas: las HH se cuentan dos veces.",
        JP, DISTORSIONA, IMPIDE, _doble_conteo),
    "hh_sin_start_o_due": Entrada(
        "Una tarea con HH Presupuestadas no tiene fecha de inicio o de término: sus HH no se pueden repartir en el tiempo.",
        JP, DISTORSIONA, IMPIDE, _sin_fechas),
    "due_anterior_a_start": Entrada(
        "La fecha de término de una tarea es anterior a su fecha de inicio.",
        JP, DISTORSIONA, DISTORSIONA, lambda c, a: f"En ClickUp, corrige las fechas de {_t(c)}: el término debe ser "
                                                   "posterior al inicio."),
    "avance_sin_horas": Entrada(
        "Una tarea tiene Avance Real mayor que cero pero no tiene horas registradas.",
        JP, DISTORSIONA, DISTORSIONA, lambda c, a: f"En ClickUp, registra las horas trabajadas en {_t(c)} (en la "
                                                   "subtarea, nunca en el padre) o corrige su Avance Real si aún no "
                                                   "se ha trabajado."),
    "horas_sin_avance": Entrada(
        "Una tarea tiene horas registradas pero su Avance Real sigue en 0 %.",
        JP, DISTORSIONA, DISTORSIONA, lambda c, a: f"En ClickUp, actualiza el Avance Real de {_t(c)}."),
    "en_planificacion": Entrada(
        "La tarea 1.2 Plan de Trabajo sigue abierta: el proyecto está en planificación y aún no tiene línea base.",
        JP, IMPIDE, IMPIDE, lambda c, a: f"En la lista {_l(c)}, cuando todas las tareas tengan HH y fechas, marca "
                                         "«1.2 Plan de Trabajo» como completada; la línea base se congela en la "
                                         "siguiente actualización."),
    "tarea_1_2_no_aplica": Entrada(
        "La tarea 1.2 Plan de Trabajo está en No Aplica: la línea base no se congela automáticamente.",
        JP, IMPIDE, IMPIDE, lambda c, a: f"En la lista {_l(c)}, completa las HH y fechas del plan y avisa a {a} "
                                         "para congelar la línea base."),
    "linea_base_sin_hh": Entrada(
        "Correspondía congelar la línea base, pero ninguna tarea tiene HH Presupuestadas.",
        JP, IMPIDE, IMPIDE, lambda c, a: f"En la lista {_l(c)}, carga las HH Presupuestadas en las tareas finales "
                                         "(subtareas) del proyecto."),
    "linea_base_tardia": Entrada(
        "La línea base se congeló después de cerrada la 1.2 (o sin 1.2), con el plan de ese día.",
        INFORMATIVA, INFORMATIVA, INFORMATIVA, _tardia),
    "no_aplica_con_hh": Entrada(
        "Una tarea en No Aplica tiene HH Presupuestadas.",
        JP, DISTORSIONA, DISTORSIONA, lambda c, a: f"En ClickUp, borra las HH Presupuestadas de {_t(c)} o, si sí "
                                                   "aplica, cambia su estado."),
    "proyecto_con_termino_vencido": Entrada(
        "La fecha de vencimiento de la lista ya pasó y el proyecto tiene trabajo pendiente.",
        JP, DISTORSIONA, DISTORSIONA, lambda c, a: f"Si hay nueva fecha con el cliente, actualiza el "
                                                   f"vencimiento de la lista {_l(c)} y pide a {a} una revisión de "
                                                   "línea base; si ya se entregó, cierra lo pendiente."),
    "hh_cambiaron_vs_linea_base": Entrada(
        "El total de HH Presupuestadas en ClickUp ya no coincide con el de la línea base.",
        JP, INFORMATIVA, INFORMATIVA, lambda c, a: f"Si el alcance cambió de verdad, pide a {a} una revisión de "
                                                   f"línea base; si fue un error, vuelve a las HH anteriores en la "
                                                   f"lista {_l(c)}."),
    "sin_jp": Entrada(
        "La lista no tiene responsable (JP) en ClickUp, o el responsable no es miembro del espacio.",
        ADMIN, IMPIDE, IMPIDE, lambda c, a: f"En ClickUp, asigna el responsable (JP) de la lista {_l(c)}."),
    "codigo_duplicado_en_clickup": Entrada(
        "Dos listas de ClickUp usan el mismo código de proyecto; en los reportes se distinguen con -A y -B.",
        ADMIN, INFORMATIVA, INFORMATIVA, _codigo_duplicado),
    "nombre_lista_sin_formato": Entrada(
        "El nombre de la lista no sigue el formato «código | nombre | cliente»: el reporte no puede mostrar el cliente.",
        JP, INFORMATIVA, INFORMATIVA, _nombre_sin_formato),
}

# Tipos sin solucion acordada todavia: columnas vacias hasta que se definan (propuestas en el informe).
PENDIENTES: dict[str, str] = {
    "sin_tarea_1_2": "No hay tarea 1.2 Plan de Trabajo en la fase 01.",
    "varias_tareas_1_2": "Hay más de una tarea 1.2 en la fase 01.",
    "sin_termino_vigente": "La lista no tiene fecha de vencimiento.",
    "tarea_de_linea_base_ahora_no_aplica": "Una tarea de la línea base está hoy en No Aplica.",
    "hh_en_tarea_no_hoja": "Una tarea padre tiene HH Presupuestadas y sus subtareas no.",
    "hh_distinta_de_time_estimate": "Las HH Presupuestadas de una tarea no coinciden con su time estimate.",
}


def resolver(tipo: str, ctx: Contexto) -> dict:
    """{como_resolver, responsable_accion, impacto}; vacias (None) si el tipo esta pendiente."""
    e = CATALOGO.get(tipo)
    if e is None:
        return {"como_resolver": None, "responsable_accion": None, "impacto": None}
    adm = administracion()
    return {"como_resolver": e.accion(ctx, adm),
            "responsable_accion": adm if e.responsable == ADMIN else e.responsable,
            "impacto": e.impacto(ctx.tiene_linea_base)}


# --- Acciones agrupadas (mensajes a los JP) -----------------------------------------------------
# Cuando un proyecto repite un tipo en varias tareas, el mensaje lo junta en un solo punto.

MAX_TAREAS_LISTADAS = 8


def lista_tareas(tareas: list[str], maximo: int = MAX_TAREAS_LISTADAS) -> str:
    nombres = [f"«{_corto(t, 'tarea sin nombre')}»" for t in tareas]
    txt = "; ".join(nombres[:maximo])
    resto = len(nombres) - maximo
    return txt + (f" y {resto} más (el detalle está en el reporte, sección Para revisar)" if resto > 0 else "")


# (tareas listadas, cantidad, tiene_linea_base, administracion) -> texto
ACCION_GRUPAL: dict[str, Callable[[str, int, bool, str], str]] = {
    "hh_en_padre_y_subtarea": lambda ts, n, lb, a: (
        f"En ClickUp, deja las HH Presupuestadas solo en las subtareas y bórralas del padre en estas {n} tareas: "
        f"{ts}. Si el padre tenía el total, repártelo entre sus subtareas." + ("" if lb else f" Luego avisa a {a}.")),
    "hh_sin_start_o_due": lambda ts, n, lb, a: (
        f"En ClickUp, asigna las fechas de inicio y de término que faltan a estas {n} tareas: {ts}."),
    "due_anterior_a_start": lambda ts, n, lb, a: (
        f"En ClickUp, corrige las fechas de estas {n} tareas (el término debe ser posterior al inicio): {ts}."),
    "avance_sin_horas": lambda ts, n, lb, a: (
        f"Estas {n} tareas tienen avance pero no tienen horas registradas: {ts}. En ClickUp, registra las horas "
        "trabajadas (en la subtarea, nunca en el padre) o corrige su Avance Real si aún no se ha trabajado."),
    "horas_sin_avance": lambda ts, n, lb, a: (
        f"En ClickUp, actualiza el Avance Real de estas {n} tareas, que tienen horas registradas y 0 % de avance: {ts}."),
    "no_aplica_con_hh": lambda ts, n, lb, a: (
        f"En ClickUp, borra las HH Presupuestadas de estas {n} tareas en No Aplica o, si sí aplican, cambia su "
        f"estado: {ts}."),
}
