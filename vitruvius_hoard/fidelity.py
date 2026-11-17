"""Clone fidelity: every round of a remake ("Rehacer") scored with the family's web-fidelity measure (``hoard_link.webfidelity``).

The pictures are the ones the parity check already took: the reference's full page at each width and the round's candidate. Each is
cut into viewport-high screens; a screen is one case. Its checkpoint is the screen's normalized SSIM against the reference's screen
(flat-baseline-normalized RGB SSIM: 1 is identical, 0 is no better than a flat picture of the background), and its checks are the
reference's headings, links, buttons and form fields that lie in that screen: each must exist in the candidate with the same text
(fields by kind). A case passes when its checks pass and its screen reaches the threshold (0.99); the fidelity score is the share of
cases that pass. The zones that differ most are outlined and numbered on the candidate's picture of each width.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable, Optional

from .hoard_link import webfidelity as wf

THRESHOLD = wf.THRESHOLD
MAX_SCREENS = 12
REGIONS_PER_SCREEN = 4
ZONES_PER_PICTURE = 10
ZONES_WIDTH = 900           # the picture with the zones is shrunk to this width
FIELDS = ("input", "textarea", "select")


def _norm(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()[:120]


def elements(outline: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """What a person can read or use on the page: headings, links and buttons by their text, form fields by their kind."""
    out = []
    for it in (outline or {}).get("items") or []:
        tag, text = it.get("t", ""), _norm(it.get("tx", ""))
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and text:
            out.append({"kind": "heading", "label": text, "y": int(it.get("y") or 0)})
        elif tag == "a" and text:
            out.append({"kind": "link", "label": text, "y": int(it.get("y") or 0)})
        elif tag == "button" and text:
            out.append({"kind": "button", "label": text, "y": int(it.get("y") or 0)})
        elif tag in FIELDS:
            out.append({"kind": "field", "label": tag, "y": int(it.get("y") or 0)})
    return out


def checks(reference: Optional[dict[str, Any]], candidate: Optional[dict[str, Any]], limit: int = 120) -> list[dict[str, Any]]:
    """One check per element of the reference (repeated ones count as many times as they appear)."""
    have = Counter((e["kind"], e["label"]) for e in elements(candidate))
    out = []
    for e in elements(reference)[:limit]:
        key = (e["kind"], e["label"])
        ok = have[key] > 0
        if ok:
            have[key] -= 1
        out.append({**e, "ok": ok, "detail": "" if ok else f"missing {e['kind']}: {e['label'][:80]}"})
    return out


def score_widths(reference: dict[int, Path], candidate: dict[int, Path], ref_outlines: dict[int, Any], cand_outlines: dict[int, Any], *,
                 viewport_height: Callable[[int], int], out_dir: Optional[Path] = None, threshold: float = THRESHOLD,
                 max_screens: int = MAX_SCREENS) -> dict[str, Any]:
    """Fidelity of one candidate against its reference at every width there are pictures for."""
    import numpy as np

    cases, widths_out, failing = [], [], []
    for w in sorted(reference, reverse=True):
        if w not in candidate or not Path(reference[w]).is_file() or not Path(candidate[w]).is_file():
            continue
        ref, cand = wf.load_rgb(reference[w]), wf.load_rgb(candidate[w])
        vh = int(viewport_height(w))
        n = max(1, min(int(max_screens), -(-ref.shape[0] // vh)))
        found = checks(ref_outlines.get(w), cand_outlines.get(w))
        screens, zones = [], []
        for k in range(n):
            y0 = k * vh
            h = min(vh, ref.shape[0] - y0)
            ref_crop = ref[y0:y0 + h]
            cand_crop = cand[y0:y0 + h] if cand.shape[0] > y0 else np.empty((0, cand.shape[1], 3))
            m = wf.normalized_ssim(ref_crop, cand_crop)
            regions = []
            if m["score"] < threshold:
                regions = [{**r, "y": r["y"] + y0} for r in wf.diff_regions(ref_crop, cand_crop, limit=REGIONS_PER_SCREEN)]
                zones += regions
            mine = [c for c in found if (min(c["y"] // vh, n - 1) if c["y"] >= 0 else 0) == k]
            scored = wf.score_case(f"{w}-{k + 1}", mine, [{"score": m["score"]}], threshold)
            screen = {"index": k, "y": y0, "height": h, "score": m["score"], "ssim": m["ssim"], "regions": regions,
                      "checks": len(mine), "checks_ok": sum(1 for c in mine if c["ok"]), "passed": scored["passed"]}
            screens.append(screen)
            cases.append(scored)
            if not scored["passed"]:
                failing.append({"width": w, "index": k, "y": y0, "height": h, "score": round(m["score"] * 100, 2), "viewport_height": vh})
        zones_file = ""
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            top = sorted(zones, key=lambda r: r["severity"], reverse=True)[:ZONES_PER_PICTURE]
            img = wf.overlay(cand[: ref.shape[0]] if cand.shape[0] >= ref.shape[0] else cand, top)
            if img.width > ZONES_WIDTH:
                img = img.resize((ZONES_WIDTH, max(1, round(img.height * ZONES_WIDTH / img.width))))
            zones_file = f"zones-{w}.png"
            img.save(out_dir / zones_file, "PNG", optimize=True)
        widths_out.append({"width": w, "screens": screens, "checks": len(found), "checks_ok": sum(1 for c in found if c["ok"]),
                           "missing": [c["detail"] for c in found if not c["ok"]][:20], "zones": zones_file,
                           "score": round(sum(1 for s in screens if s["passed"]) / len(screens), 4),
                           "visual_mean": round(sum(s["score"] for s in screens) / len(screens), 4)})
    site = wf.score_site(cases)
    return {"score": site["score"], "cases": site["cases"], "passed": site["passed"], "visual_mean": site["visual_mean"],
            "functional_rate": site["functional_rate"], "threshold": threshold, "widths": widths_out, "failing_screens": failing}


def summary(full: dict[str, Any]) -> dict[str, Any]:
    """The few numbers kept with the round."""
    return {k: full.get(k) for k in ("score", "cases", "passed", "visual_mean", "functional_rate", "threshold")}
