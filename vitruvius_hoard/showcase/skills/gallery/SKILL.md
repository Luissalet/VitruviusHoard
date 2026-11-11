---
name: showcase-gallery
description: Una sala real en WebGL con suelo, luces, paneles seleccionables y desplazamiento de cámara. Use when reproducing the gallery showcase reference.
version: 1.0.0
---

# Sala-galería 3D

## Procedure

Construye una sala-galería WebGL ejecutable con tres paneles de proyectos, suelo con juntas, focos dirigidos, sombras y profundidad real. Permite caminar con rueda, W/S, flechas, controles y gesto táctil dentro de límites. Cada panel se selecciona por raycasting y muestra un detalle con enlace funcional. Usa también enlaces HTML equivalentes. Sigue posiciones, luz, tipografía local y encuadres de la receta gallery. Verifica entrada, cámara avanzada y selección.

### light

Sala gris verdosa con focos cálidos dirigidos a cada panel y luz hemisférica suave. Suelo con rugosidad 0,3 y juntas oscuras que hacen legible la profundidad.

### rhythm

Tres obras visibles al entrar, un paso de dos unidades por botón y un recorrido máximo de diez. El acercamiento conserva la continuidad espacial.

### typography

Los títulos y subtítulos viven dentro de las texturas de los paneles. Instrument Serif y Barlow se cargan antes de dibujarlos. El rótulo de sala deja libre la zona central.

### interaction

Perspectiva real, cámara que camina con rueda, botones, W/S y flechas verticales. Deslizamiento táctil. Raycaster selecciona un panel y enlaces HTML ofrecen los mismos proyectos.

### why

Los marcos y sus sombras pertenecen al espacio. La cámara se mueve entre ellos y permite reconocer distancias, mientras los enlaces conservan acceso directo a cada pieza.

## Verification

- Entrar y observar los tres paneles, sus sombras y las juntas del suelo.
- Avanzar con botón, rueda, W y gesto táctil. Retroceder y volver a la entrada.
- Seleccionar un panel mediante raycast y por enlace, cerrar detalle y abrir su proyecto.
