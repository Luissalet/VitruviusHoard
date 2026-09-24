# Vitruvius's Hoard — REST API

Base URL: `http://127.0.0.1:5191` (or whatever `VITRUVIUS_PORT` resolved to; see `data/url`). Every route below is
served from the same FastAPI app as the MCP bridge and uses the same domain logic — the client should never need
anything not listed here. All bodies and responses are JSON unless noted. Errors are always
`{"error": "message"}` with a 4xx/5xx status.

## Health & status

### `GET /api/health`

```json
{
  "service": "vitruvius-hoard",
  "version": "0.1.0",
  "dataDirConfigured": false,
  "browser": {"ok": true, "error": null, "playwright_installed": true},
  "ffmpeg": true,
  "git": true,
  "counts": {"sources": 19, "documents": 240, "chunks": 3100, "styles": 40, "palettes": 12,
            "font_pairings": 18, "rules": 120, "renders": 4, "design_systems": 2, "references": 6},
  "hoard_link": {"version": "0.4.0", "family": "0.4.0", "events": true, "app": "vitruvius", "hub": "http://127.0.0.1:8810"}
}
```

### `GET /api/status`

```json
{
  "service": "vitruvius-hoard",
  "version": "0.1.0",
  "data_dir": "/path/to/data",
  "started_at": 1790000000.0,
  "now": 1790000123.0,
  "browser": {"ok": true, "error": null, "playwright_installed": true},
  "ffmpeg": true,
  "git": true,
  "counts": { "...": "same shape as /api/health" },
  "models": {
    "llm": {"capability": "llm", "provider": "llamacpp", "url": "...", "model": "...", "api": "openai", "state": "resolved", "reason": "..."},
    "vision": {"...": "same Resolution shape, or state: \"unavailable\", reason: \"no vision model\""},
    "embeddings": {"...": "..."}
  }
}
```

## Library

### `GET /api/library/search?query=...&kind=&source=&area=&limit=8`

Query params: `query` (required), `kind` (`skill|guide|rule|catalog|reference|readme|other`), `source` (source
id), `area` (`typography|color|layout|motion|a11y|forms|performance|content`), `limit` (1-50).

```json
{
  "count": 2,
  "items": [
    {
      "cite": "[vitruvius: vercel-web-interface-guidelines/AGENTS.md § Motion]",
      "source": "vercel-web-interface-guidelines",
      "license": "MIT",
      "score": 4.21,
      "text": "Prefer easing curves over linear timing functions for UI motion.",
      "kind": "rule",
      "heading": "Motion"
    }
  ]
}
```

### `POST /api/library/brief`

Request:

```json
{"subject": "a fintech dashboard", "vibe": "editorial", "product_type": "finance", "platform": "web",
 "mode": "marketing", "knobs": {"variance": 5}, "use_model": false}
```

Response (a "brief" object — this exact shape is reused by the `design_brief` MCP tool):

```json
{
  "subject": "a fintech dashboard", "vibe": "editorial", "product_type": "finance", "platform": "web", "mode": "marketing",
  "styles": [{"id": 1, "source_id": "ui-ux-pro-max", "name": "Aurora", "slug": "aurora", "description": "...",
             "keywords": ["gradient", "vibrant"], "colors": [], "typography": {"heading": "", "body": ""},
             "effects": [], "best_for": [], "avoid": [], "css_hints": ""}],
  "palette": {"id": 3, "source_id": "ui-ux-pro-max", "name": "Finance Dark", "product_type": "finance",
             "colors": [{"role": "primary", "hex": "#1b2f9e"}], "notes": ""},
  "font_pairing": {"id": 2, "source_id": "ui-ux-pro-max", "heading": "Fraunces", "body": "Inter", "mono": "",
                   "category": "", "mood": "editorial", "google_fonts_url": "", "notes": ""},
  "rules": [{"id": 10, "source_id": "vercel-web-interface-guidelines", "area": "motion", "severity": "warn",
            "title": "No linear easing", "text": "...", "check_id": "motion.linear-easing"}],
  "motion_guidance": [{"cite": "[vitruvius: ...]", "source": "...", "license": "MIT", "score": 1.2, "text": "...", "kind": "rule", "heading": "Motion"}],
  "anti_patterns": ["Do not default to the generic hero + three feature cards layout.", "..."],
  "checklist": ["Run render_preview at 390/1024/1440 and check for horizontal overflow.", "..."],
  "cites": ["[vitruvius: ui-ux-pro-max style/aurora]", "..."],
  "direction": "An optional 150-word paragraph (only present when use_model=true and a model resolved)."
}
```

