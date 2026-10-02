"""Esquema de las pestañas de la hoja de reportes (fase 2).

Tipos: texto, numero, entero, fecha, fecha_hora. En Sheets las fechas se escriben como numero de serie
(dias desde 1899-12-30) con formato de fecha en la columna, para que Looker Studio las lea como fecha.
"""
from __future__ import annotations

TEXTO, NUMERO, ENTERO, FECHA, FECHA_HORA, BOOLEANO = "texto", "numero", "entero", "fecha", "fecha_hora", "booleano"

# Identificacion del proyecto repetida en las tablas de hechos, para filtrar en Looker Studio sin uniones.
# nombre_corto, cliente y proyecto ("<codigo sin PJ-> · <nombre_corto>") son de presentacion (presentacion.py).
PRESENTACION = [("nombre_corto", TEXTO), ("cliente", TEXTO), ("proyecto", TEXTO)]
# estado_proyecto: "en_curso" (folder PJ Ingenieria) o "finalizado" (folder Proyectos Finalizados; finalizados.py).
# Se actualiza en todas las filas de la lista, tambien las antiguas: es el filtro de Looker para proyectos en curso.
ESTADO = [("estado_proyecto", TEXTO)]
# programa: id del programa de servicio continuo (config/programas.json; programas.py) o vacio. Filtro de Looker para
# sacar esas listas de las paginas de curva S. Se actualiza en todas las filas de la lista, como estado_proyecto.
PROGRAMA = [("programa", TEXTO)]
IDENT = [("codigo", TEXTO)] + PRESENTACION + [("jp_nombre", TEXTO), ("jp_email", TEXTO)] + ESTADO + PROGRAMA

# Tipo de corrida y banderas (fase 3):
# - tipo_corte: "oficial" (semanal, corte domingo, queda en el historial) o "preliminar" (diaria, se sobrescribe).
# - es_ultimo_corte: filas de la corrida mas reciente, de cualquier tipo (vista por defecto en Looker).
# - es_ultimo_oficial: filas del corte oficial mas reciente (PDF de los lunes).
OFICIAL, PRELIMINAR = "oficial", "preliminar"
CORTE = [("tipo_corte", TEXTO), ("es_ultimo_corte", BOOLEANO), ("es_ultimo_oficial", BOOLEANO)]

# hh_gastadas_acum = hh_historicas (saldo del Timetracker) + horas nativas de ClickUp (horas.py).
# hh_estimadas_al_termino: la curva proyectada hasta el ultimo pendiente; hh_estimadas_a_entrega: su valor en la
# fecha de entrega contractual de la linea base (vacio si ya paso o no hay linea base).
METRICAS = [("total_hh", NUMERO), ("hh_prog_acum", NUMERO), ("hh_gastadas_acum", NUMERO), ("hh_historicas", NUMERO),
            ("avance_prog", NUMERO),
            ("avance_real", NUMERO), ("ev", NUMERO), ("spi", NUMERO), ("cpi", NUMERO),
            ("hh_estimadas_al_termino", NUMERO), ("hh_estimadas_termino_plan_semanal", NUMERO),
            ("hh_estimadas_a_entrega", NUMERO),
            ("hh_actuales_clickup", NUMERO)]

