# Definiciones del reporte semanal DEP

Vigentes desde el 2026-11-02 (TAREA_reportes_plan_vs_real.md, decisiones de Ale del 2026-11-02). Código en
`dep_reportes/`; entre paréntesis, la función que implementa cada regla.

## 1. Presupuesto y línea base

**HH del proyecto (universo de la curva S).** Suma de «HH Presupuestadas» de las tareas que **no tienen ningún
ancestro con HH**: si el padre, el abuelo o cualquier ancestro ya tiene HH, la tarea no suma
(`adaptador_clickup.con_ancestro_con_hh`, `a_tareas_metrica`). En una lista antigua, «00 Administración» no cuenta
como ancestro con HH: sus HH son el presupuesto contractual y quedan fuera de la curva; en una lista v2,
«00 Administración y cierre» es un cajón más. El detector de calidad sigue viendo las HH tal cual están en ClickUp,
para avisar el doble conteo (`hh_en_padre_y_subtarea`).

**Rev. 0, la misma regla para todas las listas** (`linea_base.evento_congelar`, `linea_base.decidir`). Se congela con
**lo primero que ocurra** entre:

- la primera hora registrada en la lista PJ (fecha trabajada, hasta el corte);
- la primera **porción** creada: una tarea con responsable, alguna fecha y `time_estimate` (fecha de creación hasta el
  corte).

Hasta entonces el programado es **provisional**: sale de las HH y fechas vigentes, no se guarda y el titular empieza
con «Programado provisional (aún sin línea base congelada).». La tarea «1.2 Plan de Trabajo» ya no dispara nada, y el
mensaje «el proyecto está en planificación (la tarea 1.2 sigue abierta)» desaparece.

- **Normal o tardía.** Si el evento cae antes de la semana del corte y la lista ya aparecía en cortes anteriores, la
  Rev. 0 se congela como `tardia`, con la foto de hoy. Mientras esa Rev. 0 esté vigente queda la advertencia
  `linea_base_tardia`.
- **El titular lo dice.** En el corte en que se congela, el titular empieza con
  «Línea base Rev. 0 congelada en este corte (… evento …).» (`presentacion.nota_congelada`).
- **Listas que ya tienen Rev. 0:** no se tocan (las filas de `linea_base` solo se agregan).
- **Línea base retenida.** Las listas en `config/reportes.json` → `linea_base_retenida` (`list_id` → motivo) no se
  congelan aunque ocurra el evento. Quedan provisionales, con el titular «Programado provisional (línea base retenida:
  motivo).» y la advertencia `linea_base_retenida`. Para liberar una lista, se borra su entrada y la Rev. 0 se congela
  en la corrida siguiente. Hoy está retenida la PJ-2026.0225 (presupuesto contractual por confirmar contra la propuesta).
- **Finalizados sin línea base:** siguen sin línea base (no pasan a provisional).

## 2. Fechas

**Fecha contractual = fechas de la lista.** Por convención DEP, el inicio y el término del contrato se cargan como
inicio y vencimiento de la lista PJ. `fecha_entrega_contractual` es la que quedó guardada en la línea base vigente (el
vencimiento de la lista al congelar) o, si no hay línea base, el vencimiento actual de la lista (`run.filas_de`). La
columna nueva `entrega_texto` lleva el vencimiento de la lista como dd-mm-aaaa, o «lista sin fecha de término». Sin
fecha, `dias_habiles_para_entrega` queda vacío. Los hitos (EDP, entregas parciales) no cambian esta fecha.

**Inicio del proyecto** (para las fechas heredadas): la primera hora registrada en la lista PJ; si no hay horas, el
inicio de la lista.

**Fechas heredadas de la plantilla.** Una tarea (que no esté en No Aplica) cuyo vencimiento es anterior al inicio del
proyecto no cuenta como atraso (`fotos_tareas.dias_atraso` y `vence_en_dias` quedan vacíos) y entra en una sola
advertencia de nivel proyecto, `fechas_anteriores_al_inicio`: «N tarea(s) con fechas anteriores al inicio del proyecto
(dd-mm-aaaa) (heredadas de la plantilla); limpiar». Las tareas no se listan en la tabla de atrasos.

`pj_create` crea la lista desde la plantilla con `options.old_due_date = false` y `options.old_start_date = false`,
para que las tareas no traigan las fechas fijas de la plantilla. `pj_v2` ya creaba las tareas solo con las fechas que
calcula.

## 3. Plan semanal y registrado semanal

