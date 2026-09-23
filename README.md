# Reportes semanales DEP

Lee los proyectos del folder **PJ Ingeniería** de ClickUp (solo lectura), congela líneas base, calcula la curva S y las métricas de avance, y las escribe en la hoja de Google Sheets **"DEP - Reportes"**, que alimenta el reporte de Looker Studio.

- **Oficial (semanal):** lunes 04:00 (hora de Santiago), corte = domingo anterior. Queda en el historial.
- **Preliminar (diaria):** martes a domingo 19:00, fecha de control = día anterior. Se conservan las preliminares de los últimos 15 días (`config/reportes.json`); la oficial borra las preliminares con corte hasta su domingo.

Cero escrituras en ClickUp. En la hoja no hay datos por persona, salvo el nombre y correo del JP de cada proyecto.

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
python -m dep_reportes.run --tipo-corte oficial --corte 2026-09-27    # escribe en la hoja
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
