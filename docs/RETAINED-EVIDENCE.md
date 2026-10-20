# Conjuntos de evidencias y relaciones guardadas

En **Análisis estático local**, selecciona una operación de **Evidencias** y marca
los análisis que quieras utilizar. Cada entrada muestra su operación y SHA-256.
Los resultados se consultan por secciones y registros, se citan como los demás
análisis y se descargan completos desde el trabajo. Las mismas operaciones están
en `theseus_analysis_catalog` y `theseus_analysis_start`, dentro de Vitruvius.
No necesitan un modelo ni una conexión con el programa analizado.

## Conjunto canónico y comparación

`evidence.bundle` recibe `source_job_ids` y, opcionalmente,
`query: {unknowns: [...]}`. Conserva los bytes JSON originales en base64, su hash,
la operación y el hash del artefacto. Los registros iguales comparten un
`record_id`; cada trabajo conserva su propia ocurrencia. La identidad del registro
no depende de su ID de trabajo local. El hash del conjunto cubre también las
ocurrencias y el historial de incógnitas.

Cada incógnita contiene `unknown_id` y todas sus revisiones desde 1, consecutivas:
`revision`, `state` (`open` o `resolved`), `statement`, `evidence_ids` y, para una
resolución, `resolution`. Las citas deben pertenecer al conjunto. Una resolución
declarada conserva su explicación y evidencias; no certifica comportamiento.

`evidence.compare_bundles` selecciona dos trabajos `evidence.bundle` mediante
`reference_job_id` y `candidate_job_id`. Por defecto compara miembros exactos.
Para relacionar registros distintos, declara parejas uno a uno en
`query.record_pairs`, con `left_record_id` y `right_record_id`. El resultado
incluye los dos conjuntos completos. Conserva adiciones, omisiones y las
revisiones avanzadas, retiradas o divergentes. Un miembro omitido queda como
desconocido. `behavior_status` siempre es `not-evaluated`.

## Agregar cambios y contrastar hipótesis

`evidence.changed_behavior` selecciona trabajos `process.compare`,
`artifact.compare` y `evidence.compare_functions`. Sigue sus referencias retenidas dentro del proyecto y
verifica los hashes de todo el cierre. Recalcula las dimensiones de procesos a
partir de ambas capturas; recalcula las comparaciones de inventarios con el
núcleo estático local, incluidas las ocho dimensiones de los dossieres completos
de funciones. Un documento ausente, alterado o incompatible conserva
el resultado desconocido. Las diferencias de inventario son candidatos
estáticos; las dimensiones de procesos describen las ejecuciones guardadas.

`evidence.correlate` utiliza las mismas entradas y una lista explícita:

```json
{"query":{"hypotheses":[{
  "id":"selected-rule",
  "static_record_id":"rec_<hash del registro de comparación estática>",
  "logical_path":"rule.py",
  "runtime_record_id":"rec_<hash del registro de comparación de procesos>",
  "dimension":"stdout",
  "expected":"both-changed",
  "side_alignment":"left_to_left",
  "statement":"Los lados seleccionados corresponden a las mismas versiones declaradas"
}]}}
```

Los IDs estables se leen en la agregación. `expected` admite `both-changed`,
`static-only`, `runtime-only` y `both-unchanged`. La coincidencia debe identificar
una única clasificación estática y una única dimensión de ejecución conocida. Las
ausencias y ambigüedades siguen desconocidas. Los nombres, rutas parecidas y
relojes no crean asociaciones automáticas. Una coincidencia con la hipótesis
declarada **no establece causalidad**. El cierre completo queda incluido.
Las ocurrencias sin cambio se obtienen de los dos inventarios completos validados.
También se puede seleccionar una dimensión de función con `static_dimension` y
declarar la alineación de lados. Consulta [Comparar funciones guardadas](RETAINED-FUNCTIONS.md).

## Todas las vías de llamada directas más cortas

`evidence.call_paths` selecciona dossieres `binary.analyze_function` completos
y recibe `query: {start: "0x1000", goal: "0x2000"}`. Valida el contrato completo
de cada dossier, el artefacto, proveedor, versión, perfil, revisión y contexto.
Normaliza los offsets hexadecimales conservando el espacio de direcciones; los
nombres son etiquetas y pueden repetirse.

La búsqueda enumera todas las vías directas más cortas, con citas en cada nodo
y arista y todos los documentos originales incluidos. No impone un límite de
profundidad o de número de vías. Una función que falte antes de alcanzar la
profundidad mínima, cobertura incompleta de llamadas salientes, llamadas sin
resolver o dossieres contradictorios impiden certificar el conjunto de vías.
`not_found` solo se devuelve tras explorar el cierre alcanzable completo.
Inicio y destino iguales producen la vía de cero saltos cuando su dossier e
identidad están presentes. Las relaciones estáticas no demuestran llamadas
durante una ejecución.

## Transferencia y límites

La exportación de evidencias de Vitruvius incluye los documentos originales.
Tras importar, selecciona los trabajos importados para crear una consulta
nueva. Sus bytes e IDs internos permanecen históricos; las referencias de
trabajos del proyecto se reasignan por el formato de transferencia. Ninguna
consulta abre rutas de artefactos originales, reanuda sesiones ni ejecuta el
programa. Los hashes comprueban integridad; no prueban autenticidad ni la
veracidad de las observaciones declaradas por un productor.
