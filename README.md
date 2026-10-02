# Reportes semanales DEP

Lee los proyectos de los folders **PJ Ingeniería** (en curso) y **Proyectos Finalizados** del espacio Proyectos Activos de ClickUp (solo lectura), congela líneas base, calcula la curva S y las métricas de avance, y las escribe en la hoja de Google Sheets **"DEP - Reportes"**, que alimenta el reporte de Looker Studio.

- **Oficial (semanal):** lunes 04:00 (hora de Santiago), corte = domingo anterior. Queda en el historial.
- **Preliminar (diaria):** martes a domingo 19:00, fecha de control = día anterior. Se conservan las preliminares de los últimos 15 días (`config/reportes.json`); la oficial borra las preliminares con corte hasta su domingo.

Cero escrituras en ClickUp. En la hoja no hay datos por persona, salvo el nombre y correo del JP de cada proyecto.

## Proyectos finalizados

Al terminar, la lista de un proyecto se mueve de PJ Ingeniería a Proyectos Finalizados (`dep_reportes/finalizados.py`). La lista conserva `list_id`, código y línea base, y queda con `estado_proyecto = finalizado` en `proyectos` y en todas sus filas de las demás pestañas, también las antiguas.

- **Cambio de folder** (estaba en curso en un corte anterior): en el corte en que cambia se escriben sus métricas semanales, la advertencia informativa `proyecto_finalizado` y su fila en la pestaña **`cierres`**. Desde el corte siguiente queda congelada: sin filas semanales nuevas y con la serie diaria del corte de cierre.
- **Incorporado ya finalizado** (nunca se vio en curso): solo la fila de `proyectos`, la de `cierres` y la advertencia. No se inventan semanas que no se observaron.
- `cierres`: una fila por proyecto, solo en corridas oficiales. Contiene las HH gastadas totales (con el saldo del Timetracker), frente a la línea base y frente al contrato; el avance final; y la duración real (del inicio a la última hora registrada) frente a la contractual (entrega de la línea base o, si falta, el vencimiento de la lista), en días hábiles.
- Si la lista vuelve a PJ Ingeniería, en el siguiente corte oficial vuelve a quedar en curso y su cierre se borra.
- Las listas de Proyectos Finalizados sin código `PJ-`/`PR-` no entran. Las listas que tienen filas en la hoja pero ya no están en ninguno de los dos folders quedan con `estado_proyecto = fuera_de_folders`.

**Looker Studio:** en las tablas y gráficos de proyectos en curso, agregar el filtro `estado_proyecto = en_curso` (además de `es_ultimo_corte` o `es_ultimo_oficial`, como hoy). Los cierres se muestran desde la pestaña `cierres`.

## Proyección a la entrega y reproceso de cortes oficiales

- `hh_estimadas_al_termino` (metricas_semanales) lleva la curva proyectada hasta la última tarea pendiente. `hh_estimadas_a_entrega` es el valor de esa curva en la fecha de término vigente (vencimiento de la lista en ClickUp; hasta octubre de 2026 era la entrega contractual de la línea base); queda vacío si la entrega ya pasó o si no hay línea base. `fecha_termino_usada` es el término con que se repartieron los pendientes atrasados.
- **Un corte oficial ya escrito no se vuelve a calcular con ClickUp en vivo** (`dep_reportes/reproceso.py`). Correrlo de nuevo recalcula `metricas_semanales` y `metricas_fase` solo desde sus `fotos_tareas`, su línea base (la vigente en su última escritura) y el saldo histórico y el término guardados en su fila. No toca las demás pestañas. Si a algún proyecto le falta un dato (por ejemplo, filas escritas antes de existir `fecha_termino_usada`), el corte no se reescribe y queda una fila `reproceso_omitido` en `ejecuciones` con el dato que falta.
- `reprocesado_en` (metricas_semanales): si un corte oficial se escribió más de una vez con ClickUp en vivo (antes de esta regla), sus números son de la última escritura; la columna guarda ese momento y `ejecuciones` tiene una fila `reprocesado` con "reprocesado con datos de <fecha>". Es el caso de los cortes del 20-09 (datos del 25-09 15:37) y del 27-09 (datos del 29-09 15:13). Ambas cosas se deducen del historial de `ejecuciones` en cada escritura.

**Extensión de plazo** (`proyectos` y `metricas_semanales`): `fecha_entrega_contractual` es la entrega congelada en la línea base vigente (no cambia), `fecha_termino_vigente` / `fecha_termino_usada` el vencimiento actual de la lista, `es_extension` es verdadero si el vencimiento es posterior a la contractual y `dias_extension` la diferencia en días hábiles (negativa si el plazo se adelantó; vacía sin línea base). Mover la fecha de la lista en ClickUp no requiere una revisión de la línea base: las revisiones quedan para cambios de alcance. En Looker, la tabla de fechas por proyecto se arma con la fuente `proyectos` (una fila por proyecto), no con `linea_base` (una fila por tarea y revisión).

