# Despliegue: curva programada única (TAREA_curva_programada_unica, 2026-11-03)

Definiciones en `docs/definiciones_reporte.md` (secciones 1 y 1b). Dry-run del corte preliminar del 03-11-2026 y
comparación con el código anterior en `reportes/curva_unica/`.

Se sube junto con «línea base única, plan vs real por persona» (643595e), sin su parte de `pj_create`, que sigue en
el main local con el resto de los commits sin push (pj_create, intake, complemento de Gmail, A1, auditorías). Ese
commit agrega `SHEETS_PLAN_VS_REAL_ID` al job de reportes de `.github/workflows/reportes.yml`.

## Qué cambia en la hoja «DEP - Reportes»

| Pestaña | Cambio |
|---|---|
| `proyectos` | 4 columnas nuevas al final: `estado_curva` (ok / sin_presupuesto / presupuesto_incoherente / retenida / recurrente), `programada_modo` (tareas / mixta / lineal; vacío sin programada), `ritmo_real` (h/semana, 2 últimas semanas cerradas) y `semanas_desfase` (HH pendientes / ritmo − semanas hasta el término contractual) |
| `metricas_semanales` | `estado_curva` y `programada_modo` al final. En cortes anteriores quedan vacías |
| `advertencias` | tipos nuevos: `proyecto_sin_presupuesto` (proyecto, JP, alta), `presupuesto_incoherente` (proyecto, JP, alta), `fechas_fuera_de_lista` (tarea, JP). En el dry-run: 4, 0 y 46 |
| `linea_base` | sin columnas nuevas. No se agregan más filas `incremental`. En la primera corrida se congelan la 0271 (291 HH) y la 0272 (130 HH), las dos `normal` por su primera hora registrada; la 0147 y la 0221 ya **no** se congelan (no tienen horas: antes las congelaba la primera porción), y CMP-SHM Modelos tampoco (es recurrente) |
| `serie_diaria`, `metricas_fase` | la programada cambia donde hay tareas al respaldo (tabla del dry-run) |
| `programa_horas`, `programa_contratos`, `programa_entregables` | filas nuevas de los programas AITO-HPC y AITO-SOTERO |
| columna `programa` | AITO-HPC en PJ-2025.0321 y Cartas AITO HPC; AITO-SOTERO en PJ-2024.0008 y Cartas Sótero (se actualiza en todas sus filas, también las antiguas) |

Cifras que se mueven en las listas con Rev. 0 o provisionales (corte preliminar 03-11): 0177 (avance programado
52 % → 42 %; dos tareas empiezan antes del inicio de la lista), 0173 (98 % → 100 %; seis tareas terminan después del
término guardado, 09-10), 0235 (93 % → 97 %), 0225 retenida (24 % → 31 %; 18 porciones de diciembre caen después del
término 13-12) y 0221 (4 % → 0 %). 0079, 0146, 0271, 0272 y 0313 no cambian.

Las Rev. 0 que ya están en la hoja de PJ-2024.0008 y PJ-2025.0321 (tardías) se conservan pero no se usan: esas listas
pasan a recurrentes y dejan de tener programada (`avance_prog` vacío). El reproceso de un corte oficial ya escrito usa
la programada nueva (con respaldo): reprocesar un corte anterior cambia su `hh_prog_acum` donde haya tareas al
respaldo.

## Qué hacer en Looker Studio

1. Fuentes `proyectos` y `metricas_semanales`: **Actualizar campos** (aparecen `estado_curva` y `programada_modo`; en `proyectos`, también `ritmo_real` y `semanas_desfase`).
2. Páginas de curva S: el filtro `programa` es nulo ya existe; con él, las listas AITO salen de esas páginas como las
   de CMP-SHM. Sugerido: un control de `estado_curva` y la columna `programada_modo` en la tabla de proyectos (una
   `mixta` o `lineal` indica fechas para corregir).
3. Página del programa: el control `programa` ahora tiene también AITO-HPC y AITO-SOTERO. Sin presupuesto en la
   config, su línea de plan queda vacía.
4. La advertencia `fechas_fuera_de_lista` lleva el motivo en el mensaje; la lista completa por JP está en
   `reportes/curva_unica/respaldo_por_jp.md`.

## Configuración

- `config/reportes.json` → `linea_base_retenida`: se agregan PJ-TEST (1400570000001689) y PJ-EJEMPLO
  (1400570000002107).
- `config/programas.json`: programas AITO-HPC y AITO-SOTERO (contrato único cada uno, líneas Servicio y Cartas, sin
  entregables ni presupuesto todavía).