### `GET /api/library/rules?area=&severity=&source=&limit=30`

```json
{"count": 1, "rules": [{"id": 10, "source_id": "...", "area": "motion", "severity": "warn", "title": "...", "text": "...", "check_id": "motion.linear-easing"}]}
```

## Catalog

### `GET /api/catalog/styles?limit=100`

```json
{"styles": [{"id": 1, "source_id": "ui-ux-pro-max", "name": "Glassmorphism", "slug": "glassmorphism",
            "description": "Frosted, translucent panels.", "keywords": ["glass", "blur"],
            "colors": ["#ffffff33"], "typography": {"heading": "", "body": ""}, "effects": ["backdrop-blur"],
            "best_for": ["dashboards"], "avoid": ["print"], "css_hints": "backdrop-filter: blur(20px);"}]}
```

### `GET /api/catalog/palettes?limit=100`

```json
{"palettes": [{"id": 3, "source_id": "ui-ux-pro-max", "name": "Finance Dark", "product_type": "finance",
              "colors": [{"role": "primary", "hex": "#1b2f9e"}, {"role": "surface", "hex": "#0b1130"}], "notes": ""}]}
```

### `GET /api/catalog/fonts?limit=100`

```json
{"fonts": [{"id": 2, "source_id": "ui-ux-pro-max", "heading": "Fraunces", "body": "Inter", "mono": "IBM Plex Mono",
           "category": "serif+sans", "mood": "editorial", "google_fonts_url": "https://fonts.google.com/...", "notes": ""}]}
```

## Sources (ingestion)

### `GET /api/sources`

```json
{"sources": [{"id": "impeccable", "kind": "git", "url": "https://...", "license": "Apache-2.0", "category": "criterion",
             "tags": ["design-language"], "paths": ["skill/**"], "structured": false, "status": "ready", "error": "",
             "docs": 42, "chunks": 310, "commit": "a1b2c3...", "last_ingest_ts": 1790000000.0, "note": ""}]}
```

`status` is one of `idle | cloning | ingesting | ready | error`.

### `POST /api/sources`

Request:

```json
{"id": "my-skill", "url": "https://github.com/me/my-skill", "kind": "git", "license": "MIT",
 "category": "criterion", "paths": ["SKILL.md"], "tags": ["custom"], "structured": false}
```

Response: the created source object (same shape as one item of `GET /api/sources`), `201 Created`.

### `POST /api/sources/{id}/ingest`

No body. Response: `{"ok": true, "queued": ["my-skill"]}`. Runs in the background; poll `GET /api/sources` or the
`source_status` tool for progress. `404` if the id is unknown.

## Renders

### `GET /api/renders?limit=30`

```json
{"renders": [{"id": "a1b2c3d4e5f6", "created_ts": 1790000000.0, "kind": "html", "input_hash": "123456",
             "url": "", "title": "", "widths": [390, 1024, 1440], "dark": false,
             "files": [{"width": 390, "path": "/abs/path/390.png", "full_page": true, "w": 390, "h": 812}],
             "metrics": {"fonts": {"loaded": ["Inter"]}, "colors": [], "libs": [], "dom_size": 210},
             "lint": {"findings": [], "score": 9.5, "counts": {"info": 0, "warn": 1, "error": 0}}, "ms": 812.4}]}
```

