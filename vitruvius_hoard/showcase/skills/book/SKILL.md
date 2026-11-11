---
name: showcase-book
description: Tres pliegos con una hoja segmentada en perspectiva, arrastre y retorno por muelle amortiguado. Use when reproducing the book showcase reference.
version: 1.0.0
---

# Libro a doble página

## Procedure

Construye una web-libro ejecutable. Conserva dos páginas visibles a 1440 y 390 px, papel marfil y lomo fijo sobre mesa oscura. Cada pliego contiene una sola pieza. Usa caras HTML y una hoja de veinte segmentos que se curva en perspectiva con un muelle amortiguado, arrastre reversible, reverso, botones y flechas. Mantén el texto legible al girar. Carga Instrument Serif y Barlow desde recursos locales. Reproduce las decisiones de la receta book y verifica también el pliego 2 y el giro a mitad de recorrido.

### light

Papel marfil sobre mesa oscura. Gradiente estrecho en el lomo y sombra proyectada hacia abajo para mostrar espesor. La luz baja durante el giro según la normal de cada segmento.

### rhythm

Cada pliego es una pieza y permanece hasta una acción. Muelle con rigidez 100 y amortiguación 18, paso de tiempo acotado a 32 ms. El arrastre puede abandonarse antes de la mitad y vuelve a su origen.

### typography

Instrument Serif para titulares de 32 a 65 px y Barlow para textos de 13 a 19 px. Las líneas cortas mantienen el margen útil de cada media página.

### interaction

Veinte segmentos por hoja recorren una curva continua en X/Z con curvatura sinusoidal. Hay reverso, oclusión, botones en ambos sentidos, flechas, arrastre capturado y cancelación. En movimiento reducido el pliego cambia directamente.

### why

La doble página y el lomo estable permiten reconocer el objeto. La resistencia, la curvatura y el retorno explican el peso de la hoja sin un vídeo pregrabado.

## Verification

- Abrir en 1440×900 y 390×844. Leer las dos páginas sin desbordamiento.
- Pasar adelante y atrás con botón y teclado. Arrastrar menos y más de media página y cancelar un gesto.
- Durante el giro comprobar curvatura, reverso y sombra. Con movimiento reducido verificar el cambio inmediato.
