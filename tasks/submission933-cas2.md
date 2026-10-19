# Vitruvius933 — corrección fuente CAS2

Sobre2159e826b4dbbd5b1dc891b2ee180aa9302c9454. Corrige exclusivamente el P2 de configuración nativa pedido formalmente por codex-fisiones-review933 en CAS1. La fábrica Diseño deriva ahora de Config.from_env() mediante dataclasses.replace y sustituye sólo data_dir, data_dir_configured, port, autostart y embed_auto. Conserva allow_local_urls, render_timeout_s, embed_backend/model, allowed_hosts, port_strict y cualquier otro campo nativo. Automatismos siguen determinados por el propietario (OFF inicial); no se cambia motor/modelo/SDK/Theseus.

## Regresión y evidencia

Prueba nueva tests/test_software_native_config.py parametrizada con automatismos False/True: configura valores nativos distintos a defaults, compara TODOS los campos no propios de la fusión, comprueba perfil nuevo/puerto y los cinco overrides. Fábrica explícita puede conservar identidad copilot; no abre vitruvius.db ni la ruta legacy, y no se entra en lifespan ni se inicia modelo/render.

- tasks/software933-cas2-before.xml:2FAIL esperados antes de tocar producto (port_strict=False frenteTrue, además de la misma pérdida de otros campos de CAS1). Recibo conservado.
- tasks/software933-cas2-initial.xml:tras el fix,6PASS+2FAIL por una aserción adicional demasiado estricta de MI fixture (exigía que ni existiera el directorio nuevo). La fábrica nativa sí puede crear metadatos del copilot en activación explícita; se cambió sólo esa aserción propia a ausencia de DB nativa/ruta legacy. No se tocó la prueba/oráculo externo del revisor. Recibo conservado.
- python -m pytest -q tests/test_software_native_config.py tests/test_software_workspace.py --tb=short --junitxml=tasks/software933-cas2-tests.xml:8PASS,0 errores/fallos/omisiones,10,793s XML. Incluye catálogo frío110/stdIO real, flujo proyecto/revisión/entorno/archivo+árbol/análisis resultado completo OFF, exportZIP/Range y limpieza concurrente causal.
- Prueba externa original SIN MODIFICAR D:/LocalAI/research-inbox/fusion-candidates-wave3/review933/test_review933.py ejecutada con el Python del candidato:3PASS,1,33s terminal/1,180s XML propio tasks/software933-cas2-reviewer-probe.xml. Es verificación del autor sobre el repro, no un voto/revisión independiente nuevos. Ambos cierres causales originales siguen pasando.
- Código y test nuevo diff-check PASS. No suites amplias/builds repetidos porque el delta ejecutable sólo cambia la fábrica Python.

## Assets, wheel y límites

No había wheel preparado y NO se ha iniciado empaquetado paralelo a raízWriter. Las tres builds existentes CAS1 siguen presentes e ignoradas en este WT, sin cambios por el fix Python. tasks/software933-cas2-assets.json inventaría cada archivo con tamaño/SHA256 y fingerprint de inventario:

- Diseño vitruvius_hoard/static:6archivos/562344bytes; f4b14115d7dc14deabbd236fa9cd8fd03791b539e11b9dd4ef4252b8cc496a99.
- Babel babel_client/dist:22archivos/889971bytes;2b94da91f684d12f5281b19fb6fa8aad6ccfe10ab1b10ecd50a18abd3c1ce9ef.
- Motor software_native/engine/dist:555archivos/3512860bytes;d6d8798c2d51979265b5e1ea858845fd7e05fd273cb4a80e01531efd7db04b98.

Root conserva packaging instalado/CUA/traslado/alias/938live/activación y publicación. No se copia ningún bundle, asset antiguo, datos/binarios reales o entorno ajeno. No cambios en931, SDK, perfiles/.env/tokens reales, apps/modelos/Hub ni repositorios originales. Theseus sigue incompleto/pausado y su programa RE pendiente no se ha reanudado. Inventario de migración/formatos/limitaciones de CAS1 permanece válido. Enviar estos dos commits como revisión CAS2 exacta; no cerrar933.
