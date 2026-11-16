# Craft library

References for designs that are not generic. Everything is read from disk and works with every module OFF.

| Tool | What it does |
| --- | --- |
| `craft_search` | `query`, `kind` (`texture`, `hero`, `scene`, `dashboard-rule`, `model-site`, `threeui`), `limit`. Cites look like `[vitruvius: craft/texture/thermal]`. |
| `craft_read` | `kind`, `id`: the full recipe (working CSS and controls, decisions, steps, or catalogue entry). |
| `craft_page` | `kind` (`texture`, `hero`, `scene`, `dashboard-rule`), `id`, optional `params`: a complete HTML document. |
| `craft_model_site` | `model`, `out_dir`, optional `views`, `section`, `section_axis`, `engine`, size and timing: the Blender script, the command and the page. |

## Textures

Ten recipes, each a class `tx-<id>` plus custom properties that are its controls: `thermal`, `blueprint`, `waves`, `graphite`, `fluted`,
`contour`, `grain`, `landscape` (with `landscape_svg(seed)`), `grass`, `softshadow`. Noise and lines come from inline SVG filters in data URIs;
nothing loads from the network. Every recipe records when to use it, when to avoid it, why it works and its accessibility note. The board
at `/craft/textures/` shows all of them with sliders; `craft_page` with `kind texture` returns a full-bleed page that uses one as its ground,
and `params` accepts the control properties (`{"--tx-cell": 24}`), `title`, `subtitle` and `seed`.

## Heroes and 3D scenes

Heroes: `typographic-wall`, `texture-field` (a live switch between materials), `index-list`. Scenes: `orbital`, `waves`, `crystal`,
on the bundled three.js module (`/showcase/assets/three.module.js`), with sliders, drag and arrow-key rotation and a reduced-motion
path; `?still` freezes a scene.

## Dashboard rules

Seven rules with a do and a check each. Five are measured by the critique rules `webcraft/dashboard-*` (type scale, one card style, actions
first, no welcome banner, command palette) on pages that look like dashboards; two are judged (a considered hover, frosted glass over a real
ground). `/craft/dashboard/index.html` is a reference dashboard that follows them.

## From a 3D model to a site

`craft_model_site` returns a self-contained Blender script: it imports a glb, gltf, obj, fbx, stl or blend file, measures the bounding box,
renders the views listed (default: two three-quarter views, one high oblique, one at eye level; the agent edits azimuth, elevation, distance
and lens) and sweeps a cutting cube along one axis to render a section-cut video, written as `<name>.png` files and `corte-de-seccion.mp4`.
Run it with `blender --background --factory-startup --python <script>` (the factory startup keeps the person's add-ons from loading). The page it returns uses a still as the hero, plays the video when it scrolls into view
and lays out the other views as a scroll gallery. The cut needs closed meshes.

## Catalogue index

`threeui_catalog.json` indexes 104 catalogue entries (163 variants) of an MIT-licensed component library: id, category, description, tags,
runtime, controls and variants. Component source and media are not included; see `craft/THIRD_PARTY.md`.

## Critique

The `webcraft` pack adds `flat-hero-surface` and the dashboard rules. `design_critique` returns `references` (textures to try when the page is one
flat colour, dashboard rules for dashboard findings, matches for the focus text).
