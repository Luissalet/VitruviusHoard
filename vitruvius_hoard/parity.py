"""Visual parity: how close a candidate page is to a reference, measured screen by screen.

Both pages are loaded in a frozen browser (fixed clock, seeded random numbers, no CSS transitions or animations, videos on
their first frame), captured full page at each width and cut into viewport-high screens. The reference is loaded twice: pixels
that differ between those two loads are unstable and are left out of the score. A screen passes when enough of its stable
pixels are within the colour tolerance of the reference; the page height must match within a few pixels.

The scoring here is pure Pillow: it takes images and returns numbers and diff pictures, so it can be tested with synthetic
images. The browser part (``BrowserWorker.parity_capture``) only produces the screenshots.
"""

from __future__ import annotations

import html as html_lib
import json
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageChops, ImageFilter

DEFAULT_WIDTHS = [1440, 390]
DEFAULT_TOLERANCE = 0.10        # per colour channel, as a share of 255
DEFAULT_PASS_SCORE = 98.0       # % of stable pixels within tolerance
DEFAULT_HEIGHT_TOLERANCE = 4    # px of difference in total page height
DEFAULT_MAX_SCREENS = 12
MAX_PAGE_HEIGHT = 14000         # taller pages are cut here (the browser cannot screenshot much more)

REF_PAD = (255, 0, 255)         # what lies below the end of a shorter reference ...
CAND_PAD = (0, 255, 0)          # ... and of a shorter candidate: never equal, so missing rows count as different

DIFF_RED = (229, 57, 53)
DIFF_BLUE = (30, 136, 229)
DIM_TO_WHITE = 0.78

# Runs before any script of the page: fixed clock, seeded random numbers, controlled frames, no transitions, no caret,
# videos that never start.
FREEZE_JS = r"""
(() => {
  const FIXED = 1767268800000; // 2026-01-01T12:00:00Z
  const RealDate = Date;
  const FrozenDate = new Proxy(RealDate, {
    construct(target, args, newTarget) { return Reflect.construct(target, args.length ? args : [FIXED], newTarget === FrozenDate ? target : newTarget); },
    apply() { return new RealDate(FIXED).toString(); },
    get(target, prop, receiver) { return prop === 'now' ? () => FIXED : Reflect.get(target, prop, receiver); },
  });
  try { Object.defineProperty(window, 'Date', { value: FrozenDate, writable: true, configurable: true }); } catch (e) {}
  try { performance.now = () => 1000; } catch (e) {}
  let seed = 0x9e3779b9;
  Math.random = () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const realSetTimeout = window.setTimeout.bind(window), realClearTimeout = window.clearTimeout.bind(window);
  window.requestAnimationFrame = (cb) => realSetTimeout(() => { try { cb(1000); } catch (e) { setTimeout(() => { throw e; }); } }, 16);
  window.cancelAnimationFrame = (id) => realClearTimeout(id);
  try { HTMLMediaElement.prototype.play = function () { this.pause(); try { this.currentTime = 0; } catch (e) {} return Promise.resolve(); }; } catch (e) {}
  const css = '*,*::before,*::after{transition:none!important;transition-delay:0s!important;caret-color:transparent!important;scroll-behavior:auto!important}';
  const inject = () => { const s = document.createElement('style'); s.setAttribute('data-parity-freeze', ''); s.textContent = css; (document.head || document.documentElement).appendChild(s); };
  if (document.documentElement) inject();
  else new MutationObserver((_, o) => { if (document.documentElement) { o.disconnect(); inject(); } }).observe(document, { childList: true });
})();
"""

