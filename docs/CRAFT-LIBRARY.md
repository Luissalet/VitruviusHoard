# Craft library

References for designs that are not generic. Everything is read from disk and works with every module OFF.

| Tool | What it does |
| --- | --- |
| `craft_search` | `query`, `kind` (`texture`, `hero`, `scene`, `dashboard-rule`, `model-site`, `threeui`, `ui-set`, `ui-control`), `limit`. Cites look like `[vitruvius: craft/texture/thermal]`. |
| `craft_read` | `kind`, `id`: the full recipe (working CSS and controls, decisions, steps, or catalogue entry). |
| `craft_page` | `kind` (`texture`, `hero`, `scene`, `dashboard-rule`, `ui-set`, `ui-control`), `id`, optional `params`: a complete HTML document. |
| `ui_set_install` | `set`, `out_dir`, optional `controls`: copies the controls of a bundled style set and its licence into `out_dir/<set>/` and returns the script tags and markup to paste. |
| `ui_set_fetch` | `set`, `effect`, `out_dir`: downloads one effect of the on-demand pack and writes its credit line beside it. |
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

## Control style sets

Ordinary controls that look and react in a distinct way, for a page whose style is a decision (a game site, an anime or cartoon brand, a playful tool).
Each control is one plain script that registers a custom element, with its drawings inside it: no dependencies and no build step. Load it with a script
tag (not as a module), then use the element. The scripts ship unchanged with the licence of each set.

| Set | Controls | Look | Elements |
| --- | --- | --- | --- |
| Sakuga VFX | 11 | anime | sakuga-button, sakuga-toggle, sakuga-slider, sakuga-checkbox… |
| Rubber Hose UI | 11 | dibujos animados de 1930 | hose-button, hose-toggle, hose-slider, hose-checkbox… |
| Pixel Worlds | 6 | pixel art | sage-status, hoard-button, raven-send, round-bar… |

`craft_search` with `kind ui-set` finds the style; `kind ui-control` finds the control (`set/control`, for example `sakuga-vfx/slider`). `craft_read` returns what the
control is for, when to avoid it, its markup and its preview. `craft_page` with `kind ui-control` returns a complete page with the script inline and, for
progress bars and toasts, a driver that shows the reaction; with `kind ui-set` it returns the board of the set. `ui_set_install` copies the files into the project.
Reference pages: `/craft/ui-sets/`, `/craft/ui-sets/{set}/index.html`, `/craft/ui-sets/{set}/{control}/index.html`; the scripts are served beside them.

Each control keeps its own behaviour (real focusable element inside, keys, form value), and `design_critique` measures it with the interaction rules: a control
that takes focus without a visible change is reported (`interaction/focus-ring-missing`), and a catalogue entry carries the accessibility note when its look
needs a focus style added by the page.

### The effects pack that needs a credit

`kanaworks-sakuga-vfx` is a library of anime-style game effects (fire, water, thunder, wind, poison, ice, light, dark, rock) as transparent flipbook sprite
sheets. Its licence is free below one million dollars of annual revenue and requires the credit `VFX: KanaWorks_AI (@KanaWorks_AI)` wherever the effects are
used; the effects cannot be redistributed as a pack. They are therefore not copied into the library: `ui_set_fetch` downloads one effect (`fire_impact_01`)
from the release and writes `CREDIT.txt` beside it.

## Interaction checks in the critique

The `interaction` pack (ten rules, Spanish text included) covers keyboard, focus and ARIA. Seven read the page source: a click handler on an element that is not
a control, a control without a name, a tabindex above zero, a reference to an id that does not exist, an ARIA widget without what its role requires, repeated ids and
a link that acts as a button. Three read a measurement taken in the browser at capture time (`vitruvius_hoard/keyboard.py`): the page is walked with Tab, the
focus indicator of each stop is compared with the same element unfocused (animations are paused while it runs), and elements with a pointer cursor that nothing
focusable contains are listed. `design_critique` returns a `keyboard` summary (tab stops, controls without a focus ring, pointer-only controls, controls Tab
never reached) next to the findings; the unnamed, pointer-only and no-ring findings are Floor.

## Critique

The `webcraft` pack adds `flat-hero-surface` and the dashboard rules. `design_critique` returns `references` (textures to try when the page is one
flat colour, dashboard rules for dashboard findings, matches for the focus text).
