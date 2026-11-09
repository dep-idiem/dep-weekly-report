# Definiciones del reporte semanal DEP

Avance físico vigente desde el 2026-11-04 (TAREA_avance_fisico.md, sección 1c). El resto, vigente desde el
2026-11-03 (TAREA_curva_programada_unica.md: un solo modo de curva S para todas las listas PJ,
antiguas y v2) y, en lo que esa tarea no cambia, desde el 2026-11-02 (TAREA_reportes_plan_vs_real.md). Código en
`dep_reportes/`; entre paréntesis, la función que implementa cada regla. Lo único que se considera confiable en todas
las listas son las **fechas de la lista** y las **horas registradas**; solo se leen datos de ClickUp.

## 1. Presupuesto, programada y línea base

**Contractual.** Inicio y término del contrato = `start_date` y `due_date` de la lista PJ. La extensión es el
`due_date` actual de la lista menos el guardado en la Rev. 0 (`fecha_entrega_contractual`, `es_extension`,
`dias_extension`; sección 2).

**Tareas que aportan presupuesto (universo de la curva S).** Las tareas con «HH Presupuestadas» > 0 que **no tienen
ningún ancestro con HH**: si el padre, el abuelo o cualquier ancestro ya tiene HH, la tarea no suma
(`adaptador_clickup.con_ancestro_con_hh`, `a_tareas_metrica`). Presupuesto = suma de sus HH. **Nada más cuenta**: ni
porciones ni `time_estimate`. En una lista antigua, «00 Administración» no cuenta como ancestro con HH: sus HH son el
presupuesto contractual y quedan fuera de la curva; en una lista v2, «00 Administración y cierre» es un cajón más. El
detector de calidad sigue viendo las HH tal cual están en ClickUp, para avisar el doble conteo
(`hh_en_padre_y_subtarea`).

**Programada** (`programada.programar`). Cada tarea que aporta presupuesto reparte sus HH en partes iguales por día
hábil entre su `start_date` y su `due_date`, y se acumula. Respaldo: si la tarea no tiene inicio o término, las
fechas están al revés, el rango no tiene días hábiles o alguna fecha cae fuera de [inicio, término] de la lista, sus
HH se reparten entre el inicio y el término de la lista, y queda la advertencia `fechas_fuera_de_lista` (nivel tarea,
para el JP, con el motivo). Si la lista no tiene inicio o término, el respaldo usa el inicio más temprano o el término
más tardío de las tareas con fechas propias.

**Inicio anterior al de la lista (hasta 30 días).** Una tarea cuyo inicio es anterior al inicio de la lista por **30
días corridos o menos** no va al respaldo: sus HH se reparten entre sus propias fechas y la ventana de la programada
(la curva) parte en ese inicio (`programada.MAX_DIAS_ANTICIPO`, `Programada.inicio_ventana`). Queda la advertencia
informativa `inicio_anterior_contractual` (nivel tarea, prioridad baja) con los días. Con más de 30 días sigue el
tratamiento de arriba (respaldo y `fechas_fuera_de_lista`). El **término** de la lista sigue siendo límite estricto: una
tarea que termina después va al respaldo aunque empiece dentro del margen. Columna `programada_modo` (en `proyectos` y `metricas_semanales`):

| programada_modo | significado |
|---|---|
| `tareas` | todas las tareas se reparten con sus propias fechas |
| `mixta` | algunas cayeron al respaldo |
| `lineal` | todas cayeron al respaldo: la programada es una recta entre inicio y término de la lista |

Las fechas de las tareas **sin** HH no se leen para la programada (tampoco para el inicio del proyecto cuando la lista
no tiene inicio: `linea_base.inicio_proyecto` usa las tareas con HH).

**Real.** Horas registradas acumuladas por fecha trabajada, como antes. Las horas de la tarea de la SS van en columna
aparte (sección 3), fuera de la curva.

