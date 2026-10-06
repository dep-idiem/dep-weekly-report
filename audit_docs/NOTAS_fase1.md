# Auditoría documental Drive ↔ SS_REGISTRO — Notas de la Fase 1

Notas escritas a mano (no las genera `recon.py`). Los reportes de cada corrida están en `audit_docs/out/`
(fuera de git: nombres de personas y de archivos).

- **v1** (2026-10-06): `rules.yaml` inicial de la tarea + mapa de estados, alcance por ubicación y Tipo DEP.
  Reporte: `out/recon_2026-10-06_v1.md`.
- **v2** (2026-10-06): ajustes 1 a 6 de abajo aplicados a `rules.yaml`. Reporte: `out/recon_2026-10-06.md`.
## Ajustes propuestos tras la primera corrida (v1)

Cumplimiento de las reglas que aplican: propuesta_economica falla en 39 de 83, propuesta_tecnica en 22 de 83 y oferta_enviada en 46 de 79.

1. **Leer un nivel más dentro de 03 y 04.** Hay 11 carpetas con subcarpetas dentro de 03 o 04 (Rev 1, Rev 2, OLD, Final, Oferta Técnica, Oferta Económica). En 2026.0152, 0155 y 0157 los documentos están ahí y hoy dan falsos faltantes. Propuesta: `recursivo: 1`, ignorando OLD y Antiguo.
2. **propuesta_tecnica por nombre y código, no solo por extensión.** En 14 de 105 carpetas 03 hay más de un PDF, y el patrón actual también calza con correos ("Correo de IDIEM…"), ofertas de otra unidad (PR.DGI…) e informes antiguos. Además hay carpetas con documentos de otra propuesta: 0249 tiene archivos de 2024.0063 y 2024.0098, 0024 tiene los de 0025, 0044 los de 2025.0311 y 0192 uno de 0185. Propuesta: `patron: '^PR[.\- ]?DEP[.\-]\d{4}[.\-]\d{4}.*\.(pdf|docx?)$'` y exigir que el código del archivo sea el de la tarea (opción `exigir_codigo: true`).
3. **propuesta_economica como advertencia, no como faltante.** Falta Excel en 39 de 83. En 22 de esos casos la carpeta 03 tiene la oferta en .docx o .pdf, pero ninguna planilla. Cuando hay planilla, el nombre varía: "Planilla Base PR DEP 2026…", "Presupuesto…", "METODOLOGIA…". Propuesta: `nivel: advertencia` mientras el equipo no acuerde una convención.
4. **oferta_enviada se mantiene estricta.** Es la regla que más falla (46 de 79). En 43 de esos casos la carpeta 04 está vacía, y en 20 hay un PDF de la oferta en 03. Es una brecha real de proceso: la oferta enviada no se archiva en 04. Conviene que vaya al checklist de la Fase 2 y no relajarla. Ajustes menores: aceptar `.zip` y `.rar` en 04 marcándolos como "por revisar" (0155, 0157), y mostrar como pista "hay PDF con el código en 03".
5. **Reglas de 03 desde ENVIADA, no desde ELABORACION.** Las 4 tareas en elaboración que quedan INCOMPLETO (0262, 0266, 0267, 0269) son propuestas que se están escribiendo. Exigir documentos antes del envío produce faltantes por tiempo, no por error.
6. **Corte histórico por código, no por fecha.** Todas las tareas tienen `date_created` desde el 26-01-2026 (es la fecha de la migración), así que `fecha_inicio_make` no separa nada. Las 7 tareas de Ingeniería sin link son propuestas de 2024 y 2025 (2024.0008, 2025.0001, 0144, 0147, 0303, 0311 y 0316), casi todas ganadas y vigentes como proyecto. Propuesta: `codigo_inicio_make: "2026.0001"`, de modo que los códigos anteriores sin link queden como HISTORICA. Con eso quedarían 2 SIN_CARPETA reales: 2025.0321 y 2026.0095, ambas con link 404 y sin carpeta por código.
7. **Alcance por Tipo DEP.** La correspondencia es exacta: Ingeniería está en DEP - CENTRAL, Laboratorio en see-laboratorio_estructuras y Láser en DEP-ULP-2026 (salvo 2026.0097, de Láser, que tiene carpeta en DEP - CENTRAL). Laboratorio no tiene carpetas nuevas desde abril: de sus tareas, 121 no tienen link. Si se incorpora, necesita su propio bloque de subcarpetas (01 Solicitud Servicio (SS), 05 Backup).
8. **Antes de la Fase 2, corregir el escenario de Make.** El error de "06 Backup" sigue ocurriendo: afecta también a propuestas recién creadas en intake (0258, 0265, 0271, 0274, 0278, 0304). Si no se corrige, la lista 7.2 vuelve a crecer cada semana.

## Resultado de la segunda corrida (v2)

Ajustes 1 a 6 aplicados en `rules.yaml`. El 7 (alcance por Tipo DEP) ya estaba en la v1 y el 8 (Make) no es del YAML.

| Resultado | v1 | v2 |
|---|---|---|
| COMPLETO | 26 | 36 |
| INCOMPLETO | 57 | 43 |
| SIN_CARPETA | 9 | 2 |
| NO_APLICA | 22 | 26 |
| HISTORICA | — | 7 |
| FUERA_DE_ALCANCE | 169 | 169 |

Cambios de v1 a v2: 10 INCOMPLETO pasan a COMPLETO (lectura de subcarpetas, económica como advertencia y .zip/.rar
por revisar), 4 INCOMPLETO pasan a NO_APLICA (en elaboración) y 7 SIN_CARPETA pasan a HISTORICA (códigos
2024/2025). Ninguna tarea empeoró con el patrón más estricto de propuesta_tecnica. Las 2 SIN_CARPETA que quedan
son 2025.0321 (ganada) y 2026.0095 (cancelada): link 404 y sin carpeta por código. Advertencias de
propuesta_economica: 32.

### Qué queda en las 43 INCOMPLETO

| Causa | Tareas | Lectura |
|---|---|---|
| Oferta: 04 vacía, PDF con el código en 03 | 16 | Oferta archivada en la subcarpeta equivocada |
| Oferta: 04 vacía, solo Word en 03 (sin PDF) | 7 | No hay PDF de lo enviado: 0062, 0126, 0147, 0195, 0212, 0225, 0228 |
| Carpeta 03 y 04 vacías | 17 | Los documentos no están en Drive. En la mayoría solo hay archivos en 00 Solicitud Servicio |
| 03 solo con documentos de otra propuesta | 3 | 0024 (archivos de 0025), 0044 (2025.0311), 0249 (2024.0063/0098) |

Solo se cumple en parte la expectativa de que lo que quede sea "casi todo oferta en el lugar equivocado": 23 de 43
son de oferta (16 con el PDF en 03), pero 17 son carpetas vacías. Esas 17 son las que más importan para la
Fase 2: las 17 están enviadas, ganadas, perdidas o cerradas y no tienen ningún documento de la oferta en Drive (0239, 0240, 0250, 0251, 0253 y
0254 son de agosto y septiembre).

### Pendiente de decidir

- Tratar "PDF con el código en 03" como cumplido (con advertencia) o como faltante. Hoy es faltante con pista.
  Si se acepta, INCOMPLETO baja a 27.
- 0024/0025 y 0044/2025.0311: confirmar si son la misma propuesta registrada dos veces (licitación duplicada,
  continuación) o un error de archivo.
- Corregir el escenario de Make (06 Backup) antes de que la Fase 2 escriba en ClickUp.
