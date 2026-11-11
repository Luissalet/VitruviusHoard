# Objetivos del verificador de protocolos

## Recetas de escaparate, tarea 2782

Segunda pasada de luz, materia y ritmo implementada y comparada con fotogramas de Links en escritorio y móvil para responder a la revisión de Claude. Entrega de la rama #2782 pendiente de su veredicto antes de integrar en main; no se considera aprobado por superar las pruebas funcionales.

Implementadas cinco referencias ejecutables y su biblioteca consultable por API/MCP, con recetas, skills, descarga y enlace al flujo Rehacer. El comparador conserva la puntuación de cada ronda y cada receta define los estados interactivos que comprobar. En encargos posteriores, ampliar las recetas a partir de las diferencias observadas y registrar las medidas de las reconstrucciones realizadas. Consulta `docs/SHOWCASE-RECIPES.md`.

Corrección 2007 integrada y revisada: replay fiel de ramas y propiedades, contraejemplo mínimo entre tipos de propiedad, tipos de estado distintos y resultado visible en el paso inicial. Las capacidades restantes de Vitruvius y el estado de Theseus siguen descritos en FAUSTUS y sus documentos propios.

Los modelos de protocolos son declarativos y acotados. Antes de conectar el test generado con un servicio real, definir qué llamada representa cada paso atómico y cómo se controla la rama indicada. Ampliar el lenguaje solo con semántica y casos verificables; un resultado del modelo no acredita automáticamente el código del servicio.

## Secuencias con estado contra servicios reales (Theseus, #2032)

Hecho: receta declarativa (destino, modelo, acciones con precondiciones, parámetros con semilla, identificadores reenlazados, oráculos ejecutables), ejecución contra un proceso real con estado nuevo por corrida, reducción con la misma firma, cobertura observada, reproducción contra otra versión y exportación pytest autónoma, verificado con el servicio de presupuestos v1 (defectuoso) y v2 (corregido). Hecho (03-11-2026): elección de identificadores por paso productor (`{"from": id_del_paso, "var": extractor}`) además de por índice, registro del productor al generar y reasignación de esas elecciones al reducir (al productor superviviente más cercano y al más antiguo del mismo conjunto, probando ambos; sin productor vivo el candidato se descarta sin ejecutarse); en el ejemplo de presupuestos con semilla 5 la reducción pasa de 5 a 4 pasos (el mínimo real). Pendiente posible: servicios con autenticación por sesión en la preparación, y valores de conjuntos que ningún extractor produjo (siguen eligiéndose por índice).
