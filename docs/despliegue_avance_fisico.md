# Despliegue: avance físico calculado (TAREA_avance_fisico, 2026-11-04)

Definiciones en `docs/definiciones_reporte.md`, sección 1c. Código en `dep_reportes/avance.py`; los checklists se
leen del listado de tareas de ClickUp (`dep_clickup.client.parse_task`: `checklist_total`, `checklist_resueltos`). No se
escribe nada en ClickUp. Dry-run del corte preliminar del 03-11-2026 con antes/después en
`reportes/avance_fisico/comparacion.md` (no se commitea: lleva nombres de tareas de los JP).

## Qué cambia en la hoja «DEP - Reportes»

| Pestaña | Cambio |
|---|---|
| `proyectos` | 7 columnas nuevas al final: `avance_fisico`, `avance_fisico_modo` (cerrada / porciones / checklist / consumo / mixto), `consumo_pct`, `hh_porciones_vencidas_abiertas`, `n_porciones_vencidas_abiertas`, `avance_fisico_si_cerradas`, `avance_manual` |
| `metricas_semanales` | las mismas 7 al final (vacías en los cortes anteriores). `avance_real` queda **obsoleto**: lleva el mismo valor que `avance_fisico`. El titular dice «Avance físico …» y, si hay porciones vencidas sin cerrar, agrega cuántas y el avance si se cerraran |
| `metricas_fase` | 3 columnas al final: `avance_fisico`, `avance_fisico_modo`, `avance_manual` |
| `fotos_tareas` | sin columnas nuevas: `avance_real` lleva el avance físico de cada tarea del presupuesto (vacío en las demás) y `origen_avance` su modo |
| `advertencias` | tipo nuevo `porcion_vencida_abierta` (tarea, JP, prioridad normal). Dejan de emitirse `avance_sin_horas` y `horas_sin_avance` (miraban el campo manual) |
| `serie_diaria` | `hh_gastadas_acum` y `hh_prog_acum` **no cambian**. Cambian `hh_proyectadas_acum` (reparte (1 − avance) × HH) y `hh_ganadas_acum` del corte en curso (avance × HH); los cortes anteriores de la curva ganada conservan su avance de entonces, así que puede haber un escalón en el corte del cambio |

Lo que depende del avance cambia con él: EV, SPI, CPI, `hh_pendientes`, `semanas_desfase`, `horas_necesarias_semana`,
`fecha_termino_estimada`, semáforo y `delta_avance_real` (el primer delta compara el avance físico con el avance
antiguo del corte anterior).

## Qué hacer en Looker Studio

1. Fuentes `proyectos`, `metricas_semanales` y `metricas_fase`: **Actualizar campos**.
2. Cambiar los gráficos y tablas que usan `avance_real` a `avance_fisico` (mismo valor desde este corte). Cuando no
   quede ninguno, se borra `avance_real` del esquema (se mantiene una corrida más para no romper páginas).
3. En la tabla de proyectos, al lado del avance: `avance_fisico_modo`, `n_porciones_vencidas_abiertas`,
   `hh_porciones_vencidas_abiertas` y `avance_fisico_si_cerradas`. Campo calculado sugerido:
   `CONCAT("avance ", ROUND(avance_fisico*100,0), " % · ", n_porciones_vencidas_abiertas, " porciones vencidas sin cerrar (", ROUND(hh_porciones_vencidas_abiertas,0), " h) → sería ", ROUND(avance_fisico_si_cerradas*100,0), " %")`
   (mostrarlo solo cuando `n_porciones_vencidas_abiertas > 0`).
4. `consumo_pct` como indicador aparte (presupuesto gastado), nunca en el mismo eje que el avance.
5. `avance_manual` es solo informativo: no ponerlo en la curva ni en el semáforo.

## Qué hacer en ClickUp (recomendación, no lo hace el reporte)

- **«Avance Acumulado»** (fórmula que solo mira fechas y está mal escrita) y **«% Avance»**: ya no se leen. Recomendado
  borrarlos de las listas PJ; si se quiere conservar algo de fechas, corregir la fórmula a «% de plazo transcurrido»
  (días desde el inicio ÷ días entre inicio y término de la tarea, con tope 0–100 %) y renombrarla así, para que nadie
  la lea como avance.
- **«Avance Real»** (manual): ya no entra en el cálculo. Se puede dejar para el JP que lo use (sale como
  `avance_manual`) o quitar de la plantilla de listas nuevas.
- Para que el avance físico no subestime: cerrar las porciones cuando terminan (la advertencia
  `porcion_vencida_abierta` y la línea del aviso semanal lo recuerdan).

## Cómo desplegar

Como los anteriores: cherry-pick del commit en un worktree de origin/main, tests, `git push HEAD:main`, `git rebase
origin/main` en el main local. Luego, con el OK de Administración DEP, la preliminar (o el oficial del domingo) con
escritura desde el worktree de origin/main. No hace falta reprocesar cortes anteriores (tampoco conviene: sus
`fotos_tareas` tienen el avance antiguo).
