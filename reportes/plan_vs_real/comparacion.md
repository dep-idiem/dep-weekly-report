# Comparación antes/después: PJ-2026.0225 (Correa 2741) y PJ-2026.0235 (Shiploader)

Fecha: 2026-11-02. TAREA_reportes_plan_vs_real.md, con las decisiones de Ale del 2026-11-02. Solo lectura: dry-run, sin
escribir en Sheets ni en ClickUp.

**Cómo se corrió.** El corte oficial del 01-11 ya está escrito, y `--corte 2026-11-01` solo lo reprocesa desde las
fotos guardadas (no pasa por la lógica que cambia). Por eso «antes» (código en `HEAD` = 77201d6) y «después» son
corridas **preliminares** del corte 01-11 con datos en vivo de ClickUp del 02-11:
`python -m dep_reportes.run --tipo-corte preliminar --corte 2026-11-01 --dry-run [--solo <list_id>]`.
Salidas en `reportes/plan_vs_real/antes/<list_id>/` y `despues/{<list_id>,todas}/`.

## Lo que cambió en ClickUp desde el corte oficial del 01-11 (no es efecto del código)

- La Correa tenía **17 tareas con HH que sumaban 1.267** (fotos del corte 01-11). Hoy tiene **79 tareas con 2.723 HH**:
  se cargaron HH Presupuestadas en unas 62 porciones (+1.456 HH). Con la regla de presupuesto de Ale (solo las tareas
  sin ancestro con HH) da lo mismo, 2.723, porque ninguna tarea con HH tiene un ancestro con HH: las tareas 5.x, 6.x,
  etc. no tienen HH.
- En el corte del 18-10, «00 Administración» tenía **744 HH** (titular «Consumidas 0 de 744 HH contratadas»). Hoy no
  tiene HH: de ahí sale `sin_presupuesto_contractual`.
- «1.2 Plan de Trabajo» quedó *completado*. Con el código anterior, **la próxima corrida congelaba la Rev. 0 con 2.723
  HH** (79 filas): es la columna «antes» de abajo.
- Las fechas de agosto ya se corrigieron: «3.2 Revisión de Documentos» vence el 23-10 y «4.1 Visita a Terreno 1» va del
  26 al 28-10.
- **El inicio de la lista es el 15-10-2026** y sale del campo de inicio de la propia lista (`start_date` de la lista,
  04:00 hora de Chile), no de la primera tarea. La tarea con el inicio más temprano es «00 Administración», el 21-08.
  La TAREA decía 13-10.

## PJ-2026.0225 Correa 2741

| | antes | después |
|---|---|---|
| Línea base | **Rev. 0 nueva, normal, 79 filas, 2.723 HH** | provisional, **retenida** (no se congela) |
| HH del programado | 2.723 (congeladas) | 2.723 (provisionales, sin guardar) |
| Programado al corte | 531,5 HH (19,5 %) | 531,5 HH (19,5 %), provisional |
| Real | 17,5 % · 351,7 HH gastadas | igual |
| Titular | «Avance real 17,5 % frente a 19,5 % programado: 2,0 puntos bajo el plan.» | «Programado provisional (línea base retenida: presupuesto contractual por confirmar contra la propuesta). Avance real 17,5 % frente a 19,5 % programado: 2,0 puntos bajo el plan.» |
| Fecha contractual | 13-12-2026 (solo porque se congelaba la Rev. 0) | 13-12-2026, vencimiento de la lista · `entrega_texto` «13-12-2026» · 29 días hábiles |
| Advertencias nuevas | — | `linea_base_retenida`; `horas_en_tarea_ss` «75,8 h registradas en la tarea de la SS…»; `fechas_anteriores_al_inicio` «1 tarea(s) con fechas anteriores al inicio del proyecto (14-10-2026)…» |

El oficial del 01-11 en la hoja decía «Sin curva programada: el proyecto está en planificación (la tarea 1.2 sigue
abierta)», con fecha contractual vacía. Con el código nuevo ese mensaje ya no existe, y la fecha contractual sale de la
lista aunque no haya línea base.

**Plan y registrado por semana** (`plan_semanal`, h):

| semana | plan oficial 01-11 (hoja) | plan antes (hoy) | **plan después (regla C)** | registrado PJ | **registrado SS** |
|---|---|---|---|---|---|
| 19-10 | 137,5 | 0 | **129,5** | 144,8 | **26,8** |
| 26-10 | 186,0 | 0 | **240,0** | 183,0 | **0** |
| 02-11 | 287,0 | 0 | **253,0** | (futura) | (futura) |

- El plan de la regla C para el 26-10 (**240 h**) coincide con el informe. Para el 02-11 da 253 h y el informe dice 267:
  la lista cambió hoy (hay porciones creadas el 02-11).
- «Antes (hoy)» da 0 porque el cálculo anterior solo sumaba tareas de clase *porción* (hoja sin HH Presupuestadas, sin
  numeración, ≤ 7 días) y ponía el time estimate **entero en la semana de inicio**. Al cargarles HH a las porciones,
  pasaron a ser paquetes y salieron del plan. El 01-11, cuando todavía no tenían HH, daba 137,5 / 186 / 287: sin
  prorrateo, con las tareas sin responsable y sin las que tienen HH.