**Rev. 0, la misma regla para todas las listas** (`linea_base.evento_congelar`, `linea_base.decidir`). Se congela con
la **primera hora registrada** en la lista PJ (fecha trabajada, hasta el corte). Ya no la disparan la tarea «1.2 Plan
de Trabajo» ni la primera porción. Al congelar se guardan, por tarea que aporta presupuesto, sus HH y sus fechas de
ClickUp, y el inicio y el término de la lista (`fecha_inicio`, `fecha_entrega_contractual` de `linea_base`). La
programada de una línea base se reconstruye siempre con esos datos y la misma regla de respaldo, con el plazo
guardado (`linea_base.programada`, también en el reproceso): cambios posteriores en las tareas o en las fechas de la
lista se ven como desvío y no reescriben el plan. Las tareas creadas después de la Rev. 0 **no** se agregan a la línea
base (ya no hay filas `incremental` nuevas): se ven en `hh_actuales_clickup` frente a `total_hh`.

Hasta la primera hora el programado es **provisional**: sale de las HH y fechas vigentes y del plazo actual de la
lista, no se guarda y el titular empieza con «Programado provisional (aún sin línea base congelada).».

- **Normal o tardía.** Si la primera hora cae antes de la semana del corte y la lista ya aparecía en cortes
  anteriores, la Rev. 0 se congela como `tardia`, con la foto de hoy. Mientras esa Rev. 0 esté vigente queda la
  advertencia `linea_base_tardia`.
- **El titular lo dice.** En el corte en que se congela, el titular empieza con
  «Línea base Rev. 0 congelada en este corte (… primera hora registrada el dd-mm-aaaa).» (`presentacion.nota_congelada`).
- **Listas que ya tienen Rev. 0:** no se tocan (las filas de `linea_base` solo se agregan).
- **Finalizados sin línea base:** siguen sin línea base (no pasan a provisional).

**Estado de la curva** (`programada.estado`; columna `estado_curva` en `proyectos` y `metricas_semanales`):

| estado_curva | cuándo | qué pasa |
|---|---|---|
| `ok` | hay presupuesto (o Rev. 0) | programada, provisional o congelada |
| `sin_presupuesto` | presupuesto 0 y sin Rev. 0 | no se dibuja programada ni se congela; advertencia `proyecto_sin_presupuesto` para el JP (prioridad alta, va al aviso semanal) |
| `presupuesto_incoherente` | sin Rev. 0, horas registradas (con el saldo histórico) > presupuesto | no se congela ni se dibuja programada; advertencia `presupuesto_incoherente` para el JP. Caso tipo: CMP-SHM Modelos, 22 HH contra 409 h |
| `retenida` | lista en `config/reportes.json` → `linea_base_retenida`, sin Rev. 0 | se calcula todo (programado provisional) pero no se congela; advertencia `linea_base_retenida` |
| `recurrente` | lista de un programa de servicio continuo (`config/programas.json`) | fuera de la curva S (sección 1b) |

Retenidas hoy: PJ-2026.0225 Correa 2741 (presupuesto contractual por confirmar contra la propuesta), PJ-TEST
(1400570000001689) y PJ-EJEMPLO (1400570000002107). Para liberar una lista, se borra su entrada y la Rev. 0 se congela
en la corrida siguiente.

**Ritmo, desfase y horas necesarias** (en `proyectos`, foto del último corte; dos de ellas también en `plan_semanal`):

- `ritmo_real` (`presupuesto.ritmo_real`): promedio semanal de las horas registradas en la lista PJ en las **2 últimas
  semanas cerradas** (lunes a domingo, con el domingo en el corte o antes: en un corte de domingo cuenta su propia
  semana; en una preliminar de martes, las dos anteriores). Solo horas nativas que cuenta el reporte (sin la tarea de la
  SS ni el saldo del Timetracker).