### `POST /api/renders`

Request:

```json
{"html": "<html>...</html>", "url": null, "widths": [390, 1024, 1440], "full_page": true, "dark": false,
 "wait_ms": 800, "lint": true, "title": "landing v1"}
```

Exactly one of `html`/`url` must be given. Response: a render object (same shape as one item of `GET /api/renders`
above), `201 Created`. On a capture failure `metrics` is `{"error": "no browser", "hint": "..."}` and `lint` is the
default all-clear shape.

### `GET /api/renders/{id}`

The render object. `404` if unknown.

### `GET /api/renders/{id}/files/{name}`

Serves one captured file (a PNG, a `.mp4`/`.webm` scroll video, or `poster.png`) by its path relative to that
render's folder, e.g. `390.png` or `scroll.mp4`. `403` if the path escapes the render's own folder, `404` if the
file does not exist.

### `POST /api/renders/{id}/critique`

Request: `{"focus": "hierarchy and motion", "use_vision": true}` (both optional; `use_vision` defaults `true`).

Response (a "critique" object):

```json
{
  "score": 7.8, "heuristic_score": 8.5, "vision_model": "qwen2.5-vl-7b-instruct",
  "findings": [{"check_id": "motion.no-reduced-motion", "area": "motion", "severity": "warn",
               "title": "No prefers-reduced-motion support", "detail": "...", "evidence": null,
               "fix": "Add an @media (prefers-reduced-motion: reduce) block..."},
              {"check_id": null, "area": "hierarchy", "severity": "info", "title": "Weak visual hierarchy",
               "detail": "The hero heading and body text are nearly the same size.", "evidence": null,
               "fix": "Increase the heading's size and weight relative to body text."}],
  "summary": "Solid layout, but hierarchy and motion need work.",
  "ms": 940.2
}
```

`404` if the render id is unknown.

### `POST /api/lint`

Request: exactly one of `html`, `url`, or `render_id`.

```json
{"html": "<html>...</html>"}
```

Response (a "lint result" object):

```json
{"findings": [{"check_id": "a11y.missing-alt", "area": "a11y", "severity": "error",
              "title": "Images missing alt text", "detail": "2 image(s) have no alt attribute.", "evidence": 2,
              "fix": "Add descriptive alt text to every meaningful image (alt=\"\" for decorative ones)."}],
 "score": 8.5, "counts": {"info": 1, "warn": 2, "error": 1}}
```

### `POST /api/renders/compare`

Request: `{"render_a": "id1", "render_b": "id2", "width": 1024}` (`width` optional; defaults to each render's
first captured width).

```json
{"diff_pct": 3.42, "diff_image": "/abs/path/diff-id1-id2.png", "width": 1024, "height": 900, "changed_bbox": [10, 20, 400, 300]}
```

## Design tokens

### `GET /api/tokens?limit=30`

```json
{"design_systems": [{"id": "d1e2f3", "name": "Finance dark", "created_ts": 1790000000.0,
                     "brief": {"name": "Finance dark", "base_color": "#1b2f9e"}, "css": "...", "tailwind": "...",
                     "preview_render_id": "a1b2c3"}]}
```

(`tokens`, the full generated token tree, is omitted from the list for size — fetch one by id for that.)

### `POST /api/tokens`

Request:

```json
{"name": "Finance dark", "base_color": "#1b2f9e", "hue": null, "style": "soft", "vibe": "trustworthy",
 "mode": "both", "knobs": {"motion_intensity": 4}, "fonts": {"heading": "Fraunces", "body": "Inter"},
 "radius": null, "density": "comfortable"}
```

Response, `201 Created` (a "design system" object):

