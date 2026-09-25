"""Esquema de las pestañas de la hoja de reportes (fase 2).

Tipos: texto, numero, entero, fecha, fecha_hora. En Sheets las fechas se escriben como numero de serie
(dias desde 1899-12-30) con formato de fecha en la columna, para que Looker Studio las lea como fecha.
"""
from __future__ import annotations

TEXTO, NUMERO, ENTERO, FECHA, FECHA_HORA, BOOLEANO = "texto", "numero", "entero", "fecha", "fecha_hora", "booleano"

# Identificacion del proyecto repetida en las tablas de hechos, para filtrar en Looker Studio sin uniones.
# nombre_corto, cliente y proyecto ("<codigo sin PJ-> · <nombre_corto>") son de presentacion (presentacion.py).
PRESENTACION = [("nombre_corto", TEXTO), ("cliente", TEXTO), ("proyecto", TEXTO)]
IDENT = [("codigo", TEXTO)] + PRESENTACION + [("jp_nombre", TEXTO), ("jp_email", TEXTO)]

# Tipo de corrida y banderas (fase 3):
# - tipo_corte: "oficial" (semanal, corte domingo, queda en el historial) o "preliminar" (diaria, se sobrescribe).
# - es_ultimo_corte: filas de la corrida mas reciente, de cualquier tipo (vista por defecto en Looker).
# - es_ultimo_oficial: filas del corte oficial mas reciente (PDF de los lunes).
OFICIAL, PRELIMINAR = "oficial", "preliminar"
CORTE = [("tipo_corte", TEXTO), ("es_ultimo_corte", BOOLEANO), ("es_ultimo_oficial", BOOLEANO)]

METRICAS = [("total_hh", NUMERO), ("hh_prog_acum", NUMERO), ("hh_gastadas_acum", NUMERO), ("avance_prog", NUMERO),
            ("avance_real", NUMERO), ("ev", NUMERO), ("spi", NUMERO), ("cpi", NUMERO),
            ("hh_estimadas_al_termino", NUMERO), ("hh_actuales_clickup", NUMERO)]

TABLAS: dict[str, list[tuple[str, str]]] = {
    "proyectos": [("list_id", TEXTO), ("codigo", TEXTO)] + PRESENTACION + [("nombre", TEXTO), ("jp_nombre", TEXTO),
                  ("jp_email", TEXTO),
                  ("estado_lista", TEXTO), ("fecha_inicio", FECHA), ("fecha_termino_vigente", FECHA),
                  ("estado_linea_base", TEXTO), ("rev_vigente", ENTERO), ("actualizado_en", FECHA_HORA)],
    "linea_base": [("list_id", TEXTO), ("rev", ENTERO), ("tipo", TEXTO), ("fecha_captura", FECHA_HORA), ("motivo", TEXTO),
                   ("fecha_inicio", FECHA), ("fecha_entrega_contractual", FECHA), ("task_id", TEXTO),
                   ("task_nombre", TEXTO), ("fase", TEXTO), ("hh", NUMERO), ("start", FECHA), ("due", FECHA)],
    "metricas_semanales": [("corte", FECHA)] + CORTE + [("list_id", TEXTO)] + IDENT
                          + [("rev_linea_base", ENTERO), ("tiene_linea_base", BOOLEANO), ("modo_calculo", TEXTO)] + METRICAS
                          + [("desviacion_pts", NUMERO), ("pct_presupuesto_usado", NUMERO), ("titular", TEXTO),
                             ("n_advertencias", ENTERO)],
    "metricas_fase": [("corte", FECHA)] + CORTE + [("list_id", TEXTO)] + IDENT
                     + [("fase", TEXTO), ("hh_linea_base", NUMERO), ("hh_prog_acum", NUMERO),
                        ("hh_gastadas_acum", NUMERO), ("avance_real", NUMERO)],
    "fotos_tareas": [("corte", FECHA), ("list_id", TEXTO), ("task_id", TEXTO), ("parent_id", TEXTO),
                     ("task_nombre", TEXTO), ("fase", TEXTO), ("estado", TEXTO), ("hh", NUMERO), ("start", FECHA),
                     ("due", FECHA), ("avance_real", NUMERO), ("hh_gastadas_acum", NUMERO)],
    "serie_diaria": [("corte", FECHA), ("tipo_corte", TEXTO), ("list_id", TEXTO)] + IDENT
                    + [("fecha", FECHA), ("hh_prog_acum", NUMERO),
                                                    ("hh_gastadas_acum", NUMERO), ("hh_proyectadas_acum", NUMERO),
                                                    ("hh_linea_base", NUMERO)],
    "advertencias": [("corte", FECHA)] + CORTE + [("list_id", TEXTO)] + IDENT
                    + [("tipo", TEXTO), ("nivel", TEXTO), ("task_id", TEXTO), ("detalle", TEXTO), ("mensaje", TEXTO),
                       ("como_resolver", TEXTO), ("responsable_accion", TEXTO), ("impacto", TEXTO)],
    "ejecuciones": [("ejecutado_en", FECHA_HORA), ("corte", FECHA), ("tipo_corte", TEXTO), ("modo", TEXTO),
                    ("n_proyectos", ENTERO),
                    ("n_lineas_base_nuevas", ENTERO), ("resultado", TEXTO), ("detalle_error", TEXTO)],
}

# Politica de escritura por tabla
REEMPLAZO_TOTAL = {"proyectos", "serie_diaria"}          # se reemplaza (en el alcance de la corrida)
POR_CORTE = {"metricas_semanales", "metricas_fase", "advertencias"}  # oficial: su corte; ambas: todas las preliminares
SOLO_OFICIAL = {"fotos_tareas"}                           # solo corridas oficiales; se reemplaza el corte
SOLO_AGREGAR = {"linea_base", "ejecuciones"}
CON_ULTIMO_CORTE = {t for t, cols in TABLAS.items() if any(c == "es_ultimo_corte" for c, _ in cols)}
CON_TIPO_CORTE = {t for t, cols in TABLAS.items() if any(c == "tipo_corte" for c, _ in cols)}
# Tablas cuyas filas llevan la identificacion del proyecto (se recalcula al escribir, tambien en filas antiguas).
CON_IDENT = {t for t, cols in TABLAS.items() if any(c == "codigo" for c, _ in cols) and t != "proyectos"}

# Claves naturales: para comprobar que no haya filas duplicadas.
CLAVES = {
    "proyectos": ("list_id",),
    "linea_base": ("list_id", "rev", "task_id"),
    "metricas_semanales": ("corte", "tipo_corte", "list_id"),
    "metricas_fase": ("corte", "tipo_corte", "list_id", "fase"),
    "fotos_tareas": ("corte", "list_id", "task_id"),
    "serie_diaria": ("list_id", "fecha"),
    "advertencias": ("corte", "tipo_corte", "list_id", "tipo", "task_id", "detalle"),
    "ejecuciones": ("ejecutado_en",),
}


def columnas(tabla: str) -> list[str]:
    return [c for c, _ in TABLAS[tabla]]


def tipos(tabla: str) -> dict[str, str]:
    return dict(TABLAS[tabla])