# After the load: lazy images forced, the page scrolled to the bottom and back to fire lazy-loading, fonts and images awaited,
# finished animations fast-forwarded (infinite ones cancelled), videos paused on the first frame.
SETTLE_JS = r"""
async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const within = (p, ms) => Promise.race([p, sleep(ms)]);
  for (const img of document.images) { try { img.loading = 'eager'; } catch (e) {} }
  const step = Math.max(200, Math.floor(window.innerHeight * 0.8));
  let y = 0, guard = 0;
  while (guard++ < 120) {
    window.scrollTo(0, y);
    await sleep(60);
    const total = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
    if (y + window.innerHeight >= total) break;
    y += step;
  }
  await sleep(150);
  window.scrollTo(0, 0);
  try { await within(document.fonts.ready, 6000); } catch (e) {}
  await within(Promise.all(Array.from(document.images).map((i) => (i.complete ? null : new Promise((r) => { i.addEventListener('load', r); i.addEventListener('error', r); })))), 8000);
  for (const v of document.querySelectorAll('video')) { try { v.pause(); v.autoplay = false; v.currentTime = 0; } catch (e) {} }
  try { for (const a of document.getAnimations()) { try { a.finish(); } catch (e) { a.cancel(); } } } catch (e) {}
  await sleep(120);
  window.scrollTo(0, 0);
  return Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
}
"""


def viewport_height(width: int) -> int:
    return 900 if width >= 768 else 844


# ---------------------------------------------------------------------------------------------------- scoring

def _rgb(image: Image.Image) -> Image.Image:
    return image if image.mode == "RGB" else image.convert("RGB")


def _screen(image: Image.Image, width: int, y0: int, height: int, fill: tuple[int, int, int]) -> Image.Image:
    """Rows y0..y0+height of `image`, `width` px wide; whatever lies outside the image is `fill`."""
    out = Image.new("RGB", (width, height), fill)
    box = image.crop((0, y0, min(image.width, width), min(image.height, y0 + height)))
    if box.width > 0 and box.height > 0:
        out.paste(box, (0, 0))
    return out


def _differs(a: Image.Image, b: Image.Image, threshold: int) -> Image.Image:
    """'L' mask, 255 where any channel differs by more than `threshold` (0..254)."""
    diff = ImageChops.difference(a, b)
    r, g, bl = diff.split()
    worst = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    return worst.point([0] * (threshold + 1) + [255] * (255 - threshold))


def _count(mask: Image.Image) -> int:
    return mask.histogram()[255]


def score_screen(ref_a: Image.Image, ref_b: Optional[Image.Image], cand: Image.Image, *, tolerance: float = DEFAULT_TOLERANCE,
                 noise_threshold: int = 0, noise_dilate: bool = True) -> dict[str, Any]:
    """One screen. `ref_a` and `cand` are compared; pixels that differ between `ref_a` and `ref_b` (a second load of the
    reference) are noise and are not counted. All three images have the same size."""
    threshold = max(0, min(254, int(tolerance * 255)))
    bad = _differs(ref_a, cand, threshold)
    if ref_b is not None:
        noise = _differs(ref_a, ref_b, noise_threshold)
        if noise_dilate and _count(noise):
            noise = noise.filter(ImageFilter.MaxFilter(3))
    else:
        noise = Image.new("L", ref_a.size, 0)
    total = ref_a.width * ref_a.height
    noise_px = _count(noise)
    stable = total - noise_px
    stable_mask = noise.point([255] + [0] * 255)
    bad_stable = ImageChops.multiply(bad, stable_mask)
    bad_px = _count(bad_stable)
    score = round(100.0 * (stable - bad_px) / stable, 2) if stable > 0 else None
    return {"score": score, "stable_px": stable, "bad_px": bad_px, "noise_px": noise_px, "total_px": total,
            "_bad": bad_stable, "_noise": noise}


def diff_picture(reference: Image.Image, bad: Image.Image, noise: Image.Image) -> Image.Image:
    """Reference dimmed; red where it differs, blue where the pixel is unstable (masked)."""
    base = Image.blend(reference, Image.new("RGB", reference.size, (255, 255, 255)), DIM_TO_WHITE)
    base.paste(Image.new("RGB", reference.size, DIFF_BLUE), (0, 0), noise)
    base.paste(Image.new("RGB", reference.size, DIFF_RED), (0, 0), bad)
    return base


