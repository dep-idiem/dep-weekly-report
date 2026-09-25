"""Columnas de presentacion para Looker Studio: nombre corto, cliente, etiqueta del proyecto, titular de
avance y mensajes de advertencia en español. Funciones puras.

Numeros con coma decimal; fechas dd-mm-aaaa.
"""
from __future__ import annotations

import datetime as dt
from typing import Mapping

from dep_clickup.naming import list_code

from .proyecto import NIVEL_PROYECTO as TIPOS_NIVEL_PROYECTO

UMBRAL_EN_LINEA_PTS = 0.5
NIVEL_PROYECTO, NIVEL_TAREA = "proyecto", "tarea"


# --- Nombre de la lista -------------------------------------------------------------------------

def _limpio(s: str) -> str:
    return " ".join(s.split())


def partes_nombre(nombre: str) -> tuple[str, str | None, bool]:
    """(nombre_corto, cliente, sigue_formato) de una lista "PJ-XXXX | nombre | cliente".

    Si la lista no sigue el formato se devuelve el nombre completo sin el codigo (la etiqueta ya lo lleva)
    y sin cliente."""
    partes = [_limpio(p) for p in (nombre or "").split("|")]
    if len(partes) == 3 and all(partes) and list_code(partes[0]) == partes[0]:
        return partes[1], partes[2], True
    completo = _limpio(nombre or "")
    codigo = list_code(completo)
    sin_codigo = completo[len(codigo):].lstrip(" |-–") if codigo else completo
    return sin_codigo or completo, None, False


def etiqueta_proyecto(codigo: str, nombre_corto: str) -> str:
    return f"{codigo.removeprefix('PJ-')} · {nombre_corto}"


# --- Formato ------------------------------------------------------------------------------------

def num(x: float, dec: int = 1) -> str:
    return f"{x:.{dec}f}".replace(".", ",")


def hh(x) -> str:
    """HH sin decimales sobrantes: 240 -> "240", 12.5 -> "12,5"."""
    return f"{round(float(x), 2):g}".replace(".", ",")


def pct(fraccion: float) -> str:
    return f"{num(fraccion * 100)} %"


def fecha(d) -> str:
    return d.strftime("%d-%m-%Y") if isinstance(d, (dt.date, dt.datetime)) else str(d)


# --- metricas_semanales -------------------------------------------------------------------------

def desviacion_pts(avance_real: float | None, avance_prog: float | None) -> float | None:
    if avance_real is None or avance_prog is None:
        return None
    return (avance_real - avance_prog) * 100


def pct_presupuesto_usado(hh_gastadas: float | None, hh_linea_base: float | None) -> float | None:
    """Fraccion (0,5 = 50 %) de las HH de la linea base ya gastadas."""
    if hh_gastadas is None or not hh_linea_base:
        return None
    return hh_gastadas / hh_linea_base


# Motivos sin linea base, en orden de prioridad (el primero que aplique).
MOTIVOS_SIN_LB = [
    ("linea_base_sin_hh", "no hay tareas con HH presupuestadas"),
    ("hh_en_padre_y_subtarea", "hay HH contadas dos veces; la línea base se congelará cuando se corrija"),
    ("tarea_1_2_no_aplica", "la tarea 1.2 está en No Aplica y la línea base se congela a mano"),
    ("en_planificacion", "el proyecto está en planificación (la tarea 1.2 sigue abierta)"),
    ("sin_tarea_1_2", "no hay tarea 1.2 en la fase 01 y la línea base se congela a mano"),
]
MOTIVO_GENERICO = "el proyecto aún no tiene línea base congelada"


def motivo_sin_linea_base(tipos_advertencia) -> str:
    tipos = set(tipos_advertencia)
    return next((txt for t, txt in MOTIVOS_SIN_LB if t in tipos), MOTIVO_GENERICO)


