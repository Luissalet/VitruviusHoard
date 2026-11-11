# Recetas de escaparate

La biblioteca se abre desde la portada de Vitruvius o en `/showcase/`. Incluye cinco páginas ejecutables y sus decisiones de luz, ritmo, tipografía, interacción y composición. Cada par contiene un prompt de construcción, una skill específica, fuentes visuales con instantes de vídeo, código editable y comprobaciones en escritorio y móvil.

| Referencia | Implementación | Interacción |
| --- | --- | --- |
| Libro a doble página | Hoja HTML dividida en veinte segmentos con caras y perspectiva | Arrastre reversible, muelle amortiguado, botones y flechas |
| Retrato sobre rejilla | Fotografía con shaders de relieve, bandas y separación cromática | Puntero, amplitud y centrado |
| Sala-galería | Sala WebGL con suelo, focos, sombras y paneles | Cámara con rueda, teclado y gesto, selección por raycast o enlace |
| Ciudad como mapa | Edificios y ventanas instanciados con alturas deterministas | Zoom, giro, destinos y pieza roja seleccionable |
| Producto sobre roca | Anillo, gema y basalto con geometría, grano y materiales físicos | Escena fija con cámara y luz ligadas al scroll reversible |

Los ejemplos usan contenido de demostración. Instrument Serif y Barlow, las fotografías de stock y el motor de representación se sirven desde el paquete. La máscara `portrait-cutout.png` deriva del retrato mediante extracción de fondo con ImageGen; método, prompt y hash constan en `assets/provenance.json`. Los orígenes, hashes y licencias acompañan las descargas. Los fotogramas de los reels se consultan mediante Links y conservan los derechos de sus autores.

## Materia, luz y ritmo de las referencias

La segunda pasada de #2782 incorpora pliegos oscuros con fotografía a sangre, grano y canto de papel; una silueta alfa sobre rejilla curvada con glitch que responde a la velocidad y se asienta; ocho obras fotográficas en fuga con marcos gruesos, haces y reflejos suaves; una ciudad densa con detalles de fachada, ventanas variables en cuatro caras, luz roja que tiñe el entorno, niebla y órbita lenta; y dos anillos sobre basalto fracturado con normal map, polvo y tres fotogramas clave ligados al scroll. Las cinco páginas tienen entrada animada y navegación discreta con objetivos interactivos de 44 px.

El postproceso de WebGL usa curva fílmica, bloom contenido y desenfoque leve según la profundidad de la escena. Los reflejos de paneles y estelas son proyecciones gráficas aproximadas; los haces son conos aditivos; el brillo de gema se proyecta mediante focos de color. Estas decisiones se documentan en las recetas y sus skills: no se atribuyen reflexión por trazado de rayos, dispersión volumétrica ni cáusticas refractivas completas. Los ocho paneles reutilizan tres proyectos de demostración.

Con movimiento reducido no hay órbita, estelas móviles, glitch ni paralaje del puntero. Se conservan los desplazamientos de cámara que la persona solicita explícitamente con los controles o el scroll. `still=1` fija la composición de entrada para Rehacer. Todas las escenas suspenden el render al ocultarse; la ciudad mantiene un bucle de órbita mientras esté visible y el movimiento esté permitido.

## API y herramientas

La consulta de biblioteca y fuentes funciona con los módulos apagados. El catálogo normal del host y el puente MCP ofrecen cuatro herramientas adicionales.

| Herramienta | Argumentos | Resultado |
| --- | --- | --- |
| `showcase_recipes` | `query` opcional, castellano o inglés | Pares ordenados por coincidencias, enlaces de referencia y descarga |
| `showcase_recipe` | `id` | Receta completa, skill específica, procedimiento común, fuentes e instrucciones para Rehacer |
| `showcase_source` | `id`, `path` opcional | Fuente real y SHA-256, entrada HTML por defecto |
| `showcase_remake` | `id`, `mode`, `widths`, `max_rounds` opcionales | Ejecución retenida de Rehacer y estados que comprobar |

Los identificadores son `book`, `glitch`, `gallery`, `city` y `rock`. Los mismos datos se leen por `GET /api/showcase`, `GET /api/showcase/{id}` y `GET /api/showcase/{id}/source?path=scene.js`. La descarga completa está en `GET /api/showcase/{id}/download`.

El ZIP lleva las cinco entradas para conservar los enlaces entre proyectos, los recursos compartidos, la receta elegida y su skill. Se sirve con `python -m http.server 8080`. La entrada raíz muestra la receta y permite recorrer las referencias. Todos los recursos de representación se cargan localmente.

## Rehacer

Activa Diseño desde el control habitual o el botón de la biblioteca y pulsa «Rehacer esta referencia». `showcase_remake` utiliza el mismo `remake_start`, almacenamiento, rondas, informes y comparador de paridad que Rehacer. El navegador sirve exclusivamente los recursos incluidos desde `https://showcase.vitruvius.invalid`. Ese origen virtual funciona dentro de la captura y evita depender de un servidor de demostración adicional.

El modo `copy` prepara una ronda de composición estable a 1440 y 390 px. El modo `rebuild` utiliza el modelo global configurado y seis rondas por defecto. Cada receta describe además los estados de cámara, hoja, puntero, selección y scroll que requieren comprobación de interacción.

Las puntuaciones corresponden a las composiciones capturadas. Una copia estática de un lienzo conserva la imagen de escritorio y puede diferir del encuadre móvil calculado por la escena. Los informes y sus puntuaciones se conservan incluso cuando quedan por debajo del umbral. La reconstrucción con modelo y la paridad de los estados interactivos adicionales se verifican en cada encargo que las ejecute.

## Verificación

`python -m pytest tests/test_showcase.py tests/test_remake.py tests/test_parity.py` comprueba pares, búsqueda acentuada, archivos exportados, hashes, rutas, descubrimiento en frío y despacho al flujo existente. Las pruebas de navegador deben abrir la biblioteca desde la portada, recorrer las cinco páginas a 1440×900 y 390×844, usar sus controles normales, verificar movimiento reducido y conservar enlaces al faltar WebGL.

La evidencia de la entrega #2782 conserva capturas de ambas anchuras, giro y segundo pliego, detalle de producto, llamadas reales al puente MCP y cinco ejecuciones retenidas de Rehacer en una instancia aislada. El acta de entrega registra los comandos y resultados exactos.