- `semanas_desfase` (`presentacion.semanas_desfase`): HH pendientes / `ritmo_real` − semanas hasta el término
  contractual (`fecha_entrega_contractual`; días hábiles para la entrega / 5, negativas si ya venció). HH pendientes =
  Σ (1 − avance físico) × HH de las tareas del presupuesto (las mismas que reparte la proyección). Positivo: a este ritmo
  el proyecto termina esas semanas después del plazo; negativo: le sobran. Vacío si no hay ritmo (0 h en las dos
  semanas), si no hay término contractual o si el proyecto no tiene curva (`sin_presupuesto`, `recurrente`).
- `hh_pendientes`: las HH pendientes de arriba (Σ (1 − avance físico) × HH del presupuesto). Vacío si el proyecto no
  tiene curva.
- `horas_necesarias_semana` (`presentacion.horas_necesarias_semana`): HH pendientes / semanas hasta el término
  contractual (días hábiles para la entrega / 5). Es el ritmo que haría falta para terminar en plazo; se compara con
  `ritmo_real`. Vacío si el plazo ya venció o vence el día del corte (no quedan semanas), si no hay término contractual
  o si el proyecto no tiene curva.
- `fecha_termino_estimada` (`presentacion.fecha_termino_estimada`): corte + HH pendientes / `ritmo_real` semanas, en
  días corridos. Vacío si no hay ritmo o el proyecto no tiene curva.

En `plan_semanal`, por semana:

- `horas_necesarias_semana` (`plan_vs_real.necesarias_por_semana`): para cada tarea del presupuesto abierta y con fecha
  de término, sus HH menos lo gastado en ella y sus descendientes, en partes iguales en las semanas posteriores al
  corte hasta la de su término (si ya venció, todo en la primera semana siguiente). Es la misma serie de la fila
  «(proyecto)» de la hoja de los JP. No coincide con `proyectos.horas_necesarias_semana`: esa reparte lo pendiente
  (por avance) parejo hasta el término contractual; esta, lo no gastado de cada tarea hasta su propio término.
- `ritmo_real`: el de `proyectos`, repetido en cada semana del proyecto (para la línea de referencia en Looker).

## 1b. Contratos recurrentes (programas de servicio continuo)

Las listas de un programa en `config/programas.json` (`programas.py`) quedan **fuera de la curva S**:

- no se congela línea base ni se dibuja programada (`estado_curva = recurrente`; una Rev. 0 que ya estaba en la hoja
  se conserva, pero no se usa);
- la columna `programa` (en todas las tablas de hechos) lleva el id del programa: es el filtro de Looker para sacar
  esas listas de las páginas de curva S (`programa` es nulo; `docs/looker_programas.md`);
- se reportan por contrato y por línea en `programa_horas`, `programa_contratos` y `programa_entregables`
  (horas por mes, consumo acumulado frente al ritmo planificado cuando la config tiene presupuesto, entregables);
- no se emiten las advertencias de `advertencias_omitidas` (término vencido, sin término, horas fuera de plazo,
  1.2, código duplicado, lista combinada, fase de otro proyecto, sin presupuesto contractual).

Programas: **CMP-SHM** (General, Informes, Modelos, Apilador y Diagnóstico Apilador), **AITO-HPC** (PJ-2025.0321
Extensión 2026 AITO HPC y Cartas AITO HPC) y **AITO-SOTERO** (PJ-2024.0008 AITO Hospital Sótero del Río y Cartas). Los
dos AITO tienen un contrato cada uno, líneas «Servicio» y «Cartas», sin entregables configurados y sin presupuesto
todavía (`_pendiente` en la config).

## 1c. Avance físico (desde el 2026-11-04)

El avance ya **no se lee del campo manual «Avance Real»** (`manual_progress`) ni de «Avance Acumulado» (fórmula) ni de
«% Avance»: se calcula desde el estado de las tareas (`avance.py`). Por cada tarea que aporta presupuesto (sección 1),
en este orden:

