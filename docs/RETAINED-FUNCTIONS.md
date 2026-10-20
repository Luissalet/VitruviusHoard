# Comparar funciones guardadas y contrastar hipótesis

En **Análisis > Evidencias · Comparar funciones guardadas**, selecciona dos
dossieres completos `binary.analyze_function`. Los selectores muestran el
artefacto, la función o dirección consultada, el estado histórico y el hash del
documento. La operación `evidence.compare_functions` también está disponible
mediante el catálogo dinámico y `theseus_analysis_start`, con
`reference_job_id` y `candidate_job_id`.

El resultado conserva las ocho dimensiones: identidad, pseudocódigo, ensamblado,
comentarios, llamadas, referencias, cadenas/nombres y CFG. Cada dimensión tiene
estado, digests, citas y limitaciones. Las representaciones de texto se comparan
literalmente: no se eliminan direcciones ni nombres generados. Un proveedor,
perfil o faceta desconocidos conservan su incertidumbre. Las diferencias de
texto o de estructura son candidatos estáticos; `behavior_status` permanece
`not-evaluated`.

Los bytes originales de ambos documentos y sus identidades de productor están
incluidos en `closure`. `retained_inputs` liga las citas internas a los hashes
de análisis y artefactos. Estos datos no contienen rutas ni IDs locales de
trabajos, de modo que se puede recalcular la misma comparación tras importar.
El recibo del trabajo mantiene por separado las referencias del proyecto.

## Agregar los tres tipos de comparación

`evidence.changed_behavior` admite comparaciones de procesos, inventarios y
funciones retenidas. Recalcula cada una desde todo su cierre de documentos.
Conserva las dimensiones individuales, sus incógnitas y el origen estático o de
ejecución. `behavior_status` solo resume las observaciones seleccionadas de los
procesos; una diferencia estática no se transforma en ejecución observada.

Al validar inventarios completos se conservan también las ocurrencias únicas
de una misma ruta sin cambios. Su clasificación `unchanged` procede de ambos
inventarios completos y de su comparación recalculada. No se deduce de la sola
ausencia de una entrada en una lista parcial de cambios.

## Seleccionar dimensión, expectativa y alineación

Una hipótesis puede seleccionar `logical_path` para un inventario o
`static_dimension` para una comparación de funciones. Los IDs de registro se
leen en la agregación y permanecen estables al transferir. Por ejemplo:

```json
{"query":{"hypotheses":[{
  "id":"rule-text-and-output",
  "static_record_id":"rec_<hash de la comparación de funciones>",
  "static_dimension":"pseudocode",
  "runtime_record_id":"rec_<hash de la comparación de procesos>",
  "dimension":"stdout",
  "expected":"both-changed",
  "side_alignment":"left_to_left",
  "statement":"La función de referencia corresponde a la ejecución de referencia"
}]}}
```

`side_alignment` admite `left_to_left` y `left_to_right`. El resultado muestra
los lados y hashes de análisis que el usuario ha asociado en `aligned_inputs`.
Las hipótesis de funciones requieren declarar esa alineación. Las consultas
anteriores sobre rutas de artefactos siguen siendo legibles y ejecutables.

`expected` admite `both-changed`, `static-only`, `runtime-only` y
`both-unchanged`. La dimensión debe aparecer exactamente una vez y tener un
estado conocido en su comparación recalculada. Una coincidencia queda como
`consistent-with-declared-association`; una contradicción con la expectativa
queda explícita y una ausencia o faceta desconocida produce `unknown`.

La alineación y la hipótesis son declaraciones del usuario. No se vinculan
funciones, archivos o procesos automáticamente por nombre, dirección o reloj;
`causality` siempre es `not-established`. Todos los documentos que sustentan el
resultado se conservan en su cierre.

Después de exportar e importar, selecciona los dossieres o comparaciones
importados para crear consultas nuevas. No se reabren sesiones binarias ni se
leen archivos originales. Los hashes comprueban integridad de lo retenido; no
certifican la autenticidad ni la veracidad de una observación histórica.
