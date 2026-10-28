# Auditoría SEO y GEO (`site_audit`)

Auditoría determinista de un sitio: cada hallazgo sale de una medición repetible (documentos descargados, cabeceras, datos estructurados
analizados, una carga real en Chromium). Ningún modelo puntúa. Lo que una medición no puede decidir se marca con `judgement: true`,
no cambia la puntuación y va a la fase de revisión humana del plan.

Herramientas MCP: `site_audit` (ejecuta y guarda el informe) y `site_audit_reports` (lista los guardados o devuelve uno entero).
API de la interfaz: `POST /design/api/site-audit`, `GET /design/api/site-audit/reports`, `GET /design/api/site-audit/reports/{id}`.
Pantalla: Auditoría. Código: `vitruvius_hoard/seo_audit.py`; la medición de rendimiento es el trabajo `vitals` de `vitruvius_hoard/browser.py`.

## Qué se comprueba

| Categoría | Peso | Comprobaciones |
|---|---|---|
| Contenido (`content`) | 23 | texto escaso, frases largas, repetición de una palabra, contenido duplicado entre páginas, páginas huérfanas, pocos enlaces internos, señales de confianza. Juicio: E-E-A-T, intención de búsqueda, originalidad, autoría y fecha de artículos |
| SEO técnico (`technical`) | 22 | HTTPS y redirección desde http, estado de la portada, cadena de redirecciones, robots.txt (cierra el sitio o a Googlebot), mapa del sitio (existe, válido, direcciones que fallan, otro dominio, fechas), `noindex` (meta y X-Robots-Tag), canónicas, cabeceras de seguridad, enlaces rotos internos y externos, contenido mixto, compresión, caché, soft 404 |
| SEO en página (`onpage`) | 20 | título y meta descripción (falta, longitud, duplicados), H1, saltos de encabezado, `lang`, viewport, Open Graph y tarjeta social, forma de la URL, enlaces con texto genérico o sin texto, favicon |
| Datos estructurados (`schema`) | 10 | JSON-LD ilegible, `@context`, propiedades recomendadas por tipo, entidad (Organization o Person) y `sameAs`, URL distinta de la canónica, tipos con resultados enriquecidos restringidos |
| Rendimiento (`cwv`) | 10 | LCP, CLS, INP (estimación), FCP, TTFB y TBT medidos en una carga real; peso de la página y errores de JavaScript |
| Visibilidad en IA (`ai`) | 10 | política de robots.txt por rastreador (entrenamiento, búsqueda y citas, petición de una persona), `llms.txt`, contenido que solo existe tras ejecutar JavaScript, `nosnippet`, `noai`; juicio: frases citables |
| Imágenes (`images`) | 5 | `alt` ausente o con nombre de archivo, dimensiones, carga diferida, formato, peso (cabecera `content-length`), imágenes rotas |

Entrenamiento y citación son permisos distintos: bloquear a un rastreador de entrenamiento es un aviso de juicio, bloquear a uno de
búsqueda o de citas es un hallazgo `high`. La tabla completa de rastreadores va en `ai_crawlers`.

## Puntuación

Gravedad `critical|high|medium|low|info` cuesta 40, 20, 10, 4 o 0 puntos de su categoría; la misma comprobación repetida en varias páginas cuesta
como máximo el doble. Categoría = 100 menos sus costes (mínimo 0). Total = media ponderada de las categorías medidas. Una categoría que no se
pudo medir (sin navegador) tiene `score: null` y no entra en la media. Los hallazgos con `judgement: true` nunca puntúan.

Si el HTML inicial está casi vacío y lo llena JavaScript, las comprobaciones de página se hacen sobre el DOM renderizado (lo que indexa un
buscador que renderiza) y `ai.js-dependent` avisa de que quien no ejecuta scripts no ve el contenido.

El rendimiento es de laboratorio: una carga en un móvil emulado (390x844) con CPU 4 veces más lenta y red de 1,6 Mbit/s con 150 ms de latencia. No son
datos de usuarios reales. INP se estima con tres interacciones sintéticas.

## Contrato del sobre (`schema: "site-audit/1"`)

Argumentos: `{url, max_pages?, check_links?, vitals?, fresh?}`. Solo `url` es obligatorio. Un informe de la misma url con menos de 10 minutos se
reutiliza (`from_cache: true`, `age_s`) salvo `fresh: true`.

```
ok            bool. Si false: error, error_kind, hint (sin puntuación)
url, final_url, audited_at (UTC "YYYY-MM-DDTHH:MM:SSZ"), duration_s, id, from_cache, fixed_at (null)
score         entero 0-100 o null (= scores.total)
scores        {total, content, technical, onpage, schema, cwv, ai, images}  (null = no medida)
summary       {score, pages_audited, requests, counts{critical..info}, findings_total, judgement_total,
               categories_measured[], categories_unmeasured[], truncated, links_checked{internal, external, broken}}
categories    [{id, name, weight, score, measured, findings:[{id, severity, title, description, recommendation, judgement, url?, evidence?}]}]
findings      [{id, category, severity, title, judgement, url?}]   lista plana, la que lee la vigilancia
action_plan   {phases:[{phase, name, timeframe, items:[{id, category, severity, title, url?}]}]}   fases 1-3 por gravedad y 4 revisión humana
pages         [{url, status, title, words, rendered?}]
ai_crawlers   [{crawler, operator, purpose: training|search|user, allowed}]
vitals        {measured, profile, conditions, metrics{lcp_ms, cls, fcp_ms, ttfb_ms, tbt_ms, inp_ms, transfer_bytes, requests}, ratings, js_errors}
robots, sitemap, llms_txt, security_headers, citability   datos de apoyo
previous      si hay un informe anterior de la url: {id, audited_at, score, new[], fixed[], persisting}
limits        qué no cubre esta ejecución
```

Identidad de un hallazgo entre ejecuciones: `id`, estable: `<categoría>.<comprobación>` y, si es de una página, `@<ruta>`
(`onpage.title-missing@/acerca/`). Una misma comprobación que falla en dos páginas son dos ids. Ni `site_audit` ni `site_audit_reports` recortan el resultado (un informe
ocupa unos 20 a 40 KB); `site_audit_reports` con `id` devuelve el informe guardado entero.

## Vigilancia periódica (agente de Talos, #1705)

El agente llama a `site_audit` por el hub (app `vitruvius`) con `{url}` (y `fresh: true` si quiere una medición nueva), guarda `score`, `scores`
y `findings`, y calcula la deriva con la identidad de arriba (o usa `previous`). Reglas acordadas en el hilo 1861:

- ignorar `judgement: true` para la deriva de puntuación; se pueden listar aparte;
- una categoría `null` no es un empeoramiento: es una medición ausente;
- el rendimiento de laboratorio varía entre ejecuciones (decenas de puntos en LCP son normales): comparar tendencias, no una sola medida;
- una auditoría completa tarda de 10 a 90 s; no lanzarla más de una vez al día por sitio;
- si `ok: false`, registrar `error_kind` y reintentar más tarde, sin tocar la última puntuación.

## Límites

No sustituye a datos de usuarios reales (CrUX), a Search Console ni a una revisión editorial. No ejecuta el sitio con sesión iniciada, no rellena
formularios y solo lee páginas públicas (la política de red rechaza direcciones privadas salvo `VITRUVIUS_ALLOW_LOCAL_URLS=1`). El tope por
ejecución es de 40 páginas y 160 peticiones.

## Origen

La estructura de la lista (categorías, pesos, plan por fases, sobre JSON) sigue una habilidad de auditoría abierta (MIT) citada en NOTICE; las
comprobaciones son código propio.