```json
{
  "id": "d1e2f3", "name": "Finance dark", "created_ts": 1790000000.0,
  "brief": {"name": "Finance dark", "base_color": "#1b2f9e", "style": "soft", "density": "comfortable"},
  "tokens": {
    "name": "Finance dark", "hue": 233.4,
    "color": {
      "primary": {"50": "#eff3ff", "100": "...", "200": "...", "300": "...", "400": "...", "500": "#1b2f9e",
                 "600": "...", "700": "...", "800": "...", "900": "...", "950": "..."},
      "neutral": {"50": "...", "...": "...", "950": "..."},
      "semantic": {"success": {"50": "...", "...": "..."}, "warn": {"...": "..."}, "danger": {"...": "..."}, "info": {"...": "..."}},
      "surfaces": {"light": {"bg": "#f...", "surface": "#ffffff", "surface-2": "#...", "border": "#..."},
                  "dark": {"bg": "#...", "surface": "#...", "surface-2": "#...", "border": "#..."}},
      "on": {"light": {"on-bg": "#0a0a0f", "on-surface": "#0a0a0f", "on-primary": "#ffffff"}, "dark": {"...": "..."}}
    },
    "typography": {"heading": "Fraunces, ui-serif, Georgia, serif", "body": "Inter, ui-sans-serif, system-ui, sans-serif",
                   "mono": "IBM Plex Mono, ui-monospace, monospace",
                   "scale": {"xs": "clamp(...)", "sm": "clamp(...)", "base": "clamp(...)", "lg": "clamp(...)",
                            "xl": "clamp(...)", "2xl": "clamp(...)", "3xl": "clamp(...)", "4xl": "clamp(...)", "5xl": "clamp(...)"}},
    "spacing": {"0_5": "2.00px", "1": "4.00px", "...": "..."},
    "radius": {"sm": "6px", "md": "10px", "lg": "16px", "xl": "24px", "pill": "999px"},
    "shadow": {"sm": "0 1px 2px rgb(0 0 0 / 0.06)", "md": "...", "lg": "..."},
    "motion": {"duration": {"fast": 120, "base": 200, "slow": 320, "enter": 240, "exit": 160},
              "easing": {"standard": "cubic-bezier(0.2, 0, 0, 1)", "emphasized": "...", "decelerate": "...",
                        "accelerate": "...", "spring": "..."}, "travel_px": 16, "intensity": 5},
    "z_index": {"base": 0, "dropdown": 1000, "sticky": 1100, "overlay": 1200, "modal": 1300, "toast": 1400},
    "breakpoints": {"sm": "480px", "md": "768px", "lg": "1024px", "xl": "1280px", "2xl": "1536px"},
    "style": "soft", "density": "comfortable"
  },
  "css": ":root {\n  --color-primary-50: #...;\n  ...\n}\n",
  "tailwind": "@theme {\n  --color-primary-50: #...;\n  ...\n}\n",
  "preview_render_id": null
}
```

### `GET /api/tokens/{id}`

The full design system object above. `404` if unknown.

### `DELETE /api/tokens/{id}`

`{"ok": true}`, or `404`.

### `GET /api/tokens/{id}/export?format=json|css|tailwind|w3c`

- `format=css` or `format=tailwind`: returns the raw CSS text (`Content-Type: text/css`), not wrapped in JSON.
- `format=json`: `{"format": "json", "content": {"color-primary-500": "#1b2f9e", "...": "..."}}` (the flat,
  Style-Dictionary-ish map).
- `format=w3c`: `{"format": "w3c", "content": {"color": {"primary": {"500": {"$value": "#1b2f9e", "$type": "color"}}}, "...": "..."}}`.

### `POST /api/tokens/{id}/preview`

Request: `{"dark": false}`. Renders the token playground HTML and returns a render object (same shape as
`POST /api/renders`), and stamps `preview_render_id` on the design system.

### `GET /api/tokens/{id}/playground?dark=false`

Returns the raw, self-contained playground HTML (`Content-Type: text/html`) — point an `<iframe>` at this URL.

## References (gallery)

### `GET /api/references?query=&tags=a,b&vibe=&lib=&limit=12`

