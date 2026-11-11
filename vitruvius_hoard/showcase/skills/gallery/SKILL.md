---
name: showcase-gallery
description: Reproduce the gallery showcase with explicit material, light and motion decisions.
version: 2.0.0
---

# Sala-galería 3D

## Procedure

Construye la referencia ejecutable Sala-galería 3D con sus recursos locales. Sala gris verdosa con focos de caída por distancia, penumbra y sombras reales. Paredes y suelo usan grano de material. Haces aditivos de opacidad baja sugieren polvo en el aire. Reflejos de las obras desenfocados y desvanecidos sobre el suelo: proyección gráfica aproximada, no reflexión por trazado de rayos. Ocho obras de demostración en fuga: tres al frente y cinco en profundidad. Marcos de 0,34 unidades con frente de imagen. El movimiento del puntero introduce paralaje; el hover eleva suavemente la obra. Seleccionar desplaza cámara y abre detalle. Títulos de Instrument Serif y pies de Barlow impresos sobre fotografías reales con un degradado de lectura. El nombre de la sala es pequeño y queda en la esquina superior, por fuera de las obras. Rueda, W/S, flechas, botones y gesto táctil recorren diez unidades. Raycast y enlaces HTML comparten el travelling al proyecto. Movimiento reducido resuelve destinos y hover sin interpolación y desactiva el paralaje de puntero. Los marcos gruesos, la repetición en fuga, los haces y los reflejos relacionan cada imagen con el espacio. La sala se percibe como un recorrido continuo, mientras el rail discreto conserva los accesos equivalentes. Conserva móvil, teclado, táctil, enlaces HTML, exportación y fallback. Compara el fotograma citado y tus capturas lado a lado, incluyendo sus estados interactivos.

### light

Sala gris verdosa con focos de caída por distancia, penumbra y sombras reales. Paredes y suelo usan grano de material. Haces aditivos de opacidad baja sugieren polvo en el aire. Reflejos de las obras desenfocados y desvanecidos sobre el suelo: proyección gráfica aproximada, no reflexión por trazado de rayos.

### rhythm

Ocho obras de demostración en fuga: tres al frente y cinco en profundidad. Marcos de 0,34 unidades con frente de imagen. El movimiento del puntero introduce paralaje; el hover eleva suavemente la obra. Seleccionar desplaza cámara y abre detalle.

### typography

Títulos de Instrument Serif y pies de Barlow impresos sobre fotografías reales con un degradado de lectura. El nombre de la sala es pequeño y queda en la esquina superior, por fuera de las obras.

### interaction

Rueda, W/S, flechas, botones y gesto táctil recorren diez unidades. Raycast y enlaces HTML comparten el travelling al proyecto. Movimiento reducido resuelve destinos y hover sin interpolación y desactiva el paralaje de puntero.

### why

Los marcos gruesos, la repetición en fuga, los haces y los reflejos relacionan cada imagen con el espacio. La sala se percibe como un recorrido continuo, mientras el rail discreto conserva los accesos equivalentes.

## Implementation

- Ocho paneles reutilizan tres proyectos de demostración; no son ocho proyectos reales. Fotografías locales con licencia y procedencia en assets/provenance.json.
- Los reflejos son texturas propias de las obras, desenfocadas a 400×280, invertidas y desvanecidas. Mantén su opacidad baja para que no parezcan pósteres en el suelo.
- El hover levanta 0,12 unidades y la selección fija el travelling en cuatro unidades. Conserva los límites para no atravesar los paneles.

## Verification

- Entrar y observar los tres paneles, sus sombras y las juntas del suelo.
- Avanzar con botón, rueda, W y gesto táctil. Retroceder y volver a la entrada.
- Seleccionar un panel mediante raycast y por enlace, cerrar detalle y abrir su proyecto.
- Comparar lado a lado el fotograma citado y las capturas propias de 1440 y 390 px. Comprobar materia, sombra, ritmo, contraste y espacio dedicado al artefacto.