**Planificado (semana)** (`plan_vs_real.plan_por_persona`, `plan_semanal_total`). Entran las tareas con responsable,
alguna fecha y `time_estimate`, de cualquier tipo (no solo «porción»). Quedan fuera los padres cuyos descendientes ya
tienen `time_estimate` y las tareas en No Aplica. Cada tarea aporta:

    time_estimate × días hábiles de la tarea dentro de la semana / días hábiles totales de la tarea

- Días hábiles: lunes a viernes, sin feriados de Chile ni los días de `config/dias_no_habiles.csv`.
- Sin `start_date`, sin días hábiles en el rango o con vencimiento anterior al inicio: la tarea cuenta entera en la
  semana del vencimiento (o del inicio, si no tiene vencimiento).
- Con varios responsables, el `time_estimate` se reparte en partes iguales.
- Las tareas sin responsable no suman al plan del proyecto; en `plan_vs_real` aparecen como «(sin responsable)».

**Registrado (semana).** Entradas de tiempo de la lista PJ por **fecha trabajada** (el inicio de la entrada), no por
fecha de registro. Aparte, las entradas registradas en la tarea de la SS del proyecto en SS_REGISTRO (se identifica
por el código al inicio del nombre: «2026.0225 | …»). Esas van marcadas con origen `SS`: se muestran
(`plan_semanal.hh_registradas_ss`, `plan_vs_real.horas_registradas_ss`) y disparan la advertencia `horas_en_tarea_ss`,
pero **no entran a la curva S** ni al cumplimiento.

**Cumplimiento** = registrado (lista PJ) / planificado.

La **proyección por plan semanal** (`config proyeccion = plan_semanal`, hoy apagada) sigue usando las porciones de
`estructura.plan_porciones`; esta definición no la cambia.

### Qué contaba el cálculo anterior

Antes del 2026-11-02, `plan_semanal.hh_planificadas` sumaba solo las tareas de clase **porción**
(`estructura.clasificar`: hoja de nivel ≥ 1, **sin HH Presupuestadas**, sin numeración de plantilla y de ≤ 7 días), con
o sin responsable, y ponía el `time_estimate` **entero en la semana de su inicio**, sin prorrateo. En la Correa 2741
eso dejaba afuera las tareas semanales que llevan HH (se clasifican como paquete) y cargaba una semana con trabajo que
cae en la siguiente. El detalle con las cifras de la Correa está en `reportes/plan_vs_real/comparacion.md`.

## 4. Plan vs real por persona (hoja aparte)

Pestaña `plan_vs_real` en una **hoja aparte de «DEP - Reportes»**, de acceso restringido a los JP
(`SHEETS_PLAN_VS_REAL_ID`). Si no hay id definido, solo se escribe en el CSV del dry-run. Hay una fila por
`fecha_corte × semana_inicio × proyecto × persona` con algún valor en la ventana (4 semanas hacia atrás, incluida la del
corte, y 6 hacia adelante), más una fila «(proyecto)» por semana con `horas_necesarias_semana`.

| columna | contenido |
|---|---|
| fecha_corte | lunes del corte (el lunes siguiente al domingo de corte) |
| corte, tipo_corte | domingo de corte y oficial/preliminar (para filtrar y fusionar) |
| semana_inicio | lunes de la semana |
| list_id, proyecto | id de la lista y código sin «PJ-» (2026.0225) |
| proyecto_nombre, jp | nombre corto y JP de la lista |
| persona | responsable; «(sin responsable)»; «(proyecto)» solo para horas necesarias |
| horas_planificadas | regla de la sección 3 |
| horas_registradas | lista PJ, por fecha trabajada (vacío en semanas futuras) |
| horas_registradas_ss | tarea de la SS (vacío en semanas futuras) |
| cumplimiento | registradas / planificadas (vacío si planificadas = 0) |
| estado | `ok` ≥ 0,8 · `parcial` 0,5–0,8 · `sin_registro` < 0,5 con plan > 0 · `sin_plan` plan = 0 y registradas > 0 · `futuro` semana > corte (vacío si solo hay horas SS) |
| horas_necesarias_semana | solo en «(proyecto)»: HH de las tareas del universo (sección 1) con fecha de término, menos lo gastado en ellas y sus descendientes, repartido en partes iguales en las semanas posteriores al corte hasta la del término; si el término ya pasó, todo en la primera semana siguiente; tareas cerradas o en No Aplica, 0 |
| es_ultimo_corte | filas del corte más reciente |

Se guarda cada corte oficial (no se sobrescribe el historial); un preliminar reemplaza los preliminares anteriores.