TABLAS: dict[str, list[tuple[str, str]]] = {
    "proyectos": [("list_id", TEXTO), ("codigo", TEXTO)] + PRESENTACION + [("nombre", TEXTO), ("jp_nombre", TEXTO),
                  ("jp_email", TEXTO),
                  ("estado_lista", TEXTO), ("fecha_inicio", FECHA), ("fecha_termino_vigente", FECHA),
                  ("estado_linea_base", TEXTO), ("rev_vigente", ENTERO), ("actualizado_en", FECHA_HORA)]
                 + ESTADO + [("corte_cierre", FECHA)] + PROGRAMA,
    "linea_base": [("list_id", TEXTO), ("rev", ENTERO), ("tipo", TEXTO), ("fecha_captura", FECHA_HORA), ("motivo", TEXTO),
                   ("fecha_inicio", FECHA), ("fecha_entrega_contractual", FECHA), ("task_id", TEXTO),
                   ("task_nombre", TEXTO), ("fase", TEXTO), ("hh", NUMERO), ("start", FECHA), ("due", FECHA)],
    "metricas_semanales": [("corte", FECHA)] + CORTE + [("list_id", TEXTO)] + IDENT
                          + [("rev_linea_base", ENTERO), ("tiene_linea_base", BOOLEANO), ("modo_calculo", TEXTO)] + METRICAS
                          + [("desviacion_pts", NUMERO), ("pct_presupuesto_usado", NUMERO), ("titular", TEXTO),
                             ("n_advertencias", ENTERO)]
                          # Presupuesto contractual (presupuesto.py)
                          + [("hh_contrato", NUMERO), ("pct_contrato_usado", NUMERO), ("ritmo_semanal", NUMERO),
                             ("semanas_restantes_al_ritmo", NUMERO), ("fecha_agotamiento_estimada", FECHA)]
                          # Presentacion (presentacion.py): dias habiles para la entrega, deltas frente al corte oficial anterior y semaforo
                          + [("dias_habiles_para_entrega", ENTERO), ("delta_avance_real", NUMERO), ("delta_avance_prog", NUMERO),
                             ("delta_desviacion_pts", NUMERO), ("delta_hh_gastadas", NUMERO), ("semaforo", TEXTO)]
                          # Reproceso (reproceso.py): termino con que se repartieron los pendientes (insumo del reproceso
                          # desde fotos) y, si el corte se recalculo con datos posteriores a su primera escritura, cuando.
                          + [("fecha_termino_usada", FECHA), ("reprocesado_en", FECHA_HORA)],
    "metricas_fase": [("corte", FECHA)] + CORTE + [("list_id", TEXTO)] + IDENT
                     + [("fase", TEXTO), ("hh_linea_base", NUMERO), ("hh_prog_acum", NUMERO),
                        ("hh_gastadas_acum", NUMERO), ("avance_real", NUMERO)],
    "fotos_tareas": [("corte", FECHA), ("list_id", TEXTO), ("task_id", TEXTO), ("parent_id", TEXTO),
                     ("task_nombre", TEXTO), ("fase", TEXTO), ("estado", TEXTO), ("hh", NUMERO), ("start", FECHA),
                     ("due", FECHA), ("avance_real", NUMERO), ("hh_gastadas_acum", NUMERO),
                     ("tipo_tarea", TEXTO), ("origen_avance", TEXTO),
                     ("dias_atraso", ENTERO), ("vence_en_dias", ENTERO)] + ESTADO,
    "serie_diaria": [("corte", FECHA), ("tipo_corte", TEXTO), ("list_id", TEXTO)] + IDENT
                    + [("fecha", FECHA), ("hh_prog_acum", NUMERO),
                                                    ("hh_gastadas_acum", NUMERO), ("hh_proyectadas_acum", NUMERO),
                                                    ("hh_linea_base", NUMERO)],
    "advertencias": [("corte", FECHA)] + CORTE + [("list_id", TEXTO)] + IDENT
                    + [("tipo", TEXTO), ("nivel", TEXTO), ("task_id", TEXTO), ("detalle", TEXTO), ("mensaje", TEXTO),
                       ("como_resolver", TEXTO), ("responsable_accion", TEXTO), ("impacto", TEXTO),
                       ("prioridad", TEXTO)],
    # Cumplimiento del plan semanal (plan_semanal.py): solo por proyecto y semana, nunca por persona.
    "plan_semanal": [("corte", FECHA), ("tipo_corte", TEXTO), ("list_id", TEXTO), ("codigo", TEXTO), ("proyecto", TEXTO),
                     ("jp_nombre", TEXTO), ("jp_email", TEXTO), ("semana", FECHA), ("hh_planificadas", NUMERO),
                     ("hh_registradas", NUMERO), ("cumplimiento", NUMERO), ("es_ultimo_corte", BOOLEANO)] + ESTADO,
    # Cierre de los proyectos finalizados (finalizados.py): una fila por lista, solo en corridas oficiales.
    "cierres": [("list_id", TEXTO)] + IDENT
               + [("tipo_cierre", TEXTO), ("corte_cierre", FECHA), ("ultimo_corte_en_curso", FECHA),
                  ("fecha_inicio", FECHA), ("fecha_ultima_hora", FECHA), ("fecha_entrega_contractual", FECHA),
                  ("entrega_contractual_origen", TEXTO), ("duracion_real_dias_habiles", ENTERO),
                  ("duracion_contractual_dias_habiles", ENTERO), ("diferencia_duracion_dias_habiles", ENTERO),
                  ("hh_gastadas_acum", NUMERO), ("hh_historicas", NUMERO), ("rev_linea_base", ENTERO),
                  ("hh_linea_base", NUMERO), ("hh_sobre_linea_base", NUMERO), ("pct_linea_base_usado", NUMERO),
                  ("hh_contrato", NUMERO), ("hh_sobre_contrato", NUMERO), ("pct_contrato_usado", NUMERO),
                  ("avance_real_final", NUMERO), ("avance_prog_final", NUMERO), ("registrado_en", FECHA_HORA)],
    # Programas de servicio continuo (programas.py): se reemplazan completas en cada corrida (salvo con --solo).
    "programa_horas": [("corte", FECHA), ("tipo_corte", TEXTO), ("programa", TEXTO), ("programa_nombre", TEXTO),
                       ("cliente", TEXTO), ("mes", FECHA), ("contrato", TEXTO), ("contrato_nombre", TEXTO),
                       ("linea", TEXTO), ("linea_nombre", TEXTO), ("responsable_linea", TEXTO), ("list_id", TEXTO),
                       ("origen", TEXTO), ("hh", NUMERO)],
    "programa_contratos": [("corte", FECHA), ("tipo_corte", TEXTO), ("programa", TEXTO), ("programa_nombre", TEXTO),
                           ("cliente", TEXTO), ("contrato", TEXTO), ("contrato_nombre", TEXTO), ("codigo", TEXTO),
                           ("mes", FECHA), ("en_periodo", BOOLEANO), ("es_futuro", BOOLEANO), ("hh_mes", NUMERO),
                           ("hh_acum", NUMERO), ("hh_acum_periodo", NUMERO), ("hh_plan_mes", NUMERO),
                           ("hh_plan_acum", NUMERO), ("hh_periodo", NUMERO), ("meses_periodo", ENTERO),
                           ("periodo_inicio", FECHA), ("periodo_fin", FECHA), ("pct_consumido", NUMERO),
                           # horas "compartido" del programa en el mes: iguales en las filas de todos los contratos
                           ("hh_compartidas_mes", NUMERO), ("hh_compartidas_acum", NUMERO)],
    "programa_entregables": [("corte", FECHA), ("tipo_corte", TEXTO), ("programa", TEXTO), ("programa_nombre", TEXTO),
                             ("cliente", TEXTO), ("contrato", TEXTO), ("contrato_nombre", TEXTO), ("linea", TEXTO),
                             ("linea_nombre", TEXTO), ("responsable_linea", TEXTO), ("list_id", TEXTO),
                             ("task_id", TEXTO), ("tipo_entregable", TEXTO), ("nombre", TEXTO), ("fase", TEXTO),
                             ("estado", TEXTO), ("fecha_entrega", FECHA), ("fecha_cierre", FECHA), ("mes", FECHA),
                             ("situacion", TEXTO), ("dias_atraso", ENTERO), ("url", TEXTO)],
    "ejecuciones": [("ejecutado_en", FECHA_HORA), ("corte", FECHA), ("tipo_corte", TEXTO), ("modo", TEXTO),
                    ("n_proyectos", ENTERO),
                    ("n_lineas_base_nuevas", ENTERO), ("resultado", TEXTO), ("detalle_error", TEXTO),
                    ("n_importadas_excluidas", ENTERO), ("n_duplicadas_excluidas", ENTERO),
                    ("n_duracion_no_positiva_excluidas", ENTERO), ("n_futuras_excluidas", ENTERO),
                    ("n_nativas_previas_excluidas", ENTERO), ("n_lb_incrementales", ENTERO),
                    ("n_proyectos_finalizados", ENTERO), ("n_cierres_nuevos", ENTERO)],
}

