"""Sound for motion compositions: ``{t, rol}`` events -> takes from a bank of code-made sound effects -> one mix at -14 LUFS.

The sound effects come from the earshot bank (MIT, Copyright (c) 2026 Leon Lin; see NOTICE): only its model-free part is used
(``earshot.forge.bank`` and ``earshot.forge.kit``: no models, no network, CPU only). Everything else here is original: which cues a
composition has, how a take is placed on a cue from its *measured* onset or peak, the gain staging, the master (integrated loudness
to -14 LUFS, a look-ahead limiter at -1 dBTP) and the check that measures where each sound really landed in the finished track.

earshot is optional. Install it without its model stack (it declares torch, which this feature never loads)::

    pip install --no-deps "earshot @ git+https://github.com/Leonxlnx/earshot@591fa3e028032e6dce56620a20e932e35667e8d8"
    pip install -e ".[sound]"

A composition without ``sound.enabled`` is exported silent, exactly as before.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from .motion import SOUND_PRESETS, SOUND_ROLES, Composition

SR = 48000
TARGET_LUFS = -14.0
CEILING_DBTP = -1.0
LOUDNESS_TOLERANCE = 0.5          # LU: how far from the target a mix may land when the ceiling stops the gain
SOFT_DRIVE = 1.6                  # soft-saturation drive of the master (tanh); 1 would be nearly linear
MAX_EVENTS = 120
TAKES_PER_ROLE = 3                # takes rendered per used role: repeated cues of a role take turns
INSTALL_HINT = ('pip install --no-deps "earshot @ git+https://github.com/Leonxlnx/earshot@591fa3e028032e6dce56620a20e932e35667e8d8" '
                'and pip install -e ".[sound]" (numpy, scipy, soundfile, soxr, pyloudnorm)')


class SoundUnavailable(RuntimeError):
    """The optional sound engine is not installed (the message says how to install it)."""


def _engine():
    try:
        from earshot.forge import bank, kit
        import pyloudnorm  # noqa: F401
        import soundfile  # noqa: F401
    except Exception as error:  # noqa: BLE001 — any import problem means the feature is unavailable
        raise SoundUnavailable(f"The sound engine is not installed ({type(error).__name__}: {error}). Install it with: {INSTALL_HINT}") from error
    return bank, kit


def status() -> dict[str, Any]:
    """Whether the sound engine is installed, its version and the presets and roles it offers."""
    try:
        bank, kit = _engine()
    except SoundUnavailable as error:
        return {"available": False, "hint": str(error), "presets": list(SOUND_PRESETS), "roles": list(SOUND_ROLES)}
    import earshot
    return {"available": True, "engine": "earshot", "version": getattr(earshot, "__version__", ""), "sounds": len(bank.ids()),
            "presets": kit.presets(), "roles": list(kit.ROLES), "target_lufs": TARGET_LUFS, "ceiling_dbtp": CEILING_DBTP}


def roles(preset: str = "crisp") -> list[dict[str, Any]]:
    """Every role of a preset with the sound behind it, where it syncs to the cue and its level; ``off`` when the preset leaves it out."""
    _, kit = _engine()
    spec = kit.preset(preset)
    out = []
    for role in kit.ROLES:
        row = (spec.get("roles") or {}).get(role)
        if not row:
            out.append({"role": role, "off": (spec.get("off") or {}).get(role) or "the preset does not sound this role"})
            continue
        out.append({"role": role, "sound": row.get("sound"), "align": row.get("align") or kit.ALIGN.get(role, "onset"),
                    "level_db": row.get("level_db", 0.0), "offset_ms": row.get("offset_ms", 0), "min_gap_ms": row.get("min_gap_ms", 0),
                    "note": row.get("note") or ""})
    return out


# ---------------------------------------------------------------- which cues a composition has

def _layer_role(layer) -> str | None:
    if layer.effect == "none" and layer.kind == "text":
        return None
    if layer.kind == "text":
        return "text"
    if layer.kind == "line":
        return "tick"
    return "pop"


def auto_events(composition: Composition) -> list[dict[str, Any]]:
    """The cues the structure of a composition implies: a scene change (``whoosh.short``), a text arriving (``text``), a shape appearing
    (``pop``), a line drawn (``tick``). Deterministic: the same composition gives the same cues."""
    events: list[dict[str, Any]] = []
    start = 0.0
    for index, scene in enumerate(composition.scenes):
        if index > 0:
            events.append({"t": round(start, 4), "rol": "whoosh.short", "source": "auto", "why": f"scene {index + 1} starts"})
        for layer in scene.layers:
            role = _layer_role(layer)
            if role is not None:
                events.append({"t": round(start + layer.delay, 4), "rol": role, "source": "auto", "why": f"{layer.kind} enters in scene {index + 1}"})
        start += scene.duration
    return events


def plan(composition: Composition) -> list[dict[str, Any]]:
    """The events that will be sounded, in time order: the explicit ones plus, with ``sound.auto``, the structural ones."""
    total = sum(s.duration for s in composition.scenes)
    events = [{"t": e.t, "rol": e.rol, "gain_db": e.gain_db or 0.0, "source": "user", "why": "event of the composition"} for e in composition.sound.events]
    if composition.sound.auto:
        events += [{**e, "gain_db": 0.0} for e in auto_events(composition)]
    events = [e for e in events if 0 <= e["t"] < total]
    events.sort(key=lambda e: (e["t"], e["rol"], e["source"]))
    return events[:MAX_EVENTS]


# ---------------------------------------------------------------- the takes

def _kit_for(preset: str, used: list[str]) -> dict[str, Any]:
    """The preset cut down to the roles the composition uses (rendering all 21 roles takes a minute; three takes of a few roles seconds)."""
    _, kit = _engine()
    spec = json.loads(json.dumps(kit.preset(preset)))
    chosen = {}
    for role in used:
        row = (spec.get("roles") or {}).get(role)
        if row:
            row["takes"] = min(int(row.get("takes") or 1), TAKES_PER_ROLE)
            chosen[role] = row
    spec["roles"] = chosen
    spec.pop("off", None)
    spec.pop("mix", None)         # how the music steps down before a hit: there is no music bed under these effects
    spec["name"] = f"vitruvius-{preset}"
    return spec


def render_takes(preset: str, used: list[str], cache_dir: Path) -> dict[str, Any]:
    """Render (or reuse from the cache) the takes of the used roles; returns the kit lock with the measured onset, peak and end of each."""
    _, kit = _engine()
    spec = _kit_for(preset, used)
    digest = hashlib.sha1(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    folder = Path(cache_dir) / "sound-takes" / f"{preset}-{digest}"
    lock = kit.render(spec, str(folder))
    lock["folder"] = str(folder)
    return lock


# ---------------------------------------------------------------- the mix

def _stereo(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64)
    return np.stack([y, y], axis=1) if y.ndim == 1 else y[:, :2]


def _true_peak_db(x: np.ndarray) -> float:
    from scipy.signal import resample_poly
    peak = float(np.max(np.abs(resample_poly(x, 4, 1, axis=0)))) if x.size else 0.0
    return -240.0 if peak <= 1e-12 else 20 * math.log10(peak)


def _limit(x: np.ndarray, ceiling_db: float, sr: int = SR) -> np.ndarray:
    """A look-ahead peak limiter. The gain needed at each sample is held for 25 ms either side of a peak and then smoothed with a 50 ms
    window, so it eases down before the peak and back up after it (no clipping, no zipper noise) and never ends up above what the
    peak needs: the ceiling is kept."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    ceiling = 10 ** (ceiling_db / 20)
    peak = np.max(np.abs(x), axis=1)
    gain = np.minimum(1.0, ceiling / np.maximum(peak, 1e-12))
    half = max(8, int(0.025 * sr))
    gain = minimum_filter1d(gain, size=2 * half + 1, mode="nearest")
    gain = uniform_filter1d(gain, size=2 * half + 1, mode="nearest")
    return x * gain[:, None]