| avance_fisico_modo | cuándo | avance de la tarea |
|---|---|---|
| `cerrada` | la tarea está en un estado de tipo done/closed | 100 % |
| `porciones` | abierta y con porciones: descendientes de **cualquier nivel** con `time_estimate` | Σ `time_estimate` de las porciones cerradas ÷ Σ `time_estimate` de todas |
| `checklist` | abierta, sin porciones y con checklists propios | ítems marcados ÷ ítems totales |
| `consumo` | abierta, sin porciones ni checklists | horas registradas en ella y sus descendientes ÷ HH, con tope 90 % (respaldo) |

- Las porciones en **No Aplica** o **cancelado/cancelada** (y lo que cuelga de ellas) no entran al denominador. Si
  todas lo están, la tarea pasa al checklist o al consumo.
- Si una porción tiene a su vez descendientes con `time_estimate`, cuentan esos y no ella (no se suma dos veces).
- **Proyecto** = Σ (avance de la tarea × HH) ÷ Σ HH, sobre las mismas tareas que la curva S (sin las tareas en No
  Aplica). Lo mismo por fase en `metricas_fase`. `avance_fisico_modo` del proyecto (o de la fase) = el modo de sus
  tareas **abiertas** si es uno solo; `mixto` si hay varios; `cerrada` si todas están cerradas.
- El avance físico es el que usan EV, SPI, CPI, las HH pendientes (proyección, desfase, horas necesarias, término
  estimado), el semáforo, los deltas y la curva ganada (`hh_ganadas_acum`). El titular dice «Avance físico …» (las filas
  anteriores al cambio siguen diciendo «Avance real …»).
- `avance_manual`: el campo «Avance Real» ponderado por HH, **solo informativo** (por si algún JP lo usa); vacío si
  ninguna tarea del proyecto lo tiene en más de 0. No entra en ningún cálculo.
- `avance_real` (en `metricas_semanales`, `metricas_fase`, `fotos_tareas`, `cierres`): **obsoleto**. Desde el
  2026-11-04 lleva el mismo valor que `avance_fisico`; se mantiene para no romper las páginas de Looker que lo leen y
  se eliminará cuando se cambien a `avance_fisico`. En los cortes anteriores conserva el valor de la regla antigua
  (manual si lo había; si no, porciones por cantidad o consumo en cajones v2).
- Ya no se emiten `avance_sin_horas` ni `horas_sin_avance` (comparaban el campo manual con las horas).

**Consumo, aparte.** `consumo_pct` = `hh_gastadas_acum` ÷ `total_hh` (en `proyectos` y `metricas_semanales`). Es un
indicador de presupuesto gastado, no de avance, y no se mezcla con él. La curva S «real» sigue siendo horas gastadas.

**Porciones vencidas sin cerrar** (el avance físico subestima si las porciones terminadas quedan abiertas; no se
asume que estén terminadas, se muestra):

- Advertencia `porcion_vencida_abierta` (nivel tarea, para el JP, prioridad normal, impacto «Distorsiona las
  cifras»): porción de una tarea en modo `porciones`, con término anterior al corte, abierta y con horas registradas
  (en ella y sus descendientes, hasta el corte) ≥ 50 % de su `time_estimate`. Mensaje: «“Modelación · 19-oct” venció
  el 23-10, lleva 11 de 12 h y sigue abierta: si terminó, cerrarla». Va a la hoja aunque la porción no tenga HH.
- `n_porciones_vencidas_abiertas` y `hh_porciones_vencidas_abiertas` (Σ `time_estimate` de esas porciones), y
  `avance_fisico_si_cerradas`: el avance físico que tendría el proyecto si se cerraran. En `proyectos` y
  `metricas_semanales`, para mostrarlos al lado del avance: «avance 42 % · 9 porciones vencidas sin cerrar (120 h) →
  sería 58 %». El titular agrega «9 porciones vencidas sin cerrar (120 h): si se cierran, el avance sería 58,0 %.».
