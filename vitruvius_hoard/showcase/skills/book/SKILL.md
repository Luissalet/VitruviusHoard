---
name: showcase-book
description: Reproduce the book showcase with explicit material, light and motion decisions.
version: 2.0.0
---

# Libro a doble página

## Procedure

Construye la referencia ejecutable Libro a doble página con sus recursos locales. Pliegos oscuros con fotografía a sangre, sombra de contacto en el lomo y canto de hojas de 9 px. El grano se genera de forma determinista en un lienzo de 128 px. El giro modula el brillo de cada segmento entre 0,58 y 1 según su normal. Tres pliegos, cada uno con una imagen dominante y una pausa editorial. El muelle conserva rigidez 100 y amortiguación 18. El contenido del reverso es el pliego siguiente, no una cara vacía. Un arrastre corto vuelve a su origen. Instrument Serif de 30 a 64 px sobre imágenes a sangre y Barlow para lectura y folios. La fotografía ocupa la página entera; el texto se ancla a los márgenes y al pie, sin una tarjeta dentro del papel. Hoja de veinte segmentos con caras HTML impresas, curvatura y sombreado angular; arrastre reversible, cancelación, botones y flechas. Rail de navegación discreto de 44 px de altura interactiva. Movimiento reducido cambia directamente de pliego. La materia se reconoce por el canto, el grano y las sombras de contacto. La imagen a sangre y el contraste entre pliego fotográfico y pausa tipográfica producen ritmo editorial sin aumentar los controles. Conserva móvil, teclado, táctil, enlaces HTML, exportación y fallback. Compara el fotograma citado y tus capturas lado a lado, incluyendo sus estados interactivos.

### light

Pliegos oscuros con fotografía a sangre, sombra de contacto en el lomo y canto de hojas de 9 px. El grano se genera de forma determinista en un lienzo de 128 px. El giro modula el brillo de cada segmento entre 0,58 y 1 según su normal.

### rhythm

Tres pliegos, cada uno con una imagen dominante y una pausa editorial. El muelle conserva rigidez 100 y amortiguación 18. El contenido del reverso es el pliego siguiente, no una cara vacía. Un arrastre corto vuelve a su origen.

### typography

Instrument Serif de 30 a 64 px sobre imágenes a sangre y Barlow para lectura y folios. La fotografía ocupa la página entera; el texto se ancla a los márgenes y al pie, sin una tarjeta dentro del papel.

### interaction

Hoja de veinte segmentos con caras HTML impresas, curvatura y sombreado angular; arrastre reversible, cancelación, botones y flechas. Rail de navegación discreto de 44 px de altura interactiva. Movimiento reducido cambia directamente de pliego.

### why

La materia se reconoce por el canto, el grano y las sombras de contacto. La imagen a sangre y el contraste entre pliego fotográfico y pausa tipográfica producen ritmo editorial sin aumentar los controles.

## Implementation

- Cada cara se compone con .editorial; su contexto de apilamiento mantiene la imagen por encima del fondo y debajo del texto. Conserva ese contexto también en las caras segmentadas.
- Las fotografías locales de costa, cerámica y retrato tienen procedencia y hashes en assets/provenance.json. Sustituye imágenes y pies juntos.
- El grano y el canto representan papel real: no los extiendas al shell de Vitruvius. Verifica sombras, reverso impreso y lectura a 390 px.

## Verification

- Abrir en 1440×900 y 390×844. Leer las dos páginas sin desbordamiento.
- Pasar adelante y atrás con botón y teclado. Arrastrar menos y más de media página y cancelar un gesto.
- Durante el giro comprobar curvatura, reverso y sombra. Con movimiento reducido verificar el cambio inmediato.
- Comparar lado a lado el fotograma citado y las capturas propias de 1440 y 390 px. Comprobar materia, sombra, ritmo, contraste y espacio dedicado al artefacto.
