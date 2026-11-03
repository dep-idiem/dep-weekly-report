# Nota de despliegue: línea base única, plan vs real por persona y fechas (TAREA_reportes_plan_vs_real)

Estado: commit local, **sin push y sin desplegar**. Requiere el OK de Ale. **No correr el worker (ni preliminar)
hasta desplegar esto**: con el código anterior, la Correa 0225 congela la Rev. 0 con 2.723 HH.

Definiciones: `docs/definiciones_reporte.md`. Comparación: `reportes/plan_vs_real/comparacion.md`.

## 1. Hoja aparte para el plan vs real por persona (la crea Ale)

- **Nombre propuesto:** `DEP - Plan vs real por persona (JP)`.
- **Pestaña:** `plan_vs_real`. La crea el worker en la primera escritura, con encabezados y formato de fecha. La hoja
  puede quedar vacía.
- **Permisos:**
  - Ale (dueña): editora. Es la cuenta Google con que escribe el worker: el OAuth de `GOOGLE_REFRESH_TOKEN` es el mismo
    de «DEP - Reportes». Si el refresh token es de otra cuenta, esa cuenta también debe ser editora.
  - JP del DEP: **lectores**, con nombre. Hoy son JP de listas: Sebastián Contreras, Sergio Tapia Pérez, Fernando Muñoz
    Benavides, Luciano Gálvez A., Felipe Yañez Valdés, Tomas Navarrete Arenas, Genesis Díaz S., Pablo Herrera y Pilar
    Castellón.
  - Sin «cualquier persona con el enlace» y sin compartir con el dominio completo.
  - Administración DEP: según lo que decida Ale.
- **Configuración del worker:**
  - Local: `SHEETS_PLAN_VS_REAL_ID=<id>` en `.env`.
  - GitHub: secreto `SHEETS_PLAN_VS_REAL_ID`. `reportes.yml` ya lo pasa al paso «Ejecutar reporte».
  - Sin el id, la pestaña solo se escribe en el CSV del dry-run, con un aviso en el log. Si el id es el mismo de «DEP -
    Reportes», tampoco escribe: `run.ejecutar` lo impide.
- El artefacto «dry-run» de `reportes.yml` excluye `plan_vs_real.csv`, para que no queden datos por persona en GitHub.

### Columnas de `plan_vs_real`

`fecha_corte` (fecha) · `corte` (fecha) · `tipo_corte` · `semana_inicio` (fecha) · `list_id` · `proyecto` (código
sin «PJ-») · `proyecto_nombre` · `jp` · `persona` · `horas_planificadas` · `horas_registradas` ·
`horas_registradas_ss` · `cumplimiento` · `estado` · `horas_necesarias_semana` · `es_ultimo_corte` (booleano).
El detalle de cada columna está en `docs/definiciones_reporte.md` §4.

### Página de Looker «Plan vs real por persona» (fuente nueva, conectada a esa hoja)

- **Fuente:** Hojas de cálculo de Google → `DEP - Plan vs real por persona (JP)` → `plan_vs_real`, con la primera fila
  como encabezados. Credenciales del propietario (Ale). Comparte el **informe** solo con los mismos JP; la fuente no se
  comparte aparte.
- **Tipos en la fuente:**
  - `fecha_corte`, `corte` y `semana_inicio` como Fecha (AAAAMMDD).
  - `horas_*` y `cumplimiento` como Número. `cumplimiento` en formato porcentaje.
  - `es_ultimo_corte` como Booleano.
- **Filtro por defecto de la página:** `es_ultimo_corte = true` y `tipo_corte = oficial` (o solo `es_ultimo_corte`
  para ver el preliminar).
- **Campos calculados:**
  - `es_persona` = `NOT REGEXP_MATCH(persona, "^\\(.*\\)$")`, para excluir «(proyecto)» y «(sin responsable)».
  - `plan_personas` = `SUM(CASE WHEN es_persona THEN horas_planificadas ELSE 0 END)`. Coincide con
    `plan_semanal.hh_planificadas`.
  - `registrado_total` = `SUM(horas_registradas)`.
  - `pct_cumplimiento` = `registrado_total / plan_personas`.
  - `personas_con_plan_y_0h` = `COUNT_DISTINCT(CASE WHEN horas_planificadas > 0 AND horas_registradas = 0 THEN persona END)`.
