# Theseus's Hoard

El análisis estático Android lee manifiestos, recursos, clases y miembros DEX,
sobrecargas, código de métodos y referencias con un lector propio que utiliza
JADX libre instalado. Apktool decodifica recursos y conserva los vínculos de
cada archivo derivado. Procedimiento y límites en `docs/ANDROID-STATIC.md`.

Las declaraciones P/Invoke pueden contrastarse con funciones Ghidra guardadas,
conservando su Evidence exacta, módulos contradictorios y desconocidos. El flujo
está en `docs/MANAGED-NATIVE.md`; no demuestra un enlace o llamada en ejecución.

Las grabaciones de señales se decodifican con sigrok-cli libre instalado: ayuda
de decodificadores, pila/canales/opciones explícitos, rangos de muestras y
diagnósticos completos. Consulta `docs/SIGNAL-RECORDINGS.md`.

El lector de volcados ELF64 Linux x86_64/ARM64 conserva notas, registros,
señales y mapas; distingue memoria grabada, ausente o ambigua y candidatos de
pila. Procedimiento y límites en `docs/RECORDED-CRASHES.md`.

Las trazas nativas siguen valores entre llamadas directas con Ghidra, conservan
los enlaces de argumentos y retornos y permiten consultar la evidencia exacta
de cada nodo. El lector Apple inspecciona metadatos Objective-C y plist XML o
binarias; las firmas requieren macOS. Procedimiento y límites en
`docs/NATIVE-VALUES-APPLE.md`.

Las sesiones Ghidra conservan navegación, comentarios y marcadores; permiten
consultar grafos/caminos de llamadas, interfaces nativas y descompilar funciones
por lotes. TShark/capinfos analizan capturas PCAP/PCAPNG sin capturar tráfico en
vivo, y los recursos PE conservan los offsets originales de cada payload.
El procedimiento está en `docs/BINARY-NAVIGATION-CAPTURES.md`.

Análisis admite también directorios físicos, extracción con vínculos entre
artefactos, recuperación de JavaScript y source maps, consultas completas de
SQLite, grafos de aplicaciones .NET y móviles, importación de reconstrucciones
ligadas al hash de CIL, comparación de fuentes con su distribución e interfaces
WebAssembly tipadas. El catálogo ofrece 49 operaciones de archivos y 50 de
sesión binaria mediante las 35
herramientas MCP existentes. Los originales no se ejecutan. El procedimiento y
sus límites están en `docs/STATIC-ARTIFACTS.md`.

La pestaña Reconstrucción permite registrar obligaciones y preguntas, enlazar
hallazgos y escenarios por su nombre, congelar una especificación para el
constructor y verificar/reintentar la reconstrucción. La prueba del oráculo
ejecuta candidatos deliberadamente erróneos y conserva los defectos que detecta,
los que acepta y los intentos incompletos. API y MCP ofrecen las mismas funciones.
Estos flujos locales no llaman al modelo ni a las Sparks.

La cobertura solo describe los casos registrados; las familias pendientes del
estudio siguen abiertas en `docs/SOURCE-COVERAGE.md`. El documento del constructor
excluye los hallazgos del lector, pero el autor debe escribir una especificación
de comportamiento. No se asegura una separación automática del contenido de la
prosa. El procedimiento está en `docs/RECONSTRUCTION.md`.

Estudio local de ingeniería inversa: archivos, evidencias, especificaciones de
comportamiento y comparación con una reconstrucción. Interfaz, API y MCP comparten
los mismos proyectos y operaciones.

Guarda una pregunta, añade un archivo local o súbelo y consulta su estructura.
Admite Python, JavaScript, HAR, source maps, ZIP, ASAR de Electron, SQLite,
ejecutables PE y cadenas binarias con sus offsets. Guarda cada hallazgo con su
ubicación y separa la observación de la interpretación. La especificación sigue
siendo un documento editable.

El motor Ghidra instalado localmente permite inspeccionar funciones, pseudocódigo
y relaciones de llamadas. Conserva el proyecto nativo y permite leer una función
concreta por MCP. La descompilación no ejecuta el binario ni equivale a recuperar
el código original. Un PE con CLR se identifica, pero todavía no se recupera su
código C#; el análisis exportado cubre instrucciones nativas.

Los escenarios ejecutan dos programas locales con la misma entrada. Comparan
stdout como texto o JSON, stderr y código de retorno. Cada ejecución conserva sus
entradas, huellas y resultados; puedes cancelarla y consultar los resultados
parciales. La aplicación conserva como interrumpidos los trabajos de un arranque
anterior. Archivar un proyecto permite restaurarlo.

No exige pagos, oráculos alojados ni API externas. El copilot común utiliza
Faustus y el servicio de razonamiento configurado en las Sparks. El núcleo de
inspección y comparación funciona sin un modelo.

## Arranque

Con Python 3.11+ y HoardLink como repositorio hermano o paquete ya instalado:

```powershell
.\Install.ps1
.\Start.ps1
```

Abre `http://127.0.0.1:5217`. El arranque no descarga dependencias. Ghidra 12.1.4
y Temurin 21 se detectan en las ubicaciones locales instaladas; también puedes
indicar `THESEUS_GHIDRA_HOME` y `THESEUS_JAVA_HOME`. Cada instancia puede usar otro
directorio mediante `THESEUS_DATA_DIR`. No cambia la configuración global de Java.

La API ofrece un catálogo en `/api/agent/tools` y 35 herramientas MCP mediante
`mcp_server.py`; las operaciones normales también tienen rutas HTTP. El token de
la familia se guarda en `data/mcp-token`, sin una cuenta adicional.

Exportar produce un registro JSON del proyecto con inspecciones, hallazgos,
especificación, escenarios y recibos. Las rutas siguen apuntando a los originales:
no es un paquete que incluya todos los archivos. Las vistas previas indican su
truncación a 16 MiB; el hash identifica el archivo completo y se pueden leer otros
fragmentos. La igualdad de una comparación se refiere a los casos ejecutados.

«Exportar evidencias» conserva además los registros completos de análisis y sus
documentos JSON disponibles, con sus hashes. «Importar evidencias», en la barra
de proyectos, crea siempre un expediente nuevo y conserva el documento de origen.
Los recibos importados son históricos: no dan por verificada una reconstrucción
en el entorno actual. No incluye los originales, las bases nativas de Ghidra ni
sesiones conectadas; importar no ejecuta programas. Véase [EVIDENCE.md](docs/EVIDENCE.md).

Consulta [el README técnico](README.md) para rutas, instalación del motor,
alcance, pruebas y procedencia.