- **309/451 y 252** no se reproducen con los datos de la hoja ni con los de hoy: ningún corte guardado tiene esas cifras
  de plan ni de registrado. Lo que sí calza: la semana del 19-10 tiene **144,8 h en la lista PJ + 26,8 h en la tarea SS
  = 171,6 h** (el «172»), y las 26,8 h son el «+27» de Sebastián en la SS. El registrado ya era por fecha trabajada
  (inicio de la entrada) antes de este cambio; lo nuevo es que las horas de la SS se ven aparte. Para cerrar 309/451 y
  252 necesito el método del informe «Correa 2741 esta semana».
- Horas necesarias (fila «(proyecto)», semana 02-11): 818,6 h. Como hoy las HH están en las porciones y no en cajones,
  «necesarias» es el resto de las porciones con HH que vencen esta semana más el de las vencidas que siguen abiertas
  (todo cae en la primera semana después del corte). No es la barra roja del informe, que se calculó sobre los 17 cajones
  de 1.267 HH.

La tabla persona × semana (sección D) está en `reportes/plan_vs_real/correa_persona_semana.md`. Tiene datos por persona
y no se commitea.

## PJ-2026.0235 Shiploader (control: nada cambia donde no debe)

| | antes | después |
|---|---|---|
| Línea base | Rev. 0 normal, 1.002 HH | igual |
| Programado / real | 915,5 HH (91,4 %) / 83,1 % · 580,4 HH gastadas | igual |
| Titular | «Avance real 83,1 % frente a 91,4 % programado: 8,3 puntos bajo el plan.» | igual |
| Fecha contractual | 06-11-2026 | igual · `entrega_texto` «06-11-2026» · 5 días hábiles |
| Plan semanal 19-10 / 26-10 / 02-11 | 58 / 60 / 65 | **75 / 69 / 95** (regla C: entran todas las tareas con responsable, fechas y time estimate, no solo las porciones) |
| Registrado PJ 19-10 / 26-10 | 9,0 / 18,5 | igual |
| Registrado SS 19-10 / 26-10 | — | 0 / 2,8 |
| Advertencias | 21 | 22: + `horas_en_tarea_ss` «103,1 h registradas en la tarea de la SS…» |

Curva S, línea base y métricas quedan idénticas. Cambian solo el plan semanal (por la decisión 2) y las horas de la
SS, que ahora se ven.

## Todas las listas (dry-run completo, después, frente al oficial del 01-11 en la hoja)

- **Listas que ya tienen Rev. 0:** `total_hh`, `hh_prog_acum` y `hh_actuales_clickup` quedan **iguales** en todas. La
  regla de presupuesto (sin ancestros con HH) no cambia ninguna lista con línea base.
- **Congelarían la Rev. 0 en la próxima corrida:**

  | lista | tipo | HH | evento |
  |---|---|---|---|
  | PJ-2026.0272 | normal | 130 | primera hora registrada el 29-10-2026 |
  | PJ-2026.0221 | tardía | 190 | primera porción creada «1.1 KOM» el 13-10-2026 (la lista empieza el 05-11) |
  | PJ-2026.0147 | tardía | 162 | primera porción creada «4.1 Picados Locales y Pacómetro» el 22-09-2026 (la lista empieza el 16-11) |
  | PJ-2025.0019-0147-B | tardía | 22,5 | primera porción creada «5.1 Modelación y Análisis Estructural» el 28-05-2026 |
  | PJ-EJEMPLO Cajones e hitos (lista de prueba) | tardía | 600 | primera porción creada «04a Modelación y análisis» el 23-10-2026 |

- **Pasan a provisional** (sin evento todavía, o retenida): PJ-2026.0225 (retenida), PJ-2026.0271, PJ-2024.0008-A,
  PJ-2025.0321-A y PJ-TEST Carga de horas.
- **Fecha contractual**, que ahora aparece en las listas sin línea base: PJ-2024.0008-A, PJ-2025.0019,
  PJ-2025.0019-0147-A/B, PJ-2025.0147, PJ-2025.0311, PJ-2025.0321-A, PJ-2026.0079, PJ-2026.0147, PJ-2026.0221,
  PJ-2026.0225, PJ-2026.0271 y PJ-2026.0272 (todas toman el vencimiento de la lista).
- Advertencias nuevas en todo el corte: `fechas_anteriores_al_inicio` 13, `horas_en_tarea_ss` 11 y
  `linea_base_retenida` 1.
- `sin_tarea_1_2`, `tarea_1_2_no_aplica`, `varias_tareas_1_2` y `en_planificacion` ya no se emiten.

## Pendientes y decisiones

1. **Porciones de plantilla como disparador.** En la 0221 y la 0147 la Rev. 0 se congelaría antes de empezar el
   proyecto: hay tareas de plantilla con responsable, fecha y time estimate (por ejemplo «1.1 KOM»), y para la regla
   cuentan como porción. ¿Lo dejo así o la porción debe además no tener numeración de plantilla?
2. **Listas de prueba** (PJ-EJEMPLO, PJ-TEST): hoy entran al reporte. Propongo agregarlas a `linea_base_retenida`
   para que no se les congele línea base en la hoja real.
3. **Cifra de la Correa:** en cuanto me la des, se saca la 0225 de `linea_base_retenida` y la Rev. 0 se congela en la
   corrida siguiente con las HH que tenga la lista ese día. Si la cifra no coincide con la suma de la lista (hoy
   2.723), hay que corregir ClickUp antes de liberar, o congelar a mano con `python -m dep_reportes.linea_base revisar`.
4. `pj_create`: las opciones `old_due_date` / `old_start_date` de la API de plantillas de ClickUp no están probadas en
   vivo. Verificar en la próxima creación de lista (o con una lista de prueba) que las tareas salgan sin fechas.
