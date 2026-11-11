---
name: showcase-city
description: Reproduce the city showcase with explicit material, light and motion decisions.
version: 2.0.0
---

# Ciudad como mapa

## Procedure

Construye la referencia ejecutable Ciudad como mapa con sus recursos locales. Noche azul con niebla exponencial 0,024, luz direccional fría y ventanas emisivas variables en cuatro fachadas. La pieza roja emite y tiene una luz puntual roja con caída física que tiñe edificios cercanos. Suelo rugoso con respuesta especular y estelas con reflejo aproximado. Órbita lenta de 0,009 rad/s cuando hay movimiento permitido. Zoom y giro amortiguados con exp(-4·dt); travelling a los destinos con exp(-8·dt). La niebla separa las alturas y el postproceso añade bloom contenido y desenfoque leve según profundidad. Instrument Serif de 38 a 54 px para el atlas, Barlow pequeño para destinos y rail. Texto en HTML con una zona superior despejada; el rojo sigue siendo la anomalía visual principal. Edificios, cornisas, pilares, coronas y ventanas instanciados. Alturas, siluetas y ventanas deterministas con variación. Zoom entre 0,55 y 1,6, giro de 45 grados, raycast y enlaces a destinos con travelling. Sin órbita, estelas móviles ni paralaje con movimiento reducido o still. La escala nace de la densidad de fachadas, de la luz en calles profundas y de ventanas con ocupación desigual. La emisión roja debe iluminar su entorno, no limitarse a un color pintado. Las líneas de rejilla sobre edificios se han eliminado. Conserva móvil, teclado, táctil, enlaces HTML, exportación y fallback. Compara el fotograma citado y tus capturas lado a lado, incluyendo sus estados interactivos.

### light

Noche azul con niebla exponencial 0,024, luz direccional fría y ventanas emisivas variables en cuatro fachadas. La pieza roja emite y tiene una luz puntual roja con caída física que tiñe edificios cercanos. Suelo rugoso con respuesta especular y estelas con reflejo aproximado.

### rhythm

Órbita lenta de 0,009 rad/s cuando hay movimiento permitido. Zoom y giro amortiguados con exp(-4·dt); travelling a los destinos con exp(-8·dt). La niebla separa las alturas y el postproceso añade bloom contenido y desenfoque leve según profundidad.

### typography

Instrument Serif de 38 a 54 px para el atlas, Barlow pequeño para destinos y rail. Texto en HTML con una zona superior despejada; el rojo sigue siendo la anomalía visual principal.

### interaction

Edificios, cornisas, pilares, coronas y ventanas instanciados. Alturas, siluetas y ventanas deterministas con variación. Zoom entre 0,55 y 1,6, giro de 45 grados, raycast y enlaces a destinos con travelling. Sin órbita, estelas móviles ni paralaje con movimiento reducido o still.

### why

La escala nace de la densidad de fachadas, de la luz en calles profundas y de ventanas con ocupación desigual. La emisión roja debe iluminar su entorno, no limitarse a un color pintado. Las líneas de rejilla sobre edificios se han eliminado.

## Implementation

- La ciudad ocupa una malla de coordenadas -8…8 con avenidas reservadas. InstancedMesh agrupa cuerpos y detalles de fachada, y otro grupo agrupa ventanas. Las juntas y la variación del hormigón se sombrean en el material por posición de fachada, sin una rejilla superpuesta al mundo.
- El postproceso usa un render target con textura de profundidad: curva fílmica, bloom de doce muestras y desenfoque suave. Es una aproximación ligera, no profundidad de campo óptica ni un compositor de cine completo.
- Las estelas se dibujan sobre el asfalto, con proyecciones tenues en el suelo. El rojo usa material emisivo más PointLight; comprueba el tinte en fachadas vecinas.

## Verification

- Abrir dos veces y comprobar la misma disposición urbana.
- Acercar, alejar, girar y elegir los tres destinos. Verificar zoom y destination en showcaseState.
- Seleccionar la pieza roja y abrir Materia. Revisar móvil y movimiento reducido.
- Comparar lado a lado el fotograma citado y las capturas propias de 1440 y 390 px. Comprobar materia, sombra, ritmo, contraste y espacio dedicado al artefacto.