def _shape(x: np.ndarray, drive: float = SOFT_DRIVE) -> np.ndarray:
    """Soft saturation (tanh) normalised so that full scale stays full scale: it tucks the transients in and lifts what is under them."""
    return np.tanh(x * drive) / math.tanh(drive)


def master(mix: np.ndarray, sr: int = SR, target: float = TARGET_LUFS, ceiling_db: float = CEILING_DBTP) -> tuple[np.ndarray, dict[str, Any]]:
    """Set an effects-only mix to ``target`` integrated LUFS (BS.1770, gated) without going over ``ceiling_db`` dBTP.

    A track of short effects is mostly transient (a crest factor of 15-20 dB), so its loudness is capped by its peaks long before -14 LUFS.
    The chain is therefore gain -> soft saturation -> look-ahead limiter, re-measured a few rounds until the loudness lands. It is a
    loud, punchy master and says so (``shaped``); when even that cannot reach the target, ``reached`` is False and the real figure is given.
    """
    import pyloudnorm as pyln
    meter = pyln.Meter(sr)

    def lufs(x: np.ndarray) -> float:
        padded = x if len(x) >= sr else np.vstack([x, np.zeros((sr - len(x), 2))])
        try:
            value = float(meter.integrated_loudness(padded))
        except ValueError:
            return -math.inf
        return value if math.isfinite(value) else -math.inf

    before = lufs(mix)
    info: dict[str, Any] = {"lufs_before": None if not math.isfinite(before) else round(before, 2), "shaped": False, "limited": False}
    if not math.isfinite(before):
        return mix, {**info, "lufs": None, "true_peak_dbtp": round(_true_peak_db(mix), 2), "gain_db": 0.0, "reached": False}
    sample_ceiling = ceiling_db - 0.6            # the limiter works on sample peaks; this margin keeps the inter-sample (true) peak under the ceiling
    gain = target - before
    out = mix
    for _ in range(16):
        raw = mix * 10 ** (gain / 20)
        if np.max(np.abs(raw)) > 10 ** (sample_ceiling / 20):
            out = _limit(_shape(raw), sample_ceiling, sr)
            info["shaped"] = info["limited"] = True
        else:
            out = raw
        now = lufs(out)
        if abs(now - target) <= 0.05:
            break
        gain += (target - now) * 0.9
    final = lufs(out)
    over = _true_peak_db(out) - ceiling_db         # the ceiling is a promise: trim the little that is left over
    if over > 0:
        out = out * 10 ** (-over / 20)
        final = lufs(out)
    info.update(lufs=round(final, 2), true_peak_dbtp=round(_true_peak_db(out), 2), gain_db=round(gain, 2), reached=abs(final - target) <= LOUDNESS_TOLERANCE)
    return out, info