`tags` is a comma-separated list. Response:

```json
{"count": 1, "references": [{"id": "8a5e7b321c36", "created_ts": 1790000000.0, "url": "https://example.com",
                             "title": "Example", "description": "", "tags": ["editorial"], "note": "", "vibe": "bold and warm",
                             "files": {"desktop": "/abs/.../desktop/1440.png", "mobile": "/abs/.../mobile/390.png",
                                      "video": "/abs/.../desktop/scroll.mp4", "poster": "/abs/.../desktop/poster.png"},
                             "palette": ["#1b2f9e", "#f4ede1"], "fonts": ["Fraunces", "Inter"], "libs": ["gsap"],
                             "motion": {"animations": 4, "transitions": 6, "scroll_driven": 1, "reduced_motion_respected": true},
                             "analysis": {"raw": "A bold editorial vibe with warm serif headings."}, "source_id": null}]}
```

### `POST /api/references`

Request: `{"url": "https://example.com", "html": null, "tags": ["editorial"], "note": "great hero", "video": true, "analyze": true}`
(exactly one of `url`/`html`). Response: a reference object as above, `201 Created`.

### `GET /api/references/{id}`

The reference object. `404` if unknown.

### `DELETE /api/references/{id}`

`{"ok": true}`, or `404`.

### `GET /api/references/{id}/files/{name}`

Serves one captured file by its path relative to that reference's folder, e.g. `desktop/1440.png` or
`desktop/scroll.mp4`. `403`/`404` as above.

## Settings

### `GET /api/settings`

```json
{"backend": {}, "vision_enabled": true, "widths": [390, 1024, 1440], "video_enabled": true, "language": "en"}
```

`backend` is the parsed `data/backend.json` (empty object if the file does not exist) — see the hoard_link
`LinkConfig` schema for its keys (`only_resident`, `faustus`, `comfy`, `gpu_lease`, `capabilities`).

### `PUT /api/settings`

Request: any subset of `{"backend": {...}, "vision_enabled": true, "widths": [390, 1024, 1440], "video_enabled": true, "language": "en"}`.
Response: the full settings object (same shape as `GET /api/settings`).

## Agent bridge

### `GET /api/agent/tools`

```json
{"instructions": "Vitruvius's Hoard is a design workbench...", "tools": [{"name": "design_search",
 "description": "Search the design library...\n...", "annotations": {"readOnlyHint": true, "destructiveHint": false,
 "idempotentHint": true, "openWorldHint": false}, "inputSchema": {"type": "object", "properties": {"...": "..."}}}]}
```

### `POST /api/agent/call`

Header: `Authorization: Bearer <token from data/mcp-token>`. Body: `{"name": "vitruvius_status", "arguments": {}, "caller": "faustus"}`.
Response: whatever that tool returns (see each tool's shape above/below). `401` on a bad/missing token, `404` for
an unknown tool, `400` on an argument validation error.

## PWA

`GET /manifest.webmanifest` (`application/manifest+json`) and `GET /sw.js` (`application/javascript`) — standard
PWA installability files; the client does not need to call these directly.


## POST /api/assay — functional check with assay

Request: `{"html"?: string, "url"?: string, "render_id"?: string, "path"?: string, "timeout_s"?: number (30-900, default 300)}` — exactly one page source.

Response (200): `{"id": string, "works": boolean, "planned": number, "passed": number, "failed": number, "surface": [{"kind": string, "label": string, "selector": string, "enabled": boolean}], "failing": [{"id": string, "what": string, "detail": string, "measured": string, "acts": [object]}], "cases_sample": [{"id": string, "what": string, "outcome": "passed"|"failed"}], "ms": number, "folder": string, "entry": string, "exit_code": number}`

When assay is not installed or cannot open the page: `{"error": string, "hint": string}` with status 200 (the UI shows the hint). 404 for a render without a saved source; 400 without a page source.

`GET /api/status` gains `"assay": boolean` (installed or not).