**Looker Studio:** mostrar `reprocesado_en` junto al corte (por ejemplo, "reprocesado con datos de …" cuando no está vacío) y agregar `hh_estimadas_a_entrega` junto a `hh_estimadas_al_termino`.

## Programas de servicio continuo

Proyectos largos que no se miden con curva S, sino por contrato y por línea de trabajo (`dep_reportes/programas.py`, configurados en `config/programas.json`). Hoy: **CMP-SHM** (Monitoreo SHM CMP), con los contratos 0019 (Los Colorados) y 0147 (Apilador) y las líneas General, Informes y Modelos.

- **Línea:** la de la lista (cada encargado presenta solo la suya). **Contrato:** fijo en la lista (`"contrato"`) o deducido del nombre de la fase con `patron_fase`. Si la fase calza con más de un contrato o con ninguno, la hora queda como `compartido`: aparece en las horas por línea y en las columnas `hh_compartidas_*` de `programa_contratos`, pero no en el consumo de ningún contrato, y genera la advertencia de nivel programa `programa_horas_compartidas` (para Administración DEP, con el total y las fases de origen). Así la vista funciona con las listas actuales y también con una lista «General» que tenga una fase por contrato: basta cambiar `listas` en la config.
- **Horas:** las mismas que el reporte cuenta en cada lista (el total del programa es la suma de `hh_gastadas_acum` de sus listas). El saldo histórico del Timetracker va al contrato fijo de su lista, en la línea `historial`.
- **`solo_consumo`:** la lista no entra a la vista (horas por línea ni entregables), pero sus horas cuentan en el consumo de su contrato (la finalizada 0147-A).
- **Presupuesto:** `hh_periodo` (HH del período) o `hh_mes`, con `periodo_inicio` y `periodo_fin`. Ritmo planificado = HH del período / meses calendario del período. Mientras falte la cifra, las columnas de plan quedan vacías.
- **Advertencias:** las de `advertencias_omitidas` no se emiten para estas listas (vencimiento, línea base y tarea 1.2, código duplicado, lista combinada, presupuesto contractual). Un programa continuo no se marca como vencido.
- **Pestañas** (se reemplazan completas en cada corrida; con `--solo` no se tocan):
  - `programa_horas`: horas por mes, contrato, línea, lista y origen (`clickup` / `timetracker`).
  - `programa_contratos`: por contrato y mes, `hh_mes`, `hh_acum`, `hh_acum_periodo`, `hh_plan_mes`, `hh_plan_acum` y `pct_consumido`; los meses posteriores al corte llevan solo el plan (`es_futuro`).
  - `programa_entregables`: tareas cuyo nombre calza con `entregables` (informes `IM-`, visitas `VT-`), con `situacion`: `a_tiempo`, `atrasado` (cerrada después de su fecha), `vencido` (abierta y con fecha pasada), `pendiente`, `sin_fecha` o `cerrado_sin_fecha_cierre`. Las líneas de `entregables_excluir_lineas` no aportan entregables (hoy Modelos: sus IM son aportes al informe); sus horas sí cuentan en la línea.
- **Limpieza de entregables** (advertencias para Administración DEP, llegan en `_administracion.txt`): `entregable_plantilla_sin_usar` (abierta con el número sin completar, `patron_plantilla`), `entregable_duplicado` (mismo código, p. ej. IM-02, en una lista y un contrato) y `entregable_fecha_inconsistente` (cerrada más de `dias_cierre_anticipado` días antes de su fecha de entrega).
- La columna `programa` (en `proyectos` y en las tablas de hechos) identifica las listas de un programa: filtro `programa` vacío en las páginas de curva S.

**Looker Studio:** ver `docs/looker_programas.md`.

## Estructura

| Ruta | Qué es |
|---|---|
| `dep_clickup/` | Cliente de solo lectura de la API de ClickUp (límite de 100 peticiones/min, reintentos ante 429). |
| `dep_reportes/` | Métricas (`metricas.py`, `proyecto.py`), líneas base (`linea_base.py`), hoja (`almacen.py`, `esquema.py`), proceso (`run.py`) y worker de Actions (`worker.py`). |
| `config/` | `reportes.json` (retención de preliminares), `controles.json` (umbrales de los controles de cordura), `dias_no_habiles.csv` (días no hábiles propios de IDIEM, además de los feriados de Chile). |
| `scripts/` | Validación contra el Excel (fase 1), calidad de datos, prueba de Google y restauración de respaldos. |
| `.github/workflows/reportes.yml` | Workflow de GitHub Actions. |
| `requirements-worker.txt` | Dependencias del worker con versiones fijas (incluidas `holidays` y `tzdata`). |