- En el aviso semanal al JP (`mensajes_jp.py`), una línea al inicio con cuántas tiene y en qué proyectos.

**Reproceso** de un corte oficial: `avance_real` y lo que depende de él se recalculan desde `fotos_tareas` (que desde
el 2026-11-04 guarda el avance físico de cada tarea); las columnas de avance físico, modo, manual, consumo y porciones
vencidas se conservan de la fila escrita.

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
- El `time_estimate` es por persona (convención de los JP, 05-11-2026): con varios responsables cuenta completo para
  cada uno, como en Carga de trabajo de ClickUp, y el plan del proyecto suma el de cada responsable.
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

## 5. Asignación, ausencias y carga base

Decisiones de Ale del 2026-11-06 (TAREA_pj_asignar_v2). Código en `pj_asignar/`, `carga_base/`, `ausencias/`, `orden_adm/` y
`dep_reportes/ausencias.py`. Todo escribe en dos pasos: dry-run y, con aprobación, la escritura.

**Disponibilidad** por persona y semana = tope total (la jornada) − carga base − planificado − ausencias − lo asignado en la
misma corrida. Nunca negativa. El planificado usa la regla C de la sección 3, estimate por responsable, en las listas PJ-
activas (sin Proyectos Finalizados ni listas de prueba) y las ADM. Quedan fuera, para no contar dos veces: ADM-01 y las tareas
con tag `carga-base` (su carga ya es la carga base), ADM-07, las tareas cerradas y el árbol de los cajones que se están
asignando.

**Elección.** Personas necesarias por cajón `n = ceil(h/semana ÷ tope_proyecto)`, máximo 3. Candidatos con perfil
(`config/perfiles.yaml`), ordenados por mayor disponibilidad mínima en las semanas del cajón, continuidad y menor carga. Cuenta
como disponible quien tiene libre al menos `porcion_minima` (8 h) o su parte del cajón, si es menor. Lo que falta se propone
fuera de perfil, con aviso. Los ingresos de oct-2026 compiten en todo salvo planos, con tope de 20 h/semana hasta el 2027-01-01
y siempre junto a alguien con historial. Con `--fuente-hh estimate`, un cajón con HH y sin estimate usa las HH y avisa
(`cajon_sin_estimate_usa_hh`). Lo que no cabe queda en `hh_sin_asignar`: no se fuerza.

**Ausencias.** Lista «ADM-07 | Ausencias»: una tarea por persona y tramo; cuenta solo en estado `aprobada`. Horas = 8,8 × días
hábiles (4,4 para medio día), calculadas desde las fechas. Sin `lista_id` en `config/ausencias.yaml` se sigue leyendo la planilla.
ADM-07 no cuenta como horas asignadas ni registradas. En `plan_vs_real` van como filas con proyecto y estado «(ausencia)» y las
horas en `horas_planificadas`: filtrarlas para no sumarlas al plan.

**Carga base.** `config/carga_base.yaml`; `python -m carga_base` crea por persona y semana, 6 semanas hacia adelante, «Administración
· DD-mmm» en ADM-01, las tareas fijas en su lista y las puntuales de una sola semana («Propuestas · DD-mmm», el estimate futuro
que tenía ADM-006, decisión del 2026-11-09), con tag `carga-base`. `--recalibrar` compara con las 8 semanas anteriores y
propone ajustes sin cambiar la config.

**Listas ADM.** `list_code` y `dep_sync` reconocen ADM con dos o tres dígitos (ADM-01, ADM-006).
ADM-01 queda con cuatro tareas: Coordinación y correos, Reuniones internas, Otros administrativos y Elaboración de propuestas
(todo lo de ADM-006). Una entrada movida por copia lleva «movida desde <tarea> el <fecha>» y no cuenta como cargada tarde.
