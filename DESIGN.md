# Vitruvius's Hoard — architecture & design system

## Architecture

```
                          ┌───────────────────────────────┐
                          │      Assistant (Faustus)      │
                          └───────────────┬───────────────┘
                                          │ stdio (MCP)
                                          ▼
                          ┌───────────────────────────────┐
                          │        mcp_server.py           │  proxies every call,
                          │  (FastMCP bridge, no DB access) │  never opens the DB
                          └───────────────┬───────────────┘
                                          │ HTTP + Bearer token
                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          vitruvius_hoard (FastAPI)                       │
│                                                                           │
│  guard.py ── request guard (Host / Origin / Fetch Metadata)              │
│                                                                           │
│  api/  ─────────────────────────────────────────────────────────────┐   │
│  │ health.py  library.py  render.py  tokens.py  references.py       │   │
│  │ settings.py  agent.py (tools+call)  pwa.py                       │   │
│  └───────────────────────────────┬───────────────────────────────────┘  │
│                                  │ every route calls Services            │
│                                  ▼                                      │
│  ┌────────────────────────── services.py ───────────────────────────┐  │
│  │  Services: db, browser worker, hoard_link.Link, ingest runner     │  │
│  └──┬───────────┬───────────┬───────────┬───────────┬───────────┬────┘  │
│     │           │           │           │           │           │       │
│     ▼           ▼           ▼           ▼           ▼           ▼       │
│  library.py  browser.py   lint.py   critique.py  tokens.py  references.py│
│  (FTS5      (Playwright   (29       (lint +     (OKLCH      (capture +  │
│   search,    worker       determ-    optional    ramps,      palette +  │
│   brief)     thread)      inistic    vision)     type/motion FTS)       │
│                           checks)                 tokens)                │
│                                                                           │
│  ingest/  ── git.py  markdown.py  catalog.py  rules.py  runner.py       │
│  (background thread: clone/pull → chunk/parse → mine rules → sources)   │
│                                                                           │
│  db.py ── SQLite (WAL, FTS5) ── data/vitruvius.db                        │
│  hoard_link/ ── vendored: family bus (emit/record_call/health_block),   │
│                Link (chat/embed against Faustus or a loopback server)   │
└─────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                          data/  (db, sources/, renders/, references/,
                                 mcp-token, url, backend.json, logs/)
```

`agent_tools.py` is the single source of truth for the 25 MCP tools: it defines pydantic argument models, the
`TOOLS` table (description, `readOnlyHint`/`destructiveHint`/`idempotentHint`, the function that runs it against
a `Services` instance) and `tool_catalog()`/`call_tool()`. `api/agent.py` and `mcp_server.py` both consume that
one catalogue, so the REST bridge and the MCP bridge can never disagree about what a tool does or how it is
described.

`main.py`'s route order matters: `family.configure(...)` runs first, then the request guard, then every API
router, and the SPA catch-all (`GET /{path:path}`) is registered **last** so it never shadows an `/api/*` route.

## Module map

| Module | Responsibility |
| --- | --- |
| `config.py` | Environment-derived process config (port, data dir, render timeout, allowed hosts). Never touches the DB. |
| `port.py` | Free-port discovery for `python -m vitruvius_hoard`. |
| `guard.py` | Host/Origin/Fetch-Metadata request guard, installed as ASGI middleware. |
| `db.py` | SQLite connection (WAL) + ordered, idempotent schema migrations, incl. FTS5 virtual tables and their sync triggers. |
| `services.py` | Wires the DB, the browser worker, `hoard_link.Link` and the ingest runner behind one object every router and tool shares; owns the render/critique/tokens/references/sources/settings/status logic. |
| `browser.py` | The single background Chromium worker (Playwright): capture (screenshot + optional scroll video) and the in-page `PROBE_JS` evaluation. |
| `lint.py` | 29 deterministic design checks over a probe dict + raw HTML, each returning typed findings; `run_lint()` scores 0-10. |
| `critique.py` | Merges lint findings with an optional vision-model rubric; robust JSON extraction from the model's answer. |
| `tokens.py` | Pure-Python OKLCH colour math, ramps, type scale, spacing/radius/shadow/motion tokens, four export formats, the self-contained playground HTML. |
| `library.py` | FTS5 `bm25` search with citations, rule listing, deterministic brief composition. |
| `references.py` | Reference-gallery capture, Pillow palette extraction, FTS search, tag/font/palette similarity. |
| `ingest/git.py` | Shallow clone / `pull --ff-only` into `data/sources/<id>`. |
| `ingest/markdown.py` | Heading-aware chunker with breadcrumbs and a ~1200-char cap. |
| `ingest/catalog.py` | Loose CSV/JSON → styles/palettes/font_pairings parsers, tolerant of unknown columns. |
| `ingest/rules.py` | Mines Do/Don't/Avoid/Never/Always bullets into `rules`, guessing area/severity/`check_id`. |
| `ingest/runner.py` | The one-source-at-a-time background ingest worker; `ingest_source()` is also the synchronous entry point used by `scripts/ingest.py` and by tests. |
| `agent_tools.py` | The 25-tool MCP/REST catalogue (single source of truth). |
| `api/*` | Thin FastAPI routers that validate input and call into `Services`. |
| `hoard_link/` | Vendored family contract: `family.emit/record_call/health_block`, `Link.chat/embed` resolution against Faustus or a loopback model server. |

