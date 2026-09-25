# Vitruvius's Hoard

*Firmeza, utilidad, belleza — para interfaces.*

Un taller de diseño de interfaces local, para el asistente (el entorno Faustus) y para la persona que lo usa: el
"sentido del diseño" que le falta a un modelo de código en bruto. Cuatro núcleos, una sola app:

- una **biblioteca de criterio** ingerida desde repositorios abiertos de skills de diseño (reglas, estilos,
  paletas, combinaciones tipográficas, recetas de motion), buscable con citas;
- un **ciclo de render → captura → crítica** sobre Chromium real: renderiza HTML o una URL, la captura a varios
  anchos, ejecuta 29 comprobaciones deterministas de lint de diseño y, opcionalmente, obtiene una crítica de un
  modelo de visión;
- un **generador de sistemas de diseño**: rampas de color OKLCH en Python puro, una escala tipográfica fluida,
  tokens de espaciado/radio/sombra/motion, exportados como variables CSS, un tema de Tailwind v4, JSON de design
  tokens W3C y un JSON plano, más una página de playground autocontenida y en vivo;
- una **galería de referencias**: captura una web con sus capturas de escritorio y móvil, un vídeo de scroll, sus
  fuentes, paleta y librerías de animación, y búscalas después por etiqueta, vibe o librería.

Todo lo anterior se expone tanto como una pequeña API REST (para su propia interfaz) como 25 herramientas MCP
(para el asistente), construidas desde el *mismo* código, para que nunca puedan discrepar.

## Por qué

Los modelos de código son fluidos escribiendo código pero por defecto caen en el mismo puñado de páginas
genéricas: Inter sobre blanco, un botón con degradado morado a azul, una sección hero seguida de tres tarjetas.
Vitruvius's Hoard le da a un asistente un sitio donde consultar criterio de diseño real (con cita, no con una
suposición), una forma de *ver* de verdad lo que construyó (render + captura, no solo markup) y una forma
determinista de señalar los patrones genéricos delatores antes de que una persona tenga que decir "esto parece
hecho por una IA".

## Funcionalidades

- **Biblioteca**: búsqueda de texto completo (SQLite FTS5, ranking `bm25`) sobre los repositorios de skills
  ingeridos, con un rerank vectorial opcional una vez existen embeddings. Cada resultado lleva una cita
  `[vitruvius: fuente/ruta § encabezado]`.
- **Búsqueda por significado, en cualquier idioma**: un modelo de frases multilingüe (ONNX con fastembed, CPU, ~120 MB,
  reutilizado de la caché de una app hermana si ya está) calcula un vector por fragmento, indexado por el hash del
  texto para que reingerir solo calcule lo que cambió; `design_search` fusiona palabras y significado por rango
  recíproco, así que «¿cómo hago que los botones parezcan pulsables?» encuentra criterio escrito en inglés. Cada
  resultado dice cómo se encontró (`bm25`, `dense`, `both`).
- **Briefs de diseño**: una composición determinista de 2-3 estilos que encajan, una paleta, una combinación
  tipográfica, reglas por área y una checklist previa a la entrega — todo citado, con un párrafo opcional de
  dirección de arte de 150 palabras generado por un modelo local.
- **Render y captura**: un único worker de Chromium en segundo plano (Playwright), capturas a cualquier ancho, un
  vídeo opcional de scroll de 6 segundos (convertido a MP4 con ffmpeg si está en el `PATH`), y una sonda en la
  propia página (fuentes, colores calculados, encabezados, pares de contraste, tamaño de zonas táctiles, número
  de animaciones, librerías externas).
- **Lint de diseño**: 29 comprobaciones deterministas (tipografía, contraste, layout, motion, accesibilidad,
  contenido, rendimiento, y varios detectores de "paleta genérica de IA") con id estable, severidad, evidencia y
  una corrección concreta por hallazgo.
- **Crítica**: los hallazgos del lint combinados con una rúbrica opcional de modelo de visión (jerarquía,
  tipografía, color, espaciado, motion, distintividad, accesibilidad, copy), puntuada de 0 a 10.
- **Design tokens**: rampas OKLCH (50-950), colores semánticos, superficies claro/oscuro, escala tipográfica
  fluida, espaciado, radio, sombras y tokens de motion (duraciones, easings, un knob de intensidad de motion),
  exportados de cuatro formas.
- **Galería de referencias**: captura cualquier URL o HTML en bruto, extrae su paleta (cuantización con Pillow),
  las librerías de animación detectadas y sus características de motion, y búscalas después.
- **MCP + REST**: 25 herramientas detrás de un único puente protegido por token, más las rutas REST idénticas que
  usa la interfaz incluida (ver `docs/API.md`).

## Instalación

### Requisitos