def _sync_in(track: np.ndarray, sr: int, align: str, lo: float = 0.0, hi: float | None = None) -> float | None:
    """Where the sound sits in an array, found here and not taken from the bank's own lock: its first sample above -30 dB of the loudest
    in the span (``onset``), or its loudest 5 ms (``peak``). Seconds from the start of ``track``; a measurement that checks the placement."""
    a = max(0, int(lo * sr))
    b = len(track) if hi is None else min(len(track), int(hi * sr))
    if b - a < 8:
        return None
    seg = np.max(np.abs(track[a:b]), axis=1)
    top = float(seg.max())
    if top < 1e-6:
        return None
    if align == "peak":
        win = max(1, int(0.005 * sr))
        smooth = np.convolve(seg, np.ones(win) / win, mode="same")
        return round((a + int(np.argmax(smooth))) / sr, 4)
    hit = np.nonzero(seg >= top * 10 ** (-30 / 20))[0]
    return round((a + int(hit[0])) / sr, 4) if hit.size else None


def mix(composition: Composition, cache_dir: Path, out_wav: Path | None = None, *, sr: int = SR) -> dict[str, Any]:
    """Sound a composition: plan the cues, render the takes, place each on its cue from the take's measured sync point, sum, master to
    -14 LUFS and (with ``out_wav``) write a 24-bit WAV exactly as long as the picture. Returns the lock: per event the take, where it
    was placed, where it landed in the finished track and the error in ms, plus the loudness and the peak."""
    import soundfile as sf
    t0 = time.monotonic()
    _, kit = _engine()
    if sr != SR:
        raise ValueError("The sound engine renders at 48 kHz")
    preset = composition.sound.preset
    events = plan(composition)
    total = sum(s.duration for s in composition.scenes)
    frames = math.ceil(total * composition.fps)
    length = int(round(frames / composition.fps * sr))
    if not events:
        return {"ok": True, "silent": True, "reason": "the composition has no cues to sound", "preset": preset, "events": [], "duration_s": round(length / sr, 4)}
    lock = render_takes(preset, sorted({e["rol"] for e in events}), cache_dir)
    folder = Path(lock["folder"])
    buffer = np.zeros((length, 2), dtype=np.float64)
    placed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    cache: dict[str, np.ndarray] = {}
    for rol in sorted({e["rol"] for e in events}):
        row = (lock.get("roles") or {}).get(rol)
        mine = [e for e in events if e["rol"] == rol]
        if not row or not row.get("takes"):
            skipped += [{"t": e["t"], "rol": rol, "why": "the preset leaves this role off"} for e in mine]
            continue
        cues = kit.space_run([e["t"] for e in mine], float(row.get("min_gap_ms") or 0.0))
        for n, (event, cue) in enumerate(zip(mine, cues)):
            take = row["takes"][n % len(row["takes"])]
            data = cache.get(take["file"])
            if data is None:
                audio, rate = sf.read(str(folder / take["file"]), dtype="float64", always_2d=False)
                if rate != sr:
                    raise ValueError(f"take {take['file']} is {rate} Hz")
                data = cache[take["file"]] = _stereo(audio)
            align = row.get("align") or "onset"
            start = kit.place(take, row, cue)
            gain = kit.gain_db(take, row, None) + float(event.get("gain_db") or 0.0)
            first = int(round(start * sr))
            lo, hi = max(0, first), min(length, first + len(data))
            if hi <= lo:
                skipped.append({"t": event["t"], "rol": rol, "why": "the take falls outside the picture"})
                continue
            buffer[lo:hi] += data[lo - first:hi - first] * 10 ** (gain / 20)
            own = _sync_in(data, sr, align)                       # the sync point of this take, measured here
            expected = round(cue + float(row.get("offset_ms") or 0.0) / 1000.0, 4)
            placed.append({"t": event["t"], "cue": round(cue, 4), "rol": rol, "source": event["source"], "sound": row.get("sound"), "take": take["file"],
                           "align": align, "offset_ms": float(row.get("offset_ms") or 0.0), "gain_db": round(gain, 2), "start_s": round(start, 4),
                           "take_onset_s": take["onset_s"], "take_peak_s": take["peak_s"], "expected_s": expected,
                           "measured_s": None if own is None else round(start + own, 4), "_span": (start, start + len(data) / sr)})
    fade = min(length, int(0.04 * sr))
    if fade:
        buffer[-fade:] *= np.linspace(1.0, 0.0, fade)[:, None]       # the picture ends: no click on a cut tail
    mastered, loudness = master(buffer, sr)
    for e in placed:
        e["error_ms"] = None if e["measured_s"] is None else round((e["measured_s"] - e["expected_s"]) * 1000, 1)
        # In the finished track the same sound can only be found where nothing else sounds around it: a whoosh's rise precedes its peak.
        window = (e["expected_s"] - 0.15, e["expected_s"] + 0.4)
        alone = not any(o is not e and o["_span"][0] < window[1] and o["_span"][1] > window[0] for o in placed)
        found = _sync_in(mastered, sr, e["align"], window[0], window[1]) if alone else None
        e["in_mix_s"] = found
        e["in_mix_error_ms"] = None if found is None else round((found - e["expected_s"]) * 1000, 1)
    for e in placed:
        e.pop("_span")
    errors = [abs(e["error_ms"]) for e in placed if e["error_ms"] is not None]
    result: dict[str, Any] = {"ok": True, "silent": False, "preset": preset, "engine": status().get("version"), "duration_s": round(length / sr, 4),
                              "events": placed, "skipped": skipped, "loudness": loudness, "target_lufs": TARGET_LUFS,
                              "max_error_ms": max(errors) if errors else None, "takes_folder": str(folder), "ms": round((time.monotonic() - t0) * 1000, 1)}
    if out_wav is not None:
        out_wav = Path(out_wav)
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_wav), mastered.astype(np.float32), sr, subtype="PCM_24")
        result["file"] = str(out_wav)
    return result