## Design system (for the bundled UI)

### Identity

- **Name**: Vitruvius's Hoard — *Firmness, commodity, delight — for interfaces.*
- **Glyph**: a circle inside a square with a drafting divider (the Vitruvian proportion), gold with a dark
  outline, drawn at ≈400px centred at (627, 768) on the icon canvas (`scripts/make_icon.py`).

### Colour

- **Accent (cobalt blueprint)**: ramp from `#1b2f9e` (dark) to `#6d8dff` (light); light tint `#dfe6ff`.
- **Gold** (glyph, marks, emphasis): `#f8d88c` → `#e0a242`.
- **Dark navy background**: `#0b1130` (surfaces slightly lighter, e.g. `#141b3f`).
- Generated per-design-system palettes (via `tokens.generate`) follow the same OKLCH-ramp shape: 50 (lightest) to
  950 (darkest), semantic success/warn/danger/info ramps hue-shifted from a shared recipe, not picked ad hoc.
- Every text/background pairing in the UI must clear **4.5:1** contrast (checked by `color.low-contrast` in the
  same lint the app runs on its own output).

### Typography

- **Headings**: a distinctive serif or display face (default generated pairing: Fraunces) — never the model's
  three defaults (Inter/Roboto/Arial) alone.
- **Body**: a readable sans (default: Inter) at a fluid scale (`tokens.type_scale`, `clamp()`-based, ratio
  1.2–1.333 depending on density).
- **Mono**: for cites, ids and code (default: IBM Plex Mono).

### Layout

- Sidebar navigation (Library / Critique / Tokens / Gallery / Settings) on desktop, a top tab bar on phones —
  same shape as the sibling Hoard apps, so a person moving between them keeps their bearings.
- Content constrained to a readable max-width; cards use the generated `radius`/`shadow` tokens, never a bespoke
  one-off value.
- Screenshots and video previews are shown at their captured aspect ratio, never stretched.

### Motion

- Respect `prefers-reduced-motion` everywhere the app itself renders motion (the playground, page transitions).
- Use the generated `motion` tokens (durations 120/200/320ms, `standard`/`emphasized`/`decelerate`/`accelerate`
  cubic-béziers) rather than ad hoc values — the app should not violate its own `motion.*` lint checks.

### Components

- **Result cards** (library search, references): citation/source/license badge always visible, never buried in a
  detail view.
- **Score dial** (critique): 0-10, coloured by band (red < 5, amber 5-7.9, green ≥ 8), always paired with the
  written summary — never the number alone.
- **Colour ramp swatches** (tokens): each swatch shows its hex and its contrast ratio against the chosen
  "on" colour, so a bad choice is visible before export.

### Do / Don't

- **Do** cite the library (`[vitruvius: ...]`) next to anything quoted from it, in both the UI and MCP responses.
- **Do** show lint findings grouped by area with severity, each with its concrete fix — never a bare list of ids.
- **Don't** default new design systems to the generic AI palette shapes this app itself detects
  (`color.generic-ai-palette-1/2/3`, `color.purple-blue-gradient`) — the whole point of the app is to avoid them.
- **Don't** block the UI on a render/critique call; always show the render id immediately and stream/poll for the
  critique.

### Icon recipe

1. Flat cobalt-blueprint gradient background (`#1b2f9e` → `#6d8dff`, diagonal).
2. A gold-gradient (`#f8d88c` → `#e0a242`) glyph — circle in a square with a drafting divider and a centre pivot
   dot — with a dark (`#06 0a18`) outline, ≈400px, centred at (627, 768) on a 1254² canvas.
3. Exported at 1254² (`app-icon.png`), 512²/192² (`client/public/icon-*.png`), and a multi-size `favicon.ico`.
4. Unlike the sibling apps (which recolour a shared family dragon illustration), Vitruvius's glyph is drawn
   directly with Pillow — there is no dragon source image to vendor for this app.
