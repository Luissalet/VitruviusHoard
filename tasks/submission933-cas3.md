# Vitruvius933 — paquete propio CAS3

CAS2 fuente1689aef307b567b6d18be33e3bc99626488e3ac7 permanece aprobado independiente sobre2159e826b4dbbd5b1dc891b2ee180aa9302c9454. Este envío añade únicamente correcciones necesarias para distribuir y probar el paquete instalado. No se cambia SDK ni capacidades/pendientes de Theseus.

## Delta

- setuptools incluye explícitamente mcp_server.py; packages.find por sí solo lo omitía. MCP instalado se ejecuta con python -m mcp_server, sin arrancar el host.
- La plantilla nativa de proyectos lee una licencia poseída por vitruvius_hoard, incluida mediante package-data. La prueba instalada descubrió que la antigua ruta ROOT/LICENSE sólo existía en el checkout y rompía app_project_create fuera de él. El aviso MIT es idéntico al de raíz.
- Un paquete instalado usa LOCALAPPDATA/VitruviusHoard/data (o ~/.local/share/VitruviusHoard/data). VITRUVIUS_PROFILE_DIR y --data-dir tienen prioridad; un checkout conserva su data/ existente. El lanzador y el host comparten la misma función de perfil. No se crea/mueve ningún perfil real.
- /build/ ignorado; verificador reproducible scripts/check-installed-software.py con Python -I exige cwd/TARGET externos al checkout y perfil nuevo. Comprueba imports, recursos exactos, catálogo frío, nativos reales y cierre. No se añaden workers automáticos ni servidores antiguos.

## Wheel y recursos

Wheel ignorado dist/vitruvius_hoard-0.1.0-py3-none-any.whl,5535423bytes, SHA256 bd3790f5fa4133b4efae39478db53eb47c144869c11b067de8009e2835a439a1.1574miembros;1568 recursos/fuentes coinciden byte a byte con el WT que se entrega. Inventario completo canónico de miembros:9413e736c5fefa06aa85385e7a90416567902d164a75f99228a08af8027eaa40. Sin data/.env/node_modules/caches/DBs ni secretos/perfiles. Licencias nativas/SDK/motor y package.json/package-lock del motor en sus rutas propias; no package.json mal ubicado. Motor Node conserva555JS compilados, fuentes/bridges/metadatos. Node22.19+ y sus dependencias propias se instalan con npm ci en el software_native/engine instalado; no se distribuye/enlaza node_modules.

Las builds reales existentes CAS1 siguen idénticas al inventario tasks/software933-cas2-assets.json: Diseño6archivos/562344B, Babel22/889971B, motor555/3512860B. El wheel contiene cada archivo con el mismo tamaño/SHA; no son fixtures HTML. El bootstrap Vite real es pequeño y referencia JS344000/311330B y CSS41468/45103B; Theseus sirve app.js95476B/CSS12607B. Se comprueban también los tres lanzadores Faustus y el tema nativo; GET devuelve los tipos correctos, sin HTML de sustitución.

## Verificación instalada

Directorio QA D:/LocalAI/research-inbox/fusion-candidates-wave3/vitruvius933-installed; TARGET final target-cas3-b, perfil nuevo profile-cas3-final. pip install --no-deps --target instala el wheel propio; npm ci --omit=dev instala34dependencias propias para la operación JavaScript ejercitada. Python del venv propio con -I ejecuta scripts/check-installed-software.py desde QA externo, nunca añade el WT al import path. vitruvius_hoard, babels_hoard, theseus, hoard_link, software_native, babel_client y mcp_server provienen exclusivamente del TARGET. Las dependencias Python pertenecen al venv propio, sin editable del producto.

- Catálogo110 sin fábricas nativas/stores/hilos/perfil; tres módulos y automatismosOFF al crear el propietario. Perfil por defecto instalado se comprueba con LOCALAPPDATA sintético sin crearlo.
- Los tres módulosON y tres UI con JS/CSS reales. Límite Theseus pausado visible. HTTP ASGI en memoria; conexiones TCP/listeners bloqueados salvo socketpair privado de asyncio. No servicios personales/proveedores/modelos/GPU. El Node hijo lee sólo la fuente sintética y no ejecuta el objetivo.
- Proyecto nativo editable→revisión→entorno Babel explícito→check real con SHAarchivo→artefacto de árbol Theseus real→javascript.application real Node→job finished→resultado íntegro retenido con SHA. ID proyecto b118c8d82741472b; entorno env-f7459d4f0b48; job6ceaba5c926e4a28bb33776be4fc1c7d. Hash JSON de fuentes y hash nativo de árbol distintos y conservados.
- Edición posterior no relabela las cinco referencias históricas. OFF conserva lectura; ON reabre el proyecto/revisión y job por sus mismos IDs; el cierre final deja los tres ownersOFF/appNone. No procesos propios de preview abiertos.
- MCP stdio real desde el mcp_server instalado, otro perfil frío: initialize/list_tools110 y nombres exactos; ese perfil no se crea.
- tests/test_software_package.py y test_software_native_config.py:6PASS,0fallos/errores/skips,0,133s XML tasks/software933-package-tests.xml. No se repiten suites amplias ya aprobadas sin motivo. Diff-check PASS.

Recibo compacto versionado tasks/software933-installed-cas3.json. Recibo completo externo installed-cas3.json SHA256 bbd0df957d08304563e75bc06400f48e2479ac0bc34aa8279233e9069d3c5941, con inventario de1574miembros, fuentes importadas, recursos servidos y todos los IDs/SHA. Log installed-cas3.log. Build log propio ignorado tasks/software933-wheel-build.log. El verificador acepta --target/--wheel/--profile/--assets/--output absolutos; --assets apunta al inventario exacto y cada nueva ejecución exige perfil nuevo.

## Recibos adversos conservados y límites

El primer wheel omitía mcp_server.py (SHA a37718cd29488dec9d9f9b3eff63bbd136d633cb94144edd6ab4b37985a31dba). Dos fallos de MI verificador se conservan como installed-cas3-record-fixture.json/log y installed-cas3-html-fixture.json/log: pip modifica legítimamente RECORD, y el HTML Vite real no tiene por qué superar1KB. Se corrigió sólo el oráculo propio: exceptuar RECORD de comparación instalada manteniendo su inventario del wheel; comprobar bootstrap>500B y las builds/JS/CSS exactas, en vez del umbral1KB. No se alteró prueba externa alguna. installed-cas3-license-missing.json/log conserva el fallo real de producto corregido de plantilla/licencia. Targets/perfiles sintéticos iniciales permanecen inventariados, sin borrados recursivos ni reinterpretar sus FAIL como PASS.

Theseus sigue incompleto/pausado por Luis; no se reanuda RE ni se añaden formatos. No acredita CUA, todos los motores/formatos, render/LLM real938, Ghidra/JDK/Frida, datos reales, migración de rutas/aliases934, instalación personal/activación o publicación. Ghidra/JDK y raíces de proyectos reales no se copian ni enlazan. Inventario de migración vigente; ningún dato/binario/.env/token/perfil real,931, repositorio original, app/Hub/modelo ha cambiado. No integración/push. Solicitar revisión independiente CAS3 de los tres commits exactos, manteniendo CAS2 como hito fuente.
