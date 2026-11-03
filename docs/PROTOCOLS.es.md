# Comprobador de protocolos

Pantalla **Protocolos**, rutas `/api/protocols/*` y herramienta `protocol_check`. Recorre en anchura todas las intercalaciones de un protocolo pequeño y acotado y comprueba sus propiedades. Si algo falla devuelve el **contraejemplo más corto**, lo repite paso a paso y genera un test pytest para reproducirlo en el sistema real.

## Especificación

```json
{"name": "…",
 "vars": {"processed": [], "charges": 0},
 "const": {"key": "pedido-42"},
 "processes": [{"name": "intento", "count": 2, "locals": {"seen": false},
   "steps": [
     {"label": "comprobar", "set": {"seen": "key in processed"}},
     {"label": "cobrar", "choose": [
        {"when": "seen", "goto": "end"},
        {"when": "not seen", "set": {"charges": "charges + 1"}, "goto": "marcar"}]},
     {"label": "marcar", "set": {"processed": "append(processed, key)"}, "goto": "end"}],
   "crash": {"max": 1, "restart": "comprobar"}}],
 "invariants": [{"name": "un solo cobro", "check": "charges <= 1"}],
 "at_end": [{"name": "cobrado", "check": "charges == 1"}],
 "deadlock": true, "max_states": 200000}
```

- Cada paso es **atómico**: todas sus asignaciones leen el estado anterior al paso. Sin `goto`, sigue el siguiente paso; tras el último, el proceso termina.
- `choose`: alternativas no deterministas (cada una con `when`, `set`, `goto`); se exploran todas.
- `count`: copias del proceso (`me` es su número, `self` su nombre).
- `crash`: el proceso puede caer hasta `max` veces en cualquier punto; vuelve a `restart` y pierde sus locales (salvo `keep_locals`); lo compartido persiste, como una base de datos.
- Propiedades: `invariants` en cada estado; `at_end` cuando todos han terminado; `deadlock` cuando nadie puede avanzar sin haber terminado. Pueden leer las variables compartidas, `ended` y `crashes`.
- Expresiones: subconjunto de Python seguro (literales, `and/or/not`, comparaciones, `in`, `+ - * // %`, `x if c else y`, índices y `len min max abs sorted append put without set_add set_remove`). Nada de atributos, importaciones ni llamadas arbitrarias.

## Resultado

`violated` (con traza, `schedule` y estado final), `holds` (se recorrió **todo** el espacio alcanzable dentro de los límites) o `inconclusive` (límite de estados o de tiempo). Siempre acompaña la lista de **supuestos**: la conclusión vale para el modelo, no para el código.

## Ejemplos incluidos

`pago-no-atomico` (doble cobro en 4 pasos), `pago-reserva-atomica` (se cumple con caídas: 148 estados), `contador` (incremento perdido), `cerrojos` (bloqueo en 2 pasos).