## Secretos de GitHub

En el repo: **Settings → Secrets and variables → Actions → New repository secret**. Son cuatro:

| Secreto | Valor |
|---|---|
| `CLICKUP_TOKEN` | El token personal de ClickUp (el mismo `CLICKUP_TOKEN` del `.env` local). |
| `GOOGLE_OAUTH_CLIENT_JSON` | El contenido de `secrets/google_oauth_client.json`, **en una sola línea** (ver abajo). |
| `GOOGLE_REFRESH_TOKEN` | El campo `refresh_token` de `secrets/google_token.json`. |
| `SHEETS_REPORTES_ID` | El ID de la hoja (el `SHEETS_REPORTES_ID` del `.env`). |

Para copiar los valores de Google al portapapeles sin mostrarlos en pantalla (PowerShell, desde la carpeta del proyecto):

```powershell
python -c "import json; print(json.dumps(json.load(open('secrets/google_oauth_client.json')), separators=(',',':')))" | Set-Clipboard
python -c "import json; print(json.load(open('secrets/google_token.json'))['refresh_token'])" | Set-Clipboard
```

El JSON va en una sola línea porque GitHub enmascara los secretos en los logs línea por línea; un JSON de varias líneas se enmascara mal. El código nunca imprime secretos.

## Correr a mano

En GitHub: **Actions → Reportes DEP → Run workflow**.

- `tipo`: `preliminar` u `oficial`.
- `corte` (opcional): oficial = un domingo (por defecto, el último); preliminar = cualquier día (por defecto, ayer).
- `dry_run`: si está marcado, no escribe en Sheets y deja los CSV como artefacto `dry-run-…` (7 días).

La corrida manual ignora la ventana horaria, pero no repite una corrida exitosa del mismo tipo en el mismo día (salvo en dry-run).

En local:

```powershell
python -m dep_reportes.run --tipo-corte preliminar --dry-run          # CSV en reportes/dry_run/
python -m dep_reportes.run --tipo-corte oficial --corte 2026-10-04    # escribe en la hoja (un corte ya escrito: reproceso desde fotos)
python -m dep_reportes.linea_base revisar --list-id <id> --motivo "…" [--tipo tardia] [--dry-run]
python -m pytest -q
```

## Controles antes de escribir

Si alguno falla, no se escribe nada salvo una fila `control_fallido` en `ejecuciones`, y el workflow termina en error (GitHub envía un correo):

- cero entradas de tiempo en todo el folder en los últimos 7 días;
- el número de proyectos cae más de 20 % respecto de la última corrida exitosa;
- un proyecto con línea base vigente queda sin métricas;
- cambia el TotalHH de una línea base existente.

Los umbrales están en `config/controles.json`.

## Reautenticar Google

Si el workflow falla con **"reautenticar Google"**, Google revocó el refresh token (por ejemplo, tras un cambio de contraseña o una revocación de acceso). Para obtener uno nuevo, en el PC:

1. Borrar `secrets/google_token.json`.
2. Correr `python scripts/google_humo.py`: abre el navegador; iniciar sesión con la cuenta del dominio y aceptar. Debe imprimir el título de la hoja.
3. Copiar el nuevo `refresh_token` (comando de la sección de secretos) y actualizar el secreto `GOOGLE_REFRESH_TOKEN` en GitHub.
4. Lanzar una corrida manual con `dry_run` para comprobar.

## Restaurar desde un respaldo

Antes de cada escritura, el contenido de la hoja se guarda y se sube como artefacto **`respaldo-…`** del workflow (30 días).

1. En la corrida de Actions, descargar el artefacto `respaldo-<run_id>-<intento>` y descomprimirlo (queda una carpeta con un CSV por pestaña y `metadata.json`).
2. Ver qué haría: `python scripts/restaurar_respaldo.py --dir <carpeta>`.
3. Restaurar: `python scripts/restaurar_respaldo.py --dir <carpeta> --confirmar`.

No se tocan `ejecuciones` (se le agrega una fila `restaurado`) ni `linea_base` (solo se agregan filas; usar `--incluir-linea-base` únicamente para quitar una revisión agregada por error).

## Activar los cron y notificaciones

Los cron están comentados en `.github/workflows/reportes.yml`. Para activarlos, descomentar el bloque `schedule` y hacer commit **con tu usuario de GitHub** (por ejemplo, editando el archivo en la web). GitHub envía el correo de fallo de los workflows programados a quien modificó por última vez la sintaxis del cron. Revisar que en **Settings → Notifications → Actions** esté activado "Send notifications for failed workflows only".

Cada corrida deja su fila en la pestaña `ejecuciones` (éxito, fallo con detalle o control fallido); las corridas omitidas por ventana horaria no se registran.
