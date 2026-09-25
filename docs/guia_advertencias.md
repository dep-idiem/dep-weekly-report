# Guía de advertencias del reporte semanal DEP

Cada advertencia del reporte indica qué pasa, cómo resolverlo en ClickUp, quién lo resuelve y qué impacto tiene mientras no se corrija. Este archivo se genera con `python scripts/guia_advertencias.py` desde `dep_reportes/resolucion.py`; no se edita a mano.

**Impacto**

- **Impide la curva S**: el proyecto no puede tener línea base o curva S.
- **Distorsiona las cifras**: hay curva S, pero algún número (avance, HH, proyección) sale mal.
- **Informativa**: no cambia las cifras; conviene revisarla.

**Responsable**: JP (jefe de proyecto), Administración DEP o Informativa (no requiere acción).

En el reporte, `<tarea>` y `<proyecto>` se reemplazan por el nombre real de la tarea o del proyecto.

| Tipo | Qué significa | Cómo resolverlo | Quién | Impacto |
|---|---|---|---|---|
| `hh_en_padre_y_subtarea` | La tarea padre y sus subtareas tienen HH Presupuestadas: las HH se cuentan dos veces. | En ClickUp, deja las HH Presupuestadas solo en las subtareas de «<tarea>» y bórralas del padre; si el padre tenía el total, repártelo entre ellas. *(Sin línea base: Luego avisa a Administración DEP.)* | JP | Impide la curva S (sin línea base) / Distorsiona las cifras (con línea base) |
| `hh_sin_start_o_due` | Una tarea con HH Presupuestadas no tiene fecha de inicio o de término: sus HH no se pueden repartir en el tiempo. | En ClickUp, asigna fecha de inicio y de término a «<tarea>». | JP | Impide la curva S (sin línea base) / Distorsiona las cifras (con línea base) |
| `due_anterior_a_start` | La fecha de término de una tarea es anterior a su fecha de inicio. | En ClickUp, corrige las fechas de «<tarea>»: el término debe ser posterior al inicio. | JP | Distorsiona las cifras |
| `avance_sin_horas` | Una tarea tiene Avance Real mayor que cero pero no tiene horas registradas. | En ClickUp, registra las horas trabajadas en «<tarea>» (en la subtarea, nunca en el padre) o corrige su Avance Real si aún no se ha trabajado. | JP | Distorsiona las cifras |
| `horas_sin_avance` | Una tarea tiene horas registradas pero su Avance Real sigue en 0 %. | En ClickUp, actualiza el Avance Real de «<tarea>». | JP | Distorsiona las cifras |
| `en_planificacion` | La tarea 1.2 Plan de Trabajo sigue abierta: el proyecto está en planificación y aún no tiene línea base. | En la lista «<proyecto>», cuando todas las tareas tengan HH y fechas, marca «1.2 Plan de Trabajo» como completada; la línea base se congela en la siguiente actualización. | JP | Impide la curva S |
| `tarea_1_2_no_aplica` | La tarea 1.2 Plan de Trabajo está en No Aplica: la línea base no se congela automáticamente. | En la lista «<proyecto>», completa las HH y fechas del plan y avisa a Administración DEP para congelar la línea base. | JP | Impide la curva S |
| `linea_base_sin_hh` | Correspondía congelar la línea base, pero ninguna tarea tiene HH Presupuestadas. | En la lista «<proyecto>», carga las HH Presupuestadas en las tareas finales (subtareas) del proyecto. | JP | Impide la curva S |
| `linea_base_tardia` | La línea base se congeló después de cerrada la 1.2 (o sin 1.2), con el plan de ese día. | La línea base se tomó con el plan vigente a la fecha de captura, no con el plan original; si no lo representa, pide una revisión a Administración DEP. | Informativa | Informativa |
| `no_aplica_con_hh` | Una tarea en No Aplica tiene HH Presupuestadas. | En ClickUp, borra las HH Presupuestadas de «<tarea>» o, si sí aplica, cambia su estado. | JP | Distorsiona las cifras |
| `proyecto_con_termino_vencido` | La fecha de vencimiento de la lista ya pasó y el proyecto tiene trabajo pendiente. | Si hay nueva fecha con el cliente, actualiza el vencimiento de la lista «<proyecto>» y pide a Administración DEP una revisión de línea base; si ya se entregó, cierra lo pendiente. | JP | Distorsiona las cifras |
| `hh_cambiaron_vs_linea_base` | El total de HH Presupuestadas en ClickUp ya no coincide con el de la línea base. | Si el alcance cambió de verdad, pide a Administración DEP una revisión de línea base; si fue un error, vuelve a las HH anteriores en la lista «<proyecto>». | JP | Informativa |
| `sin_jp` | La lista no tiene responsable (JP) en ClickUp, o el responsable no es miembro del espacio. | En ClickUp, asigna el responsable (JP) de la lista «<proyecto>». | Administración DEP | Impide la curva S |
| `codigo_duplicado_en_clickup` | Dos listas de ClickUp usan el mismo código de proyecto; en los reportes se distinguen con -A y -B. | En ClickUp, corrige el código <código> en el nombre de una de las dos listas que lo usan. | Administración DEP | Informativa |
| `nombre_lista_sin_formato` | El nombre de la lista no sigue el formato «código \| nombre \| cliente»: el reporte no puede mostrar el cliente. | En ClickUp, renombra la lista como «PJ-XXXX \| <nombre del proyecto> \| cliente». | JP | Informativa |
| `hh_en_tarea_no_hoja` | Una tarea padre tiene HH Presupuestadas y sus subtareas no: no distorsiona el cálculo, pero incumple la convención de presupuestar solo en subtareas. | En ClickUp, reparte las HH Presupuestadas de «<tarea>» entre sus subtareas y borra el valor del padre. | JP | Informativa |
| `horas_en_tarea_padre` | Hay horas registradas directamente en una tarea que tiene subtareas: no se sabe en qué subtarea se trabajó. | Registra las horas en las subtareas de «<tarea>», no en la tarea padre. | JP | Distorsiona las cifras |
| `horas_en_administracion` | Las horas registradas en la fase 00 Administración superan el umbral del proyecto (config/reportes.json). | En la lista «<proyecto>», registra en las subtareas del trabajo realizado las horas que hoy van a «00 Administración»; deja ahí solo la gestión del proyecto. | JP | Distorsiona las cifras |
| `horas_fuera_de_plazo` | Hay entradas de tiempo antes del inicio o después del término del proyecto. | En la lista «<proyecto>», corrige la fecha o la tarea de las entradas fuera del plazo, o actualiza el inicio y el término de la lista. | JP | Distorsiona las cifras |
| `fase_de_otro_proyecto` | Una fase de la lista lleva en su nombre el código de otro proyecto: sus horas cuentan en el proyecto equivocado. | Mueve la fase «<tarea>» a la lista de su proyecto o corrige el código en su nombre. | Administración DEP | Distorsiona las cifras |
| `lista_combinada` | La lista tiene fases de más de un proyecto (códigos distintos en los nombres de sus fases): las horas de ambos se reportan juntas. | Separa en listas distintas las fases de cada proyecto en «<proyecto>», o confirma que se reportan juntos. | Administración DEP | Distorsiona las cifras |
| `horas_timetracker_sin_clickup` | El Timetracker antiguo tiene horas del proyecto posteriores al inicio del registro en ClickUp que no están en ClickUp: posibles horas sin registrar. | Revisa con el JP las horas del Timetracker de la lista «<proyecto>»: regístralas en ClickUp o confirma que no corresponden. | Administración DEP | Distorsiona las cifras |
| `sin_tarea_1_2` | No hay tarea 1.2 Plan de Trabajo en la fase 01. | *Pendiente de definir* | — | — |
| `varias_tareas_1_2` | Hay más de una tarea 1.2 en la fase 01. | *Pendiente de definir* | — | — |
| `sin_termino_vigente` | La lista no tiene fecha de vencimiento. | *Pendiente de definir* | — | — |
| `tarea_de_linea_base_ahora_no_aplica` | Una tarea de la línea base está hoy en No Aplica. | *Pendiente de definir* | — | — |
| `hh_distinta_de_time_estimate` | Las HH Presupuestadas de una tarea no coinciden con su time estimate (o no tiene). | *No va a la hoja: solo en calidad_datos.md* | — | — |