def compare_widths_images(ref_loads: list[Image.Image], cand: Image.Image, *, width: int, vh: int, max_screens: int = DEFAULT_MAX_SCREENS,
                          tolerance: float = DEFAULT_TOLERANCE, pass_score: float = DEFAULT_PASS_SCORE,
                          height_tolerance: int = DEFAULT_HEIGHT_TOLERANCE, out_dir: Optional[Path] = None,
                          save_screens: bool = True) -> dict[str, Any]:
    """Everything for one viewport width. `ref_loads` are the full-page captures of the reference (one or two loads)."""
    ref_loads = [_rgb(i) for i in ref_loads]
    cand = _rgb(cand)
    ref = ref_loads[0]
    h_ref, h_cand = ref.height, cand.height
    delta = h_cand - h_ref
    height_pass = abs(delta) <= height_tolerance
    # Inside the tolerance the extra rows of the taller page are not scored (they are not a visible mismatch);
    # beyond it they count as different, so a page that grew or shrank cannot pass.
    h_cmp = min(h_ref, h_cand) if height_pass else max(h_ref, h_cand)
    h_cmp = max(1, h_cmp)
    total_screens = -(-h_cmp // vh)
    checked = min(total_screens, max(1, max_screens))
    screens: list[dict[str, Any]] = []
    full_diff = Image.new("RGB", (width, min(h_cmp, checked * vh)), (255, 255, 255))
    stable_all = bad_all = noise_all = 0
    for index in range(checked):
        y0 = index * vh
        h = min(vh, h_cmp - y0)
        a = _screen(ref, width, y0, h, REF_PAD)
        b = _screen(ref_loads[1], width, y0, h, REF_PAD) if len(ref_loads) > 1 else None
        c = _screen(cand, width, y0, h, CAND_PAD)
        res = score_screen(a, b, c, tolerance=tolerance)
        picture = diff_picture(a, res.pop("_bad"), res.pop("_noise"))
        full_diff.paste(picture, (0, y0))
        passed = res["score"] is not None and res["score"] >= pass_score
        row = {"index": index, "y": y0, "height": h, "score": res["score"], "passed": passed, "stable_px": res["stable_px"],
               "bad_px": res["bad_px"], "noise_px": res["noise_px"], "total_px": res["total_px"], "diff_image": None}
        if res["score"] is None:
            row["note"] = "Todos los píxeles de esta pantalla son inestables entre las dos cargas de la referencia."
        if out_dir is not None and save_screens:
            name = f"diff-{width}-{index + 1}.png"
            picture.save(Path(out_dir) / name)
            row["diff_image"] = name
        screens.append(row)
        stable_all += res["stable_px"]; bad_all += res["bad_px"]; noise_all += res["noise_px"]
    overall = round(100.0 * (stable_all - bad_all) / stable_all, 2) if stable_all else None
    failing = [s["index"] + 1 for s in screens if not s["passed"]]
    result = {
        "width": width, "viewport_height": vh, "reference_height": h_ref, "candidate_height": h_cand, "height_delta": delta,
        "height_pass": height_pass, "screens_total": total_screens, "screens_checked": checked, "truncated": total_screens > checked,
        "screens": screens, "score": overall, "min_screen_score": min([s["score"] for s in screens if s["score"] is not None], default=None),
        "noise_px": noise_all, "noise_pct": round(100.0 * noise_all / max(1, stable_all + noise_all), 2),
        "failing_screens": failing, "passed": bool(height_pass and not failing),
    }
    if out_dir is not None:
        full_diff.save(Path(out_dir) / f"diff-{width}.png")
        result["images"] = {"reference": f"reference-{width}.png", "candidate": f"candidate-{width}.png", "diff": f"diff-{width}.png"}
    return result


def summarize(widths: list[dict[str, Any]], errors: Optional[list[str]] = None) -> dict[str, Any]:
    """Global verdict: everything passes, or the list of what fails (in Spanish, as the UI shows it)."""
    failures: list[str] = []
    for w in widths:
        label = f"{w['width']} px"
        if not w["height_pass"]:
            failures.append(f"{label}: la altura de la página difiere {w['height_delta']:+d} px (referencia {w['reference_height']} px, candidata {w['candidate_height']} px)")
        for s in w["screens"]:
            if not s["passed"]:
                shown = "sin píxeles estables" if s["score"] is None else f"{s['score']} %"
                failures.append(f"{label}: pantalla {s['index'] + 1} (desde {s['y']} px) con {shown} de coincidencia")
        if w["truncated"]:
            failures.append(f"{label}: solo se han comprobado {w['screens_checked']} de {w['screens_total']} pantallas")
    for e in errors or []:
        failures.append(e)
    passed = not failures
    text = "Paridad visual completa en todas las anchuras." if passed else f"No pasa: {len(failures)} fallo(s)."
    return {"passed": passed, "failures": failures, "text": text}


# ---------------------------------------------------------------------------------------------------- storage

def runs_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "parity"


def run_dir(data_dir: Path, run_id: str) -> Path:
    if not run_id or not all(c.isalnum() for c in run_id):
        raise LookupError(f"Unknown parity run '{run_id}'.")
    return runs_dir(data_dir) / run_id


def save_run(data_dir: Path, run: dict[str, Any]) -> None:
    folder = run_dir(data_dir, run["id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "compare.html").write_text(report_html(run), encoding="utf-8")


def get_run(data_dir: Path, run_id: str) -> dict[str, Any]:
    file = run_dir(data_dir, run_id) / "run.json"
    if not file.is_file():
        raise LookupError(f"Unknown parity run '{run_id}'.")
    return json.loads(file.read_text(encoding="utf-8"))


def list_runs(data_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    base = runs_dir(data_dir)
    if not base.is_dir():
        return []
    rows = []
    for folder in base.iterdir():
        file = folder / "run.json"
        if not file.is_file():
            continue
        try:
            run = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append({"id": run["id"], "created_ts": run.get("created_ts"), "label": run.get("label", ""), "passed": run["summary"]["passed"],
                     "reference": run.get("reference", {}).get("label", ""), "candidate": run.get("candidate", {}).get("label", ""),
                     "widths": [{"width": w["width"], "score": w["score"], "passed": w["passed"]} for w in run.get("widths", [])]})
    rows.sort(key=lambda r: r.get("created_ts") or 0, reverse=True)
    return rows[:max(1, limit)]


def delete_run(data_dir: Path, run_id: str) -> bool:
    import shutil
    folder = run_dir(data_dir, run_id)
    if not folder.is_dir():
        raise LookupError(f"Unknown parity run '{run_id}'.")
    shutil.rmtree(folder)
    return True


def file_path(data_dir: Path, run_id: str, name: str) -> Path:
    base = run_dir(data_dir, run_id).resolve()
    candidate = (base / name).resolve()
    if base not in candidate.parents:
        raise PermissionError("path escapes the parity run directory")
    return candidate


# ---------------------------------------------------------------------------------------------------- side-by-side page

_REPORT_CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14171c;--muted:#5b6472;--line:#d9dde4;--ok:#1b7f4b;--bad:#c62828;--accent:#2f4bd8}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--panel:#171b23;--ink:#e8ebf0;--muted:#98a1b0;--line:#2a303b;--ok:#4cc38a;--bad:#ff6b66;--accent:#7f95ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1500px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 12px}
.verdict{padding:10px 14px;border-radius:8px;border:1px solid var(--line);background:var(--panel);margin-bottom:12px;font-weight:600}
.verdict.ok{border-color:var(--ok);color:var(--ok)}.verdict.bad{border-color:var(--bad);color:var(--bad)}
.verdict ul{margin:6px 0 0;padding-left:18px;font-weight:400;color:var(--ink)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}.tabs button,.modes button{border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:6px 12px;border-radius:6px;cursor:pointer;font:inherit}
.tabs button[aria-pressed=true],.modes button[aria-pressed=true]{border-color:var(--accent);color:var(--accent);font-weight:600}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:14px}@media (max-width:900px){.layout{grid-template-columns:minmax(0,1fr)}}
.stage{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px}
.viewer{position:relative;overflow:hidden;line-height:0;border:1px solid var(--line);border-radius:4px;touch-action:none;background:#fff}
.viewer img{display:block;width:100%;height:auto}.viewer .top{position:absolute;inset:0}
.viewer .handle{position:absolute;top:0;bottom:0;width:3px;margin-left:-1px;background:var(--accent);cursor:ew-resize}
.viewer .handle::after{content:"";position:absolute;top:50%;left:50%;width:18px;height:18px;margin:-9px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px var(--panel)}
.range{width:100%;margin:8px 0 2px}.legend{color:var(--muted);font-size:12px;display:flex;justify-content:space-between}
.modes{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap}.swatch{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}tr[data-y]{cursor:pointer}tr[data-y]:hover{background:rgba(127,127,127,.12)}
.ok{color:var(--ok)}.bad{color:var(--bad)}.meta{color:var(--muted);font-size:12px;margin:0 0 8px}
"""

_REPORT_JS = """
const RUN = JSON.parse(document.getElementById('run-data').textContent);
let cur = 0, mode = 'slider', pos = 50;
const $ = (s) => document.querySelector(s);
function tabs(){ const t = $('#tabs'); t.innerHTML=''; RUN.widths.forEach((w,i)=>{ const b=document.createElement('button'); b.type='button'; b.textContent=w.width+' px '+(w.passed?'\\u2713':'\\u2717'); b.setAttribute('aria-pressed', i===cur); b.onclick=()=>{cur=i;draw();}; t.appendChild(b); }); }
function draw(){
  tabs(); const w = RUN.widths[cur]; if(!w.images){ $('#stage').textContent='Sin imágenes.'; return; }
  const f = (n)=>'files/'+n;
  const modes = [['slider','Deslizador'],['diff','Diferencias'],['ref','Referencia'],['cand','Candidata']];
  $('#modes').innerHTML=''; modes.forEach(([k,l])=>{ const b=document.createElement('button'); b.type='button'; b.textContent=l; b.setAttribute('aria-pressed', k===mode); b.onclick=()=>{mode=k;draw();}; $('#modes').appendChild(b); });
  const v = $('#viewer'); v.innerHTML='';
  const add=(src,cls)=>{ const i=document.createElement('img'); i.src=f(src); i.alt=''; if(cls) i.className=cls; v.appendChild(i); return i; };
  if(mode==='slider'){ add(w.images.reference); const top=document.createElement('div'); top.className='top'; const i=document.createElement('img'); i.src=f(w.images.candidate); i.alt=''; top.appendChild(i); v.appendChild(top); const h=document.createElement('div'); h.className='handle'; v.appendChild(h);
    const set=(p)=>{ pos=Math.max(0,Math.min(100,p)); top.style.clipPath='inset(0 0 0 '+pos+'%)'; h.style.left=pos+'%'; $('#range').value=pos; };
    set(pos); $('#range').hidden=false; $('#range').oninput=(e)=>set(+e.target.value);
    const move=(e)=>{ const r=v.getBoundingClientRect(); set(100*(e.clientX-r.left)/r.width); };
    v.onpointerdown=(e)=>{ v.setPointerCapture(e.pointerId); move(e); v.onpointermove=move; }; v.onpointerup=()=>{ v.onpointermove=null; };
    $('#legend').innerHTML='<span>\\u2190 Referencia</span><span>Candidata \\u2192</span>';
  } else { $('#range').hidden=true; v.onpointerdown=null; add(mode==='diff'?w.images.diff:mode==='ref'?w.images.reference:w.images.candidate);
    $('#legend').innerHTML = mode==='diff' ? '<span><i class="swatch" style="background:#e53935"></i>distinto</span><span><i class="swatch" style="background:#1e88e5"></i>inestable (enmascarado)</span><span>el resto, atenuado</span>' : ''; }
  const rows=$('#rows'); rows.innerHTML='';
  w.screens.forEach((s)=>{ const tr=document.createElement('tr'); tr.dataset.y=s.y; tr.innerHTML='<td>'+(s.index+1)+'</td><td>'+(s.score===null?'\\u2014':s.score.toFixed(2)+' %')+'</td><td class="'+(s.passed?'ok':'bad')+'">'+(s.passed?'pasa':'no pasa')+'</td>';
    tr.onclick=()=>{ const sc=v.getBoundingClientRect().width/w.width; window.scrollTo({top: v.getBoundingClientRect().top+window.scrollY+s.y*sc-8}); }; rows.appendChild(tr); });
  $('#meta').textContent='Altura: referencia '+w.reference_height+' px, candidata '+w.candidate_height+' px ('+(w.height_delta>=0?'+':'')+w.height_delta+' px, '+(w.height_pass?'dentro':'fuera de')+' la tolerancia). Puntuación '+(w.score===null?'\\u2014':w.score+' %')+'. Ruido enmascarado '+w.noise_pct+' %.';
}
draw();
"""


def report_html(run: dict[str, Any]) -> str:
    summary = run["summary"]
    verdict = ('<div class="verdict ok">' + html_lib.escape(summary["text"]) + "</div>") if summary["passed"] else (
        '<div class="verdict bad">' + html_lib.escape(summary["text"]) + "<ul>" + "".join(f"<li>{html_lib.escape(f)}</li>" for f in summary["failures"]) + "</ul></div>")
    data = json.dumps({"widths": run["widths"]}, ensure_ascii=False).replace("</", "<\\/")
    p = run.get("params", {})
    sub = (f"Referencia: {html_lib.escape(str(run.get('reference', {}).get('label', '')))} · Candidata: {html_lib.escape(str(run.get('candidate', {}).get('label', '')))}"
           f" · tolerancia {round(100 * p.get('tolerance', DEFAULT_TOLERANCE))} % por canal · pasa con {p.get('pass_score', DEFAULT_PASS_SCORE)} % · altura ±{p.get('height_tolerance', DEFAULT_HEIGHT_TOLERANCE)} px")
    return ("<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Paridad visual {html_lib.escape(run['id'])}</title><style>{_REPORT_CSS}</style></head><body><main>"
            f"<h1>Paridad visual{(' · ' + html_lib.escape(run['label'])) if run.get('label') else ''}</h1><p class=\"sub\">{sub}</p>{verdict}"
            "<div class=\"tabs\" id=\"tabs\"></div><div class=\"layout\"><div class=\"stage\"><div class=\"modes\" id=\"modes\"></div><p class=\"meta\" id=\"meta\"></p>"
            "<div class=\"viewer\" id=\"viewer\"></div><input class=\"range\" id=\"range\" type=\"range\" min=\"0\" max=\"100\" step=\"0.1\" aria-label=\"Posición del deslizador\">"
            "<div class=\"legend\" id=\"legend\"></div></div>"
            "<div><table><thead><tr><th>Pantalla</th><th>Coincidencia</th><th>Resultado</th></tr></thead><tbody id=\"rows\"></tbody></table></div></div>"
            f"</main><script type=\"application/json\" id=\"run-data\">{data}</script><script>{_REPORT_JS}</script></body></html>")
