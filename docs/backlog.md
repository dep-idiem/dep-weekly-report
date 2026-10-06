# Backlog

Cambios pendientes del reporte, con su motivo. Al tomar uno, moverlo a una TAREA y borrarlo de aquí.

## Saldo histórico del Timetracker por contrato, no por lista

*Anotado el 06-10-2026 (Ale), a partir de la migración del programa CMP-SHM.*

Hoy el saldo del Timetracker se asocia a una **lista** por el código en su nombre (`dep_reportes/run.py`, `base_de` /
`tt_por_codigo`). El corte histórico se calcula con la primera entrada nativa de esa lista, o con
`config/reportes.json` → `corte_historico`. Consecuencias:

- **No se puede archivar una lista vacía sin perder horas.** El reporte no lee listas archivadas. Si se archiva, su
  saldo pasa a otra lista con el mismo código base (en CMP-SHM, la finalizada "PJ-2025.0147 Diagnóstico"), que no
  tiene corte histórico y suma el Timetracker completo. El 06-10 eso contó 12 h dos veces en el contrato 0147.
- **Si una lista se queda sin entradas nativas, pierde su corte histórico.** Hubo que fijarlo a mano:
  `"PJ-2025.0147": "2026-06-03"`.

Por esto hoy hay que mantener viva la lista "PJ-2025.0147 | CMP-SHM Apilador (histórico) | CMP", vacía y con
`solo_consumo`.

**Propuesta:** en los programas (`config/programas.json`), asociar el saldo histórico al **contrato**, con su código
del Timetracker y su corte histórico en `contratos.<id>`, en vez de a una lista. Así la lista 0147 se podría archivar,
y el saldo de 0019 dejaría de depender del nombre de la lista General.
