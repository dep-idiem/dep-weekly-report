# Despliegue: asignación, ausencias en ClickUp y carga base

Orden de escritura, cada bloque con OK de Ale: D (renombres y movimientos) → B (lista, formulario, importación) → C (carga base)
→ E (porciones; repetir el dry-run antes, porque D y C cambian la disponibilidad).

## Qué cambia

- **Hoja `plan_vs_real`:** al llenar `lista_id` en `config/ausencias.yaml` aparecen filas con proyecto «(ausencia)». Los
  encabezados no cambian. Cualquier suma de `horas_planificadas` debe filtrar `proyecto <> (ausencia)`.
- **Looker («DEP - Reportes»):** sin cambios; no lleva datos por persona.
- **Informe semanal:** lee ausencias de ADM-07 en vez de la planilla, y ADM-07 no suma como asignado ni registrado. Las siglas de los
  JP salen de `siglas` en `config/informe_semanal.yaml`.
- **Carga de trabajo de ClickUp:** se ve la carga base y las ausencias de cada persona (por eso se les pone Time Estimate).
- **TSheet:** los renombres no cambian de proyecto (las ADM van por id de lista). `dep_sync/clickup.py` está fuera de git: su
  regex de ADM se cambió solo en este PC. ADM-006 va entero a «Elaboración de propuestas» en ADM-01 (decisión del 2026-11-09),
  así que ninguna entrada pasa a SS_REGISTRO (excluida de TSheet).
- **Entradas movidas:** si ClickUp no deja cambiar la tarea de una entrada, `orden_adm` la copia con «movida desde <tarea> el
  <fecha>» en la descripción y borra la original. El informe semanal no cuenta esas copias como cargadas tarde.
- **Configuración local:** `config/asignables.yaml` y `config/perfiles.yaml` llevan nombres y quedan fuera de git; `pj_asignar`
  y `carga_base` solo corren en el PC de Ale. Las herramientas locales (`pj_asignar`, `carga_base`, `ausencias`, `orden_adm`)
  dependen de la bitácora y de `ss_load_hours`, que aún no están en origin/main: se suben junto con esos módulos.
- **`python -m ausencias sincronizar`:** el formulario no calcula el Time Estimate; hay que correrlo periódicamente.
