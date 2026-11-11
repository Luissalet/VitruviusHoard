---
name: showcase-rock
description: Reproduce the rock showcase with explicit material, light and motion decisions.
version: 2.0.0
---

# Producto sobre roca

## Procedure

Construye la referencia ejecutable Producto sobre roca con sus recursos locales. Foco cálido lateral y recortes fríos. Tarjetas PMREM dan reflejos amplios al metal. El basalto oscuro tiene rugosidad 0,87, normal map multiescala y metalicidad 0,04. Focos verdes y azules proyectan un brillo de gema artístico sobre la piedra; no simulan cáusticas refractivas. Motas y haces sutiles dan aire. Dos anillos y dos plintos de roca en distintos planos, con un fondo de basalto fracturado. El scroll de 280 svh interpola tres fotogramas clave de cámara y objetivo mediante smoothstep. El segundo tramo viaja hasta la pieza azul y el texto entra con el encuadre. Instrument Serif de 42 a 80 px y Barlow de 12 a 16 px. La nota de material aparece sobre una zona oscura con contraste estable, junto al segundo plano. El título deja libre el objeto principal. Bloque subdividido desplazado por ruido continuo de tres escalas y crestas, normal map derivado de diferencias del ruido, aro y gema editables. Scroll reversible, inicio y detalle, progreso directo en movimiento reducido y entrada inmóvil con still. El relieve grande decide la silueta, el ruido medio rompe los planos y las normales pequeñas describen las aristas húmedas. Controlar esos tamaños por separado evita la masa blanda y el brillo metálico uniforme sobre roca. Conserva móvil, teclado, táctil, enlaces HTML, exportación y fallback. Compara el fotograma citado y tus capturas lado a lado, incluyendo sus estados interactivos.

### light

Foco cálido lateral y recortes fríos. Tarjetas PMREM dan reflejos amplios al metal. El basalto oscuro tiene rugosidad 0,87, normal map multiescala y metalicidad 0,04. Focos verdes y azules proyectan un brillo de gema artístico sobre la piedra; no simulan cáusticas refractivas. Motas y haces sutiles dan aire.

### rhythm

Dos anillos y dos plintos de roca en distintos planos, con un fondo de basalto fracturado. El scroll de 280 svh interpola tres fotogramas clave de cámara y objetivo mediante smoothstep. El segundo tramo viaja hasta la pieza azul y el texto entra con el encuadre.

### typography

Instrument Serif de 42 a 80 px y Barlow de 12 a 16 px. La nota de material aparece sobre una zona oscura con contraste estable, junto al segundo plano. El título deja libre el objeto principal.

### interaction

Bloque subdividido desplazado por ruido continuo de tres escalas y crestas, normal map derivado de diferencias del ruido, aro y gema editables. Scroll reversible, inicio y detalle, progreso directo en movimiento reducido y entrada inmóvil con still.

### why

El relieve grande decide la silueta, el ruido medio rompe los planos y las normales pequeñas describen las aristas húmedas. Controlar esos tamaños por separado evita la masa blanda y el brillo metálico uniforme sobre roca.

## Implementation

- Mantén el ruido geométrico continuo: se evalúa por posición, sin valores aleatorios por vértice que abran costuras. El bloque conserva una silueta de losa; promedia las normales de posiciones coincidentes para unir las costuras entre caras sin convertir la piedra en una esfera.
- La segunda pieza debe apoyar sobre su plinto sin quedar enterrada. Revisa inicio, mitad y final tanto en escritorio como en móvil.
- El brillo de gema se construye con focos de color localizados. Polvo, haces y desenfoque son aproximaciones ligeras declaradas; no se atribuye una simulación física completa.

## Verification

- Ver anillo completo, roca irregular, sombra y reflejo desde la entrada.
- Desplazar hasta el final y volver. Comparar showcaseState.scrollProgress y el encuadre.
- Usar Ver detalle y Volver al inicio. Comprobar móvil, movimiento reducido y fallback sin WebGL.
- Comparar lado a lado el fotograma citado y las capturas propias de 1440 y 390 px. Comprobar materia, sombra, ritmo, contraste y espacio dedicado al artefacto.
