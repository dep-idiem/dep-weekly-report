# Auditoría documental Drive ↔ SS_REGISTRO — Notas de la Fase 2

Notas escritas a mano. CSV de dry-run, respaldos y logs en `audit_docs/out/` (fuera de git).

## Prerrequisitos (2026-10-06)

- **Campo `Docs OK`**: existe en SS_REGISTRO, dropdown con `Completo`, `Incompleto` y `Sin carpeta`. Los scripts lo buscan por nombre.
- **Make corregido**: no se pudo verificar porque no se ha creado ninguna tarea después de la corrección. La última es 2026.0304 (06-10 09:31) y apuntaba a 06 Backup; el bloque A la corrigió. Ale decidió que la verificación pase a ser prerrequisito del bloque C (antes de activar el cron), con una tarea de prueba en intake o con la próxima propuesta real.

## Cambios en rules.yaml

- `propuesta_economica`: pasa de advertencia a faltante, con `exigir_codigo: true`.
- Formato del código en los nombres de archivo: año y número separados por `.`, `-`, `_` o espacio, con espacios opcionales alrededor. Se acepta `Planilla Base PR DEP 2026 - 0221.xlsx` (plantilla del equipo).
- Pistas cuando hay archivos que calzan con el patrón pero ninguno lleva el código de la tarea (`pista_codigo`; aplica a la económica y a la técnica):
  - `otro_anio`: número correcto con otro año (PR.DEP.2025.0171 en la 2026.0171).
  - `sin_codigo`: sin código o con otro código. De los 21 casos de la económica, 5 son la plantilla `PR.DEP.2025.0000 ECO (uso público)`: el Excel está, pero probablemente el cálculo no.
- `oferta_enviada`: la causa queda separada en `oferta_mal_ubicada` (04 vacía y PDF con el código en 03), `sin_oferta` y `por_revisar` (.zip/.rar en 04).

| Corrida | COMPLETO | INCOMPLETO | SIN_CARPETA | NO_APLICA | HISTORICA | FUERA_DE_ALCANCE |
|---|---|---|---|---|---|---|
| v2 (cierre Fase 1) | 36 | 43 | 2 | 26 | 7 | 169 |
| v3 (económica faltante, sin «2026 - NNNN») | 2 | 77 | 2 | 26 | 7 | 169 |
| v4 (con «2026 - NNNN», después del bloque A) | 12 | 67 | 2 | 26 | 7 | 169 |

La estimación era de ~63 INCOMPLETO. Los 14 casos con `2026 - NNNN` ahora cumplen la económica, pero solo 10 pasan a COMPLETO; los otros 4 siguen INCOMPLETO por la oferta.

Causas en la v4: 17 con 03 y 04 vacías; económica sin Excel 7 (más las 17 vacías y otras combinaciones), `sin_codigo` 21 y `otro_anio` 6; oferta `oferta_mal_ubicada` 16, `sin_oferta` 27 (incluidas las 17 vacías) y `por_revisar` 2. Lista para la reunión: `out/vacias_2026-10-06.md` (17).

## Preguntas abiertas

- **Tareas con link duplicado**: ninguna carpeta PR está enlazada desde dos tareas. 0024/0025 y 0044/2025.0311 son errores de archivo, no tareas duplicadas: en la carpeta de 2026.0024 (Antucoya) la oferta se llama "PR.DEP.2026.0025 … Antucoya" (la 0025 real es Cárceles y está cancelada), y en la 0044 hay un PDF de la 2025.0311 (FACH).
- **API de checklists**: se prueba al inicio del bloque B.

## Bloque A — Corrección de `Drive PR URL` (cerrado el 2026-10-06)

Dry-run `out/fix_links_2026-10-06.csv` (copia `_revisado.csv`): A1 66, A2 8, A3 0.

- **Piloto A1 en 2026.0304**: apply → 200 (link a la carpeta PR, verificado), revert → 200 (vuelve a 06 Backup, verificado), reapply → 200 (verificado). Revert probado con una tarea real.
- **A1 completo**: 65 escrituras con HTTP 200 y 0304 omitida porque ya tenía el valor nuevo. Las 66 verificadas en vivo resuelven a su carpeta PR.
- **A2**: 8 escrituras con HTTP 200 (2026.0147, 0148, 0150, 0152, 0153, 0155, 0156, 0157), todas verificadas.
- **A3**: sin filas. La única candidata, 2026.0097, es de Láser y queda fuera de alcance.
- **Dry-run de control** después de aplicar (`_control.csv`): A1 0, A2 0, A3 0.
- **No se tocaron**: 2025.0321 (ganada), 2026.0095 (cancelada) y 2026.0015 (cerrada), cuyo link da 404 y no aparecen por código; 2026.0027 (Laboratorio), con link 404 pero fuera de alcance. `Drive PJ URL` no se modificó.
- Respaldo: `out/fix_links_2026-10-06_backup.csv`. Log por fila: `out/fix_links_2026-10-06_log.csv`. Para revertir: `python -m audit_docs.fix_links --revert out/fix_links_2026-10-06_backup.csv [--solo …]`; usa el primer valor respaldado de cada tarea.
