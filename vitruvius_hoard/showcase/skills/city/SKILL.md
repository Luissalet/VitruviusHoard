---
name: showcase-city
description: Mapa urbano 3D con edificios instanciados, ventanas iluminadas, destinos y una pieza roja destacada. Use when reproducing the city showcase reference.
version: 1.0.0
---

# Ciudad como mapa

## Procedure

Construye una ciudad 3D azul vista desde arriba como mapa navegable, con edificios de altura determinista, ventanas cálidas, calles y una pieza escultórica roja destacada. Usa geometría instanciada, niebla y sombras. Incluye zoom, giro y tres destinos con posición, ficha y enlace reales. La selección mueve la cámara y se ofrece por raycast y HTML. Sigue la receta city y comprueba mapa inicial, giro de 45 grados y destino rojo.

### light

Luz azul fría, niebla exponencial de densidad 0,013 y ventanas cálidas. La pieza roja tiene el contraste cromático máximo. Una luz direccional proyecta las sombras.

### rhythm

Vista cenital oblicua al entrar. Acercar y girar son acciones expresas. Elegir un destino desplaza el punto de mira con continuidad y abre su ficha.

### typography

Instrument Serif para el nombre del atlas y Barlow para destinos y controles. Los nombres permanecen en HTML, legibles sobre la ciudad.

### interaction

Edificios y ventanas usan InstancedMesh. Rueda y botones regulan zoom entre 0,55 y 1,6. Girar añade 45 grados. Tres plintos y la pieza roja responden a raycast, y los destinos HTML dirigen cámara y detalle.

### why

La ciudad funciona como orientación espacial. Las ventanas dan escala y la anomalía roja convierte un proyecto en destino reconocible sin introducir muchos colores.

## Verification

- Abrir dos veces y comprobar la misma disposición urbana.
- Acercar, alejar, girar y elegir los tres destinos. Verificar zoom y destination en showcaseState.
- Seleccionar la pieza roja y abrir Materia. Revisar móvil y movimiento reducido.