# Politica de escritura por tabla
REEMPLAZO_TOTAL = {"proyectos", "serie_diaria"}          # se reemplaza (en el alcance de la corrida)
POR_CORTE = {"metricas_semanales", "metricas_fase", "advertencias", "plan_semanal"}  # oficial: su corte; ambas: todas las preliminares
SOLO_OFICIAL = {"fotos_tareas"}                           # solo corridas oficiales; se reemplaza el corte
SOLO_AGREGAR = {"linea_base", "ejecuciones"}
POR_LISTA = {"cierres"}                                   # una fila por lista (finalizados.fusionar_cierres)
PROGRAMAS = {"programa_horas", "programa_contratos", "programa_entregables"}   # completas; con --solo no se tocan
CON_ULTIMO_CORTE = {t for t, cols in TABLAS.items() if any(c == "es_ultimo_corte" for c, _ in cols)}
CON_TIPO_CORTE = {t for t, cols in TABLAS.items() if any(c == "tipo_corte" for c, _ in cols)}
# Tablas cuyas filas llevan la identificacion del proyecto (se recalcula al escribir, tambien en filas antiguas).
CON_IDENT = {t for t, cols in TABLAS.items() if any(c == "codigo" for c, _ in cols) and t != "proyectos"
             and t not in PROGRAMAS}
CON_ESTADO = {t for t, cols in TABLAS.items() if any(c == "estado_proyecto" for c, _ in cols) and t != "proyectos"}

# Claves naturales: para comprobar que no haya filas duplicadas.
CLAVES = {
    "proyectos": ("list_id",),
    "linea_base": ("list_id", "rev", "task_id"),
    "metricas_semanales": ("corte", "tipo_corte", "list_id"),
    "metricas_fase": ("corte", "tipo_corte", "list_id", "fase"),
    "fotos_tareas": ("corte", "list_id", "task_id"),
    "serie_diaria": ("list_id", "fecha"),
    "advertencias": ("corte", "tipo_corte", "list_id", "tipo", "task_id", "detalle"),
    "ejecuciones": ("ejecutado_en", "corte", "modo"),   # un reproceso escribe varias filas con la misma hora
    "plan_semanal": ("corte", "tipo_corte", "list_id", "semana"),
    "cierres": ("list_id",),
    "programa_horas": ("programa", "mes", "contrato", "linea", "list_id", "origen"),
    "programa_contratos": ("programa", "contrato", "mes"),
    "programa_entregables": ("programa", "list_id", "task_id"),
}


def columnas(tabla: str) -> list[str]:
    return [c for c, _ in TABLAS[tabla]]


def tipos(tabla: str) -> dict[str, str]:
    return dict(TABLAS[tabla])