- Python 3.11+ (objetivo en Windows: 3.13)
- Node.js 22+ (solo para compilar el cliente)
- `git` en el `PATH` (para ingerir fuentes)
- `ffmpeg` en el `PATH` (opcional, para vídeos MP4 — si no está, se conserva el WebM)
- Un Chromium accesible por Playwright: ejecuta `python -m playwright install chromium` una vez, o ten Edge/Chrome
  instalado (el worker de render recurre a `channel="msedge"` / `channel="chrome"`)

### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
npm install
npm run build
python -m vitruvius_hoard
```

### Windows

```powershell
py -3.13 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
npm install
npm run build
python -m vitruvius_hoard
```

La app escribe sus datos en `data/` junto a este repositorio (se puede cambiar con `VITRUVIUS_DATA_DIR`), elige
un puerto libre a partir del `5191` (cámbialo con `VITRUVIUS_PORT`, o fija `PORT_STRICT=1` para exigir ese puerto
exacto), y escribe `data/mcp-token` y `data/url` al arrancar.

## Configuración MCP

Apunta tu asistente compatible con MCP a `mcp_server.py` con el mismo intérprete de Python de arriba. El
`faustus-plugin.json` incluido es el manifiesto que lee el entorno Faustus para conectarlo automáticamente (id
`vitruvius`, comprobación de salud en `/api/health`, puente MCP por stdio). Para una entrada manual en
`mcp.json`:

```json
{
  "mcpServers": {
    "vitruvius-hoard": {
      "command": "/ruta/al/venv/bin/python",
      "args": ["/ruta/a/vitruvius/mcp_server.py"],
      "env": { "VITRUVIUS_URL": "http://127.0.0.1:5191" }
    }
  }
}
```

El puente nunca abre la base de datos por sí mismo: reenvía cada llamada a `POST /api/agent/call` en la app en
ejecución (arrancándola automáticamente si no lo está) usando el token del portador en `data/mcp-token`.

## Herramientas

| Herramienta | Solo lectura | Qué hace |
| --- | --- | --- |
| `design_search` | sí | Busca en la biblioteca de diseño: reglas, skills, estilos, recetas de motion con citas. |
| `design_brief` | sí | Brief de diseño para una página/app: estilo, paleta, tipografías, reglas, motion, anti-patrones. |
| `design_rules` | sí | Lista reglas de diseño por área (tipografía, color, layout, motion, a11y, formularios). |
| `styles_search` | sí | Encuentra estilos de UI (glass, brutalist, swiss, aurora…) con tokens y cuándo usarlos. |
| `palettes_search` | sí | Encuentra paletas de color catalogadas por nombre o tipo de producto. |
| `fonts_search` | sí | Encuentra combinaciones tipográficas catalogadas por mood o consulta. |
| `render_preview` | no | Renderiza HTML o una URL en Chromium, captura a varios anchos, ejecuta el lint. |
| `design_lint` | sí | Comprobaciones deterministas de diseño sobre HTML/URL (tipografía, contraste, motion, a11y, patrones genéricos de IA). |
| `design_critique` | no | Critica una página renderizada: puntuación 0-10, hallazgos con arreglos, usando lint + modelo de visión local. |
| `page_assay` | sí | Comprobación funcional de una página generada en un navegador real: ¿funciona cada control? Ejecuta [assay](https://github.com/awss1i/assay) (`pip install assay-ui`), sin tests escritos ni modelo. |
| `render_compare` | sí | Diferencia de píxeles entre dos renders a un ancho dado: porcentaje cambiado + imagen de diferencia. |
| `tokens_generate` | no | Genera un sistema de diseño: paletas OKLCH, escala tipográfica, espaciado, tokens de motion. |
| `tokens_get` | sí | Obtiene un sistema de diseño generado en formato json, css, tailwind o w3c. |
| `tokens_list` | sí | Lista los sistemas de diseño generados. |
| `tokens_preview` | no | Renderiza el playground en vivo del sistema de diseño y lo audita. |
| `tokens_delete` | no (destructiva) | Elimina un sistema de diseño generado (solo cuando el usuario lo pide). |
| `reference_add` | no | Captura una web en la galería de referencias: capturas, vídeo, tipografías, paleta. |
| `reference_search` | sí | Busca en la galería de referencias por texto, etiquetas, vibe o librería. |
| `reference_get` | sí | Obtiene el detalle completo de una referencia (archivos, paleta, tipografías, motion, análisis). |
| `reference_delete` | no (destructiva) | Elimina una referencia de la galería (solo cuando el usuario lo pide). |
| `sources_list` | sí | Lista cada fuente de criterio de diseño ingerida y su estado. |
| `source_add` | no | Añade una nueva fuente a ingerir: un repo git, una carpeta local o una URL de una sola página. |
| `source_ingest` | no | Ingiere (o reingiere) una fuente o todas; se ejecuta en segundo plano. |
| `source_status` | sí | Estado de la ingesta de una fuente (idle, cloning, ingesting, ready, error). |
| `vitruvius_status` | sí | Salud: navegador, ffmpeg, git, contadores de la biblioteca, resolución de modelos para visión/chat/embeddings. |

Al asistente se le indica, en `AGENT_INSTRUCTIONS`, que cite la biblioteca con `[vitruvius: ...]`, que itere con
`render_preview` → `design_critique` → arreglar → renderizar de nuevo (parando en puntuación ≥ 8 o tras 3
rondas), y que solo llame a las herramientas que cambian algo (`reference_add`, `source_add`, `source_ingest`,
`tokens_delete`, `reference_delete`) cuando el usuario lo pida explícitamente.

## Fuentes con las que viene

`vitruvius_hoard/seeds.json` lista los repositorios que la biblioteca ingiere la primera vez («Ingerir todo» en la
interfaz o `python scripts/ingest.py --all`). Cada uno se clona superficialmente en `data/sources/<id>`; solo se
indexan el Markdown/CSV/JSON de las rutas listadas, y cada resultado de búsqueda cita su fuente. El mérito del
criterio es de sus autores: esta app solo lo indexa en local. Añade las tuyas con `source_add` (URL git o carpeta).

| id | repositorio | licencia | categoría |
|---|---|---|---|
| `impeccable` | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | Apache-2.0 | criterion |
| `anti-slop` | [miqdadbadjuber/anti-slop](https://github.com/miqdadbadjuber/anti-slop) | MIT | rules |
| `hallmark` | [Nutlope/hallmark](https://github.com/Nutlope/hallmark) | MIT | criterion |
| `superdesign-skill` | [superdesigndev/superdesign-skill](https://github.com/superdesigndev/superdesign-skill) | MIT | criterion |
| `anthropic-frontend-design` | [anthropics/skills](https://github.com/anthropics/skills) | Apache-2.0 | criterion |
| `vercel-web-interface-guidelines` | [vercel-labs/web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines) | MIT | rules |
| `ui-ux-pro-max` | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | MIT | catalog |
| `taste-skill` | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | MIT | criterion |
| `aesthetic-anchors` | [Ilm-Alan/frontend-design](https://github.com/Ilm-Alan/frontend-design) | MIT | criterion |
| `frontend-design-pro-demo` | [claudekit/frontend-design-pro-demo](https://github.com/claudekit/frontend-design-pro-demo) | MIT | reference |
| `distinctive-frontend` | [Koomook/claude-frontend-skills](https://github.com/Koomook/claude-frontend-skills) | MIT | criterion |
| `design-motion-principles` | [kylezantos/design-motion-principles](https://github.com/kylezantos/design-motion-principles) | MIT | motion |
| `emil-skills` | [emilkowalski/skills](https://github.com/emilkowalski/skills) | MIT | motion |
| `claude-design-skillstack` | [freshtechbro/claudedesignskills](https://github.com/freshtechbro/claudedesignskills) | MIT | motion |
| `bang-motion` | [bangtutorial/bang-motion](https://github.com/bangtutorial/bang-motion) | MIT | motion |
| `hyperframes` | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) | Apache-2.0 | motion |
| `nullmotion` | [blixvip/NullMotion](https://github.com/blixvip/NullMotion) | sin declarar (marcada en la UI) | motion |
| `web-quality-skills` | [addyosmani/web-quality-skills](https://github.com/addyosmani/web-quality-skills) | MIT | rules |
| `designer-skills` | [Owl-Listener/designer-skills](https://github.com/Owl-Listener/designer-skills) | MIT | criterion |
| `awesome-web-animation` | [sergey-pimenov/awesome-web-animation](https://github.com/sergey-pimenov/awesome-web-animation) | CC0-1.0 | index |
| `motion-ui-design` | [fliptheweb/motion-ui-design](https://github.com/fliptheweb/motion-ui-design) | sin declarar (marcada en la UI) | index |
| `frontend-design-toolkit` | [wilwaldon/Claude-Code-Frontend-Design-Toolkit](https://github.com/wilwaldon/Claude-Code-Frontend-Design-Toolkit) | sin declarar (marcada en la UI) | index |

Las galerías tipo Godly, Lapa Ninja, Curated Design, Minimal Gallery o Siteinspire **no** se rastrean: pega la URL
de una página que te guste en la Galería (o `reference_add`) y Vitruvius captura esa página por su cuenta.

## Capturas

| Biblioteca | Crítica |
|---|---|
| ![Library](docs/screenshots/library.png) | ![Critique](docs/screenshots/critique.png) |

| Design system | Galería |
|---|---|
| ![Design system](docs/screenshots/tokens.png) | ![Gallery](docs/screenshots/gallery.png) |

## Licencia

MIT — ver `LICENSE`.
