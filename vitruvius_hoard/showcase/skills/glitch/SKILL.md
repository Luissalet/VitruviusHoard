---
name: showcase-glitch
description: Reproduce the glitch showcase with explicit material, light and motion decisions.
version: 2.0.0
---

# Retrato sobre rejilla

## Procedure

Construye la referencia ejecutable Retrato sobre rejilla con sus recursos locales. Silueta fotográfica verde pálida sobre rejilla verde oscura. La máscara alfa local portrait-cutout.png sigue pelo y hombros; se obtuvo mediante extracción de fondo con ImageGen a partir de la foto de stock. El relieve de luminancia se limita a 0,12 unidades para conservar el rostro. La velocidad del puntero crea un impulso acotado que decae exponencialmente con exp(-9·dt). Las franjas horizontales, separación RGB y bloques de datamosh duran mientras el gesto se asienta. El reposo conserva la cara reconocible y sin parpadeo automático. Barlow para el título, nota de interacción y datos de señal. Los rótulos SEÑAL / RGB están en HTML y rodean la silueta; no tapan el centro del rostro. En móvil el título permanece sobre el retrato. El vertex shader de la rejilla curva la superficie cerca del puntero. El fragment shader del retrato aplica RGB y bandas según el impulso, sin deformación facial amplia. Intensidad y centrado siguen disponibles. Movimiento reducido y still anulan el impulso. La máscara elimina el rectángulo de fotografía y hace que la figura emerja de la rejilla. Separar la velocidad de la posición permite que el glitch tenga un inicio y un asentamiento, en vez de romper la cara permanentemente. Conserva móvil, teclado, táctil, enlaces HTML, exportación y fallback. Compara el fotograma citado y tus capturas lado a lado, incluyendo sus estados interactivos.

### light

Silueta fotográfica verde pálida sobre rejilla verde oscura. La máscara alfa local portrait-cutout.png sigue pelo y hombros; se obtuvo mediante extracción de fondo con ImageGen a partir de la foto de stock. El relieve de luminancia se limita a 0,12 unidades para conservar el rostro.

### rhythm

La velocidad del puntero crea un impulso acotado que decae exponencialmente con exp(-9·dt). Las franjas horizontales, separación RGB y bloques de datamosh duran mientras el gesto se asienta. El reposo conserva la cara reconocible y sin parpadeo automático.

### typography

Barlow para el título, nota de interacción y datos de señal. Los rótulos SEÑAL / RGB están en HTML y rodean la silueta; no tapan el centro del rostro. En móvil el título permanece sobre el retrato.

### interaction

El vertex shader de la rejilla curva la superficie cerca del puntero. El fragment shader del retrato aplica RGB y bandas según el impulso, sin deformación facial amplia. Intensidad y centrado siguen disponibles. Movimiento reducido y still anulan el impulso.

### why

La máscara elimina el rectángulo de fotografía y hace que la figura emerja de la rejilla. Separar la velocidad de la posición permite que el glitch tenga un inicio y un asentamiento, en vez de romper la cara permanentemente.

## Implementation

- portrait-cutout.png es una extracción alfa derivada de portrait.jpg mediante ImageGen; origen, método, prompt y hash acompañan la exportación. Para otra fotografía entrega una máscara alfa que siga su contorno; no uses un óvalo para sustituir la silueta.
- Los colores RGB se comparan contra el canal original, de modo que la separación cromática vale cero al reposar.
- Comprueba showcaseState.impulse durante un gesto y después de 600 ms; debe asentarse. El shader sigue dibujando lotes finitos después del input.

## Verification

- Comprobar fotografía cargada, rejilla y volumen en escritorio y móvil.
- Mover el puntero y comparar showcaseState.deformation. Cambiar Deformación y centrar.
- Verificar navegación y texto accesibles con WebGL desactivado.
- Comparar lado a lado el fotograma citado y las capturas propias de 1440 y 390 px. Comprobar materia, sombra, ritmo, contraste y espacio dedicado al artefacto.