- **Tabla dinámica:**
  - Filas `persona` (filtro `es_persona`), columnas `semana_inicio`, métrica `cumplimiento` (MAX o AVG; hay una fila
    por celda).
  - Formato condicional por `estado`: `ok` verde, `parcial` ámbar, `sin_registro` rojo, `sin_plan` gris y `futuro` sin
    color. Looker no colorea una métrica según otro campo de la tabla dinámica: o se usa una tabla con `estado` como
    dimensión, o un campo calculado numérico de `estado` con reglas de color.
- **Barras por semana:**
  - Dimensión `semana_inicio`. Métricas `plan_personas`, `SUM(horas_registradas)` y `SUM(horas_necesarias_semana)`
    (esta última es la barra roja; solo trae valor en las filas «(proyecto)»).
  - `SUM(horas_registradas_ss)` como serie aparte, si se quiere ver.
- **Scorecards:** planificado (`plan_personas`), registrado (`registrado_total`), % (`pct_cumplimiento`) y personas con
  plan y 0 h (`personas_con_plan_y_0h`).
- **Filtros:** `proyecto`, `jp`, `persona` y `semana_inicio`.

## 2. Cambios en «DEP - Reportes» (columnas nuevas; ninguna por persona)

| pestaña | columna nueva | qué es |
|---|---|---|
| `proyectos` | `entrega_texto` | vencimiento de la lista dd-mm-aaaa, o «lista sin fecha de término» |
| `metricas_semanales` | `entrega_texto` | ídem |
| `plan_semanal` | `hh_registradas_ss` | horas en la tarea de la SS del proyecto (fuera de la curva S y del cumplimiento) |

Columnas que no cambian de nombre pero sí de contenido:

- `fecha_entrega_contractual`, en `proyectos` y `metricas_semanales`: sin línea base, ahora es el vencimiento de la
  lista (antes quedaba vacía).
- `plan_semanal.hh_planificadas`: la regla C (prorrateo por días hábiles, todas las tareas con responsable, fechas y
  time estimate). Los cortes anteriores no se recalculan.
- `fotos_tareas.dias_atraso` y `vence_en_dias`: vacíos en las tareas con fecha heredada (vencimiento anterior al inicio
  del proyecto).
- `metricas_semanales.linea_base_provisional`: ahora puede ser verdadero en listas antiguas, no solo en las v2.
- `titular`: prefijo «Línea base Rev. 0 congelada en este corte (…).» en el corte en que se congela, y «Programado
  provisional (línea base retenida: …).» en las listas retenidas.

Advertencias nuevas: `fechas_anteriores_al_inicio`, `horas_en_tarea_ss` y `linea_base_retenida`. Ya no se emiten
`en_planificacion`, `sin_tarea_1_2`, `tarea_1_2_no_aplica` ni `varias_tareas_1_2`.

**Qué actualizar en la fuente de Looker de «DEP - Reportes»:** «Actualizar campos» en las fuentes de `proyectos`,
`metricas_semanales` y `plan_semanal`, para que aparezcan `entrega_texto` (Texto) y `hh_registradas_ss` (Número). En la
ficha del proyecto, mostrar `entrega_texto` junto a la fecha contractual (o en su lugar). En la tabla de plan semanal,
agregar `hh_registradas_ss` como columna aparte.

La primera escritura migra los encabezados sola: las columnas nuevas quedan vacías en las filas antiguas.

## 3. Configuración

`config/reportes.json`:
- `ss_registro_list_id`: `901324495476` (SS_REGISTRO).
- `linea_base_retenida`: `{"1400570000001233": "presupuesto contractual por confirmar contra la propuesta"}` (la
  Correa 0225). Para liberarla, se borra la entrada; la Rev. 0 se congela en la corrida siguiente.

## 4. Pasos de despliegue (con el OK de Ale)

1. Ale crea la hoja aparte, la comparte según §1 y define el secreto `SHEETS_PLAN_VS_REAL_ID` (GitHub y `.env`).
2. Decisiones pendientes de `comparacion.md`: porciones de plantilla como disparador (0221 y 0147), listas de prueba
   en `linea_base_retenida`, cifra de la Correa.
3. `git push` del commit (main local está 21 + N commits delante de origin; ver la memoria de la auditoría v2 por el
   rebase anterior).
4. Corrida manual: primero `--dry-run` y revisar `reportes/dry_run/<corte>/`; después la escritura. Al terminar,
   verificar en la hoja la pestaña `plan_vs_real` y las columnas nuevas.
5. Ale actualiza los campos de las fuentes de Looker (§2) y arma la página nueva (§1).
