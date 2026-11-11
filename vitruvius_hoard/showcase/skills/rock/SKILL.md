---
name: showcase-rock
description: Anillo y basalto modelados en 3D, luz dramática y recorrido de cámara ligado al scroll. Use when reproducing the rock showcase reference.
version: 1.0.0
---

# Producto sobre roca

## Procedure

Construye un escaparate cinematográfico ejecutable de un anillo sobre basalto irregular. Modela roca, aro, engaste y gema en 3D con materiales físicos. Usa luz cálida lateral, recorte frío, reflejos de tarjetas luminosas y sombra real. Mantén la escena sticky durante 280 svh, liga cámara, pequeño giro y luz al scroll reversible. Conserva visible el producto desde la entrada y permite saltar a inicio y detalle. Sigue la receta rock y verifica entrada, mitad y final del recorrido.

### light

Un foco cálido alto a la izquierda y un recorte frío detrás. Tarjetas luminosas en un entorno PMREM producen reflejos amplios sobre el metal. El basalto usa rugosidad 0,96, grano y normales continuas.

### rhythm

Recorrido de 280 svh con escena sticky. El producto es visible desde la entrada. El scroll acerca la cámara, rota ligeramente el anillo y aumenta la intensidad del foco. Una segunda nota aparece durante el detalle.

### typography

Instrument Serif de 64 a 96 px para el nombre de producto y Barlow de 15 a 18 px para material y controles. El texto vive fuera del centro del objeto.

### interaction

Basalto deformado determinísticamente, aro toroidal, engaste y gema con materiales físicos. Scroll reversible, botones de inicio y detalle. Con movimiento reducido la cámara sigue directamente la posición sin amortiguación.

### why

La rugosidad de la roca y el brillo del metal responden de forma distinta a una misma luz. El acercamiento descubre el engaste y convierte el scroll en un examen del objeto.

## Verification

- Ver anillo completo, roca irregular, sombra y reflejo desde la entrada.
- Desplazar hasta el final y volver. Comparar showcaseState.scrollProgress y el encuadre.
- Usar Ver detalle y Volver al inicio. Comprobar móvil, movimiento reducido y fallback sin WebGL.