def miles(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def titular(tiene_linea_base: bool, avance_real: float | None, avance_prog: float | None,
            motivo: str | None = None, presupuesto: Mapping | None = None) -> str:
    if not tiene_linea_base:
        p = presupuesto or {}
        if p.get("hh_contrato") and p.get("pct_contrato_usado") is not None:
            txt = (f"Sin curva programada. Consumidas {miles(p['pct_contrato_usado'] * p['hh_contrato'])} de "
                   f"{miles(p['hh_contrato'])} HH contratadas ({num(p['pct_contrato_usado'] * 100, 0)} %)")
            if p["pct_contrato_usado"] >= 1:
                return txt + ": presupuesto superado."
            if p.get("fecha_agotamiento_estimada"):
                return txt + f"; al ritmo actual se agotan el {fecha(p['fecha_agotamiento_estimada'])}."
            return txt + "."
        return f"Sin curva programada: {motivo or MOTIVO_GENERICO}."
    if avance_prog is None:
        return "Línea base sin avance programado calculable."
    if avance_real is None:
        return f"Sin avance real registrado frente a {pct(avance_prog)} programado."
    d = desviacion_pts(avance_real, avance_prog)
    base = f"Avance real {pct(avance_real)} frente a {pct(avance_prog)} programado: "
    if abs(d) < UMBRAL_EN_LINEA_PTS:
        return base + "en línea con el plan."
    return base + f"{num(abs(d))} puntos {'bajo' if d < 0 else 'sobre'} el plan."


def derivadas_semanales(fila: Mapping, motivo: str | None = None) -> dict:
    """Columnas de presentacion de una fila de metricas_semanales (tambien para filas antiguas)."""
    tiene = fila.get("rev_linea_base") is not None
    return {
        "tiene_linea_base": tiene,
        "desviacion_pts": desviacion_pts(fila.get("avance_real"), fila.get("avance_prog")) if tiene else None,
        "pct_presupuesto_usado": pct_presupuesto_usado(fila.get("hh_gastadas_acum"), fila.get("total_hh")) if tiene else None,
        "titular": titular(tiene, fila.get("avance_real"), fila.get("avance_prog"), motivo, fila),
    }


# --- Advertencias -------------------------------------------------------------------------------

def nivel(tipo: str) -> str:
    """"proyecto" (se muestra siempre) o "tarea" (solo si la tarea tiene HH): ver proyecto.NIVEL_PROYECTO."""
    return NIVEL_PROYECTO if tipo in TIPOS_NIVEL_PROYECTO else NIVEL_TAREA


def _t(tarea: str | None) -> str:
    return f"«{tarea}»" if tarea else "Una tarea"


def mensaje(tipo: str, tarea: str | None = None, datos: Mapping | None = None) -> str:
    """Advertencia como frase lista para mostrar, sin codigos tecnicos. Si faltan datos (filas de cortes
    antiguos) la frase sale generica."""
    d = dict(datos or {})
    t = _t(tarea)
    if tipo == "sin_jp":
        if d.get("responsable"):
            return f"El responsable de la lista ({d['responsable']}) no está entre los miembros de ClickUp: revisar la asignación"
        return "La lista no tiene jefe de proyecto asignado en ClickUp: asignar un responsable"
    if tipo == "en_planificacion":
        return "Proyecto en planificación (la tarea 1.2 sigue abierta): todavía no tiene línea base"
    if tipo == "sin_tarea_1_2":
        if d.get("tardia"):
            return "No hay tarea 1.2 en la fase 01: la línea base se congela con la foto del día"
        return "No hay tarea 1.2 en la fase 01: la línea base no se congela automáticamente"
    if tipo == "tarea_1_2_no_aplica":
        return f"{t} está en No Aplica: la línea base no se congela automáticamente"
    if tipo == "varias_tareas_1_2":
        n = f"{d['n']} tareas" if "n" in d else "Varias tareas"
        return f"{n} 1.2 en la fase 01: se usa {t}; dejar solo una"
    if tipo == "proyecto_con_termino_vencido":
        cuando = f" ({fecha(d['fin'])})" if d.get("fin") else ""
        return f"La fecha de término{cuando} ya pasó: actualizar el vencimiento de la lista si el proyecto sigue en curso"
    if tipo == "sin_termino_vigente":
        return "La lista no tiene fecha de vencimiento en ClickUp: definirla"
    if tipo == "no_aplica_con_hh":
        cuanto = f"{hh(d['hh'])} HH presupuestadas" if "hh" in d else "HH presupuestadas"
        return f"{t} está en No Aplica pero tiene {cuanto}: quitarlas o cambiar el estado"
    if tipo == "hh_cambiaron_vs_linea_base":
        if "actual" in d and "linea_base" in d:
            cuales = f"de {d['n']} paquete(s) congelado(s) " if d.get("n") else ""
            return (f"Las HH presupuestadas {cuales}cambiaron: {hh(d['actual'])} en ClickUp frente a "
                    f"{hh(d['linea_base'])} en la línea base; evaluar una revisión")
        return "Las HH presupuestadas en ClickUp ya no coinciden con la línea base: evaluar una revisión"
    if tipo == "tarea_de_linea_base_ahora_no_aplica":
        return f"{t} está en la línea base pero hoy está en No Aplica: evaluar una revisión de la línea base"
    if tipo == "linea_base_tardia":
        cuando = f" el {fecha(d['fecha'])}" if d.get("fecha") else ""
        return f"Línea base congelada tarde{cuando}, cuando la tarea 1.2 ya estaba cerrada o no existía"
    if tipo == "linea_base_sin_hh":
        return "No hay tareas con HH presupuestadas: no se puede congelar la línea base"
    if tipo == "codigo_duplicado_en_clickup":
        if d.get("codigo_base") and d.get("codigo"):
            return (f"Otra lista de ClickUp usa el mismo código {d['codigo_base']}: en los reportes esta aparece "
                    f"como {d['codigo']}")
        return "Otra lista de ClickUp usa el mismo código: cambiar uno de los dos"
    if tipo == "nombre_lista_sin_formato":
        return "El nombre de la lista no sigue el formato «código | nombre | cliente»: se muestra el nombre sin cliente"
    if tipo == "hh_en_padre_y_subtarea":
        donde = f" en {tarea}" if tarea else ""
        return f"HH contadas dos veces{donde}: corregir antes de congelar la línea base"
    if tipo == "hh_en_tarea_no_hoja":
        return f"{t} tiene HH pero sus subtareas no: pasar las HH a las subtareas"
    if tipo == "hh_sin_start_o_due":
        falta = {"start": "le falta la fecha de inicio", "due": "le falta la fecha de término",
                 "start y due": "le faltan las fechas de inicio y término"}.get(d.get("falta"), "le faltan fechas")
        return f"{t} tiene HH pero {falta}"
    if tipo == "due_anterior_a_start":
        return f"{t} termina antes de empezar: revisar las fechas"
    if tipo == "hh_distinta_de_time_estimate":
        if "hh" in d:
            est = "no tiene time estimate" if d.get("estimate") is None else f"su time estimate es {hh(d['estimate'])} h"
            return f"{t} tiene {hh(d['hh'])} HH presupuestadas pero {est}"
        return f"{t}: las HH presupuestadas no coinciden con el time estimate"
    if tipo == "avance_sin_horas":
        av = f"{num(d['avance'] * 100, 0)} % de avance" if "avance" in d else "avance"
        return f"{t} tiene {av} pero no tiene horas registradas"
    if tipo == "horas_sin_avance":
        h = f"{num(d['horas'], 2)} h registradas" if "horas" in d else "horas registradas"
        return f"{t} tiene {h} pero 0 % de avance"
    if tipo == "horas_en_tarea_padre":
        cuanto = f"{num(d['horas'])} h registradas" if "horas" in d else "horas registradas"
        return f"{t} tiene {cuanto} en la tarea padre, no en sus subtareas"
    if tipo == "horas_en_administracion":
        if "fraccion" in d and "horas" in d:
            umbral = f", sobre el umbral de {num(d['umbral'] * 100, 0)} %" if "umbral" in d else ""
            return (f"El {num(d['fraccion'] * 100, 0)} % de las horas del proyecto ({num(d['horas'])} h) está en "
                    f"00 Administración{umbral}")
        return "Demasiadas horas del proyecto están en 00 Administración"
    if tipo == "horas_fuera_de_plazo":
        partes = []
        if d.get("n_antes"):
            partes.append(f"{d['n_antes']} entradas ({num(d['h_antes'])} h) antes del inicio del proyecto"
                          + (f" ({fecha(d['inicio'])})" if d.get("inicio") else ""))
        if d.get("n_despues"):
            partes.append(f"{d['n_despues']} entradas ({num(d['h_despues'])} h) después de su término"
                          + (f" ({fecha(d['fin'])})" if d.get("fin") else ""))
        return ("Hay " + " y ".join(partes)) if partes else "Hay horas registradas fuera del plazo del proyecto"
    if tipo == "fase_de_otro_proyecto":
        cod = f" ({d['codigo_fase']})" if d.get("codigo_fase") else ""
        return f"La fase {t if tarea else 'indicada'} lleva el código de otro proyecto{cod}"
    if tipo == "fase_con_hh":
        cuanto = f"{hh(d['hh'])} HH Presupuestadas" if "hh" in d else "HH Presupuestadas"
        return f"La fase {t if tarea else 'indicada'} tiene {cuanto}; deberían estar en un paquete con fechas"
    if tipo == "porcion_con_hh":
        cuanto = f"{hh(d['hh'])} HH Presupuestadas" if "hh" in d else "HH Presupuestadas"
        return f"{t} tiene forma de porción semanal pero lleva {cuanto}"
    if tipo == "sin_presupuesto_contractual":
        return "El proyecto no tiene presupuesto contractual cargado (HH Presupuestadas en 00 Administración)"
    if tipo == "presupuesto_por_agotarse":
        if d.get("superado"):
            return f"Presupuesto contractual superado: {num((d.get('pct') or 0) * 100, 0)} % usado"
        if d.get("semanas") is not None:
            cuando = f" (hacia el {fecha(d['fecha'])})" if d.get("fecha") else ""
            return (f"El presupuesto contractual se agota en {num(d['semanas'])} semanas al ritmo actual{cuando}; "
                    f"usado {num((d.get('pct') or 0) * 100, 0)} %")
        return "El presupuesto contractual está por agotarse"
    if tipo == "cumplimiento_semanal_fuera_de_rango":
        if "n" in d:
            sentido = ("bajo el 50 %" if d.get("bajo") == d["n"] else "sobre el 150 %" if not d.get("bajo")
                       else "fuera del rango 50-150 %")
            return (f"En {d['n']} de las últimas {d.get('ventana', 4)} semanas las horas registradas quedaron {sentido} "
                    "de lo planificado en las porciones")
        return "Las horas registradas se alejan de lo planificado en las porciones varias semanas seguidas"
    if tipo == "paquete_desaparecido":
        if d.get("nombres"):
            return (f"{d.get('n', len(d['nombres']))} paquete(s) de la línea base ya no están en la lista: "
                    + ", ".join(f"«{x}»" for x in d["nombres"][:3]) + (" …" if len(d["nombres"]) > 3 else ""))
        return "Hay paquetes de la línea base que ya no están en la lista"
    if tipo == "lista_combinada":
        cods = f" ({', '.join(d['codigos'])})" if d.get("codigos") else ""
        return f"Lista combinada con fases de más de un proyecto{cods}"
    if tipo == "horas_timetracker_sin_clickup":
        if "horas" in d:
            desde = f" desde el {fecha(d['desde'])}" if d.get("desde") else ""
            return f"El Timetracker tiene {num(d['horas'])} h de este proyecto{desde} que no están registradas en ClickUp"
        return "El Timetracker tiene horas de este proyecto que no están registradas en ClickUp"
    return "Advertencia sin descripción"
