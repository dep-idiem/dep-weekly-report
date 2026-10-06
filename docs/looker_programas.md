# Página de Looker Studio para programas de servicio continuo

Cómo armar la página del programa **CMP-SHM** (Monitoreo SHM CMP) con las pestañas que escribe el reporte
(`dep_reportes/programas.py`, configuración en `config/programas.json`).

## Fuentes de datos

Agregar a la hoja **"DEP - Reportes"** tres fuentes nuevas, una por pestaña:

| Fuente | Pestaña | Para qué |
|---|---|---|
| Programa · horas | `programa_horas` | Horas por mes, contrato y línea |
| Programa · contratos | `programa_contratos` | Consumo acumulado frente al ritmo planificado, por contrato |
| Programa · entregables | `programa_entregables` | Informes y visitas, a tiempo o atrasados |

Las tres pestañas se reemplazan completas en cada corrida: siempre muestran la última. No hace falta filtrar por
`es_ultimo_corte`.

## Controles (arriba de la página)

1. **Programa** (`programa`): lista desplegable, valor por defecto `CMP-SHM`. Aplica a las tres fuentes.
2. **Línea** (`linea_nombre`): lista desplegable, **sin valor por defecto** (equivale a «todas»). Aplica a
   `programa_horas` y `programa_entregables`. Cada encargado elige su línea al presentar.
3. **Contrato** (`contrato_nombre`): lista desplegable sin valor por defecto. Aplica a las tres fuentes.

`programa_contratos` no tiene línea: el presupuesto es por contrato. El control de línea no la filtra; los gráficos
de consumo muestran siempre el contrato completo.

## Gráficos

**1. Horas por mes y línea** (`programa_horas`). Barras apiladas: dimensión `mes` (fecha, año-mes), desglose
`linea_nombre`, métrica `SUM(hh)`. La línea «Historial Timetracker (sin línea)» son las horas anteriores a ClickUp.
Para ver solo lo registrado en ClickUp: filtro `origen = clickup`.

**2. Consumo frente al plan** (`programa_contratos`), uno por contrato (o con el control de contrato). Líneas:
dimensión `mes`, métricas `MAX(hh_acum_periodo)` (real) y `MAX(hh_plan_acum)` (plan). Mientras no esté el
presupuesto en `config/programas.json`, la línea de plan queda vacía. Los meses futuros (`es_futuro`) muestran solo
el plan.

**3. Indicadores del contrato** (`programa_contratos`, filtro `es_futuro = false` y el último `mes`): tarjetas
con `hh_acum_periodo`, `hh_periodo` y `pct_consumido` (formato porcentaje).

**4. Horas del mes por contrato** (`programa_contratos`). Barras: dimensión `mes`, desglose `contrato_nombre`,
métricas `SUM(hh_mes)` y `MAX(hh_plan_mes)` (ritmo planificado).

**4b. Horas compartidas** (`programa_contratos`). Tarjeta o serie con `MAX(hh_compartidas_acum)` y
`MAX(hh_compartidas_mes)` por `mes`. Usar **MAX, no SUM**: el valor es del programa y se repite en la fila de cada
contrato.

**5. Entregables** (`programa_entregables`).
- Tarjetas: `COUNT(task_id)` con filtros `situacion = a_tiempo`, `atrasado` y `vencido`.
- Tabla: `contrato_nombre`, `linea_nombre`, `nombre`, `fecha_entrega`, `fecha_cierre`, `situacion`, `dias_atraso`,
  con `url` como enlace. Orden: `fecha_entrega` descendente.
- Barras por mes: dimensión `mes`, desglose `situacion`, métrica `COUNT(task_id)`: un informe mensual por contrato.
- Tipos (`tipo_entregable`): `informe` (IM), `visita` (VT), `reporte_diario` (RD) y `reporte_alerta` (RA). La columna
  `frecuencia` dice cómo se cuentan: `mensual` (IM, RD: un paquete por mes; los RD diarios dentro del paquete no
  cuentan aparte) o `evento` (VT, RA: uno por evento, con su plazo como fecha de entrega). Agregar `frecuencia` como
  control o filtro para separar los entregables mensuales de los por evento. La columna es nueva: actualizar los
  campos de la fuente «Programa · entregables».

## Páginas de curva S

En las tablas y gráficos de proyectos en curso, agregar el filtro **`programa` es nulo** (además de
`estado_proyecto = en_curso`), para que las listas del programa no aparezcan como proyectos sin curva.

## Horas «compartido»

En la lista General, una fase que no es de un solo contrato (`00 Administración`, `05 Reportes`, fases históricas
compartidas) cuenta en 0019 (`contrato_por_defecto`), igual que su saldo del Timetracker. En las listas de Informes y
Modelos, las horas registradas en fases que no son de un solo contrato (por ejemplo «PJ-2025.0147/.0019 Informes Visitas»
o «Tareas Generales») aparecen con contrato «Compartido (varios contratos)» en las horas por línea y en
`hh_compartidas_mes` / `hh_compartidas_acum`, pero no suman en el consumo de ningún contrato. Mientras existan, la
pestaña `advertencias` tiene una fila `programa_horas_compartidas` (nivel `programa`, sin `list_id`) con el total y
las fases de origen.
