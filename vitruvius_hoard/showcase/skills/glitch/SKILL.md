---
name: showcase-glitch
description: Una textura fotográfica deforma una malla mediante un shader y responde a la posición del puntero. Use when reproducing the glitch showcase reference.
version: 1.0.0
---

# Retrato sobre rejilla

## Procedure

Construye una entrada con retrato fotográfico sobre rejilla verde pálida y fondo casi negro. Implementa shaders de vértice y fragmento con relieve por luminancia, bandas horizontales, separación cromática y deformación localizada al puntero. Usa una malla subdividida y conserva la fotografía reconocible. Incluye amplitud regulable y centrado, tipografía Barlow local y adaptación móvil. Reproduce la receta glitch. Verifica entrada estable y una posición fija del puntero.

### light

El valor de luminancia de la fotografía da relieve. Verde pálido sobre un fondo verde casi negro concentra la máxima luz en el rostro.

### rhythm

La imagen aparece completa. El desplazamiento se limita a la región cercana al puntero y termina al reposar. No hay parpadeos automáticos.

### typography

Barlow de 38 a 80 px, a la izquierda del retrato en escritorio y encima en móvil. La nota de interacción ocupa veinte caracteres de medida aproximada.

### interaction

Vertex shader con relieve por luminancia y empuje gaussiano. Fragment shader con rejilla de 100×74 celdas, bandas horizontales desplazadas y separación cromática local. Un control regula la amplitud y otro centra.

### why

La densidad de líneas convierte una imagen reconocible en un objeto digital. Mantener la deformación localizada permite explorar la técnica y conservar el rostro.

## Verification

- Comprobar fotografía cargada, rejilla y volumen en escritorio y móvil.
- Mover el puntero y comparar showcaseState.deformation. Cambiar Deformación y centrar.
- Verificar navegación y texto accesibles con WebGL desactivado.
