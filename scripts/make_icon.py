"""Build Vitruvius's icon from the family dragon.

    python scripts/make_icon.py [--src path/to/dragon-src.png] [--preview out.png]

Steps (the family recipe):
1. mask the yellow play button by HSV (and the dark halo around it) and fill it,
   so its triangle goes too;
2. flatten the picture to "dragon luminance on a flat background" and inpaint the
   button area on that flat map (cv2.inpaint TELEA), so no yellow or dark ring bleeds
   into the result;
3. recolour the dragon by luminance with a dark→light ramp (Vitruvius: #1b2f9e → #6d8dff,
   cobalt blueprint); the eye keeps a light colour; the background becomes the family's
   flat dark navy (the black rounded-square corners disappear);
4. compose a gold vector glyph ≈400 px centred at (627, 768): the Vitruvian proportion —
   a circle inside a square — crossed by a drafting divider, with a dark outline like the
   other icons.

Outputs: app-icon.png (1254²), client/public/icon-512.png, icon-192.png, favicon.ico
(16-256) and dist-icons/Vitruvius hoard.png (for the shared Icons folder).
Needs: pillow, numpy, opencv-python-headless (requirements-icon.txt).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1254
BACKGROUND = (1, 11, 27)  # the family's flat dark navy
RAMP_DARK = np.array([0x1B, 0x2F, 0x9E], dtype=np.float32)
RAMP_LIGHT = np.array([0x6D, 0x8D, 0xFF], dtype=np.float32)
EYE_COLOR = np.array([0xDF, 0xE6, 0xFF], dtype=np.float32)
GOLD_TOP = (0xF8, 0xD8, 0x8C)
GOLD_BOTTOM = (0xE0, 0xA2, 0x42)
OUTLINE = (6, 10, 24)
GLYPH_CENTER = (627, 768)
GLYPH_SIZE = 400


def default_source() -> Path | None:
    for candidate in (ROOT.parent / "Icons" / "dragon-src.png", ROOT.parent / "icons" / "dragon-src.png", Path.home() / "icons" / "dragon-src.png"):
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# dragon
# ---------------------------------------------------------------------------

def button_mask(rgb: np.ndarray) -> np.ndarray:
    """The yellow button, its triangle and the dark halo around it (uint8 0/255)."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    yellow = cv2.inRange(hsv, (12, 90, 110), (40, 255, 255))
    yellow = cv2.morphologyEx(yellow, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(yellow, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(yellow)
    if contours:
        biggest = max(contours, key=cv2.contourArea)
        cv2.drawContours(filled, [biggest], -1, 255, thickness=cv2.FILLED)  # includes the triangle
    halo = cv2.dilate(filled, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (29, 29)))
    return halo


def eye_mask(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    cyan = cv2.inRange(hsv, (80, 120, 120), (105, 255, 255))
    cyan = cv2.morphologyEx(cyan, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.dilate(cyan, np.ones((5, 5), np.uint8))


def recolour_dragon(src: Image.Image) -> Image.Image:
    rgb = np.array(src.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS))
    button = button_mask(rgb)
    eye = eye_mask(rgb)
    lum = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    lum[eye > 0] = 200.0  # the eye counts as dragon (light) for the flat map
    # Flatten: dragon luminance on a flat background level, so inpainting cannot pick up
    # the button's yellow or the rounded square's black corners.
    bg_level = float(np.median(lum[(lum < 40) & (button == 0)])) if np.any((lum < 40) & (button == 0)) else 12.0
    flat = np.where(lum > 45, lum, bg_level).astype(np.float32)
    flat8 = np.clip(flat, 0, 255).astype(np.uint8)
    inpainted = cv2.inpaint(flat8, button, 21, cv2.INPAINT_TELEA).astype(np.float32)
    # Alpha of the dragon: smooth ramp on luminance (antialiased edges).
    alpha = np.clip((inpainted - 50.0) / 40.0, 0.0, 1.0)
    dragon = inpainted[alpha > 0.9]
    lo, hi = (np.percentile(dragon, 2), np.percentile(dragon, 98)) if dragon.size else (90.0, 220.0)
    t = np.clip((inpainted - lo) / max(1.0, hi - lo), 0.0, 1.0)[..., None]
    colour = RAMP_DARK * (1 - t) + RAMP_LIGHT * t
    eye_f = (cv2.GaussianBlur(eye, (5, 5), 0).astype(np.float32) / 255.0)[..., None]
    colour = colour * (1 - eye_f) + EYE_COLOR * eye_f
    background = np.array(BACKGROUND, dtype=np.float32)
    a = alpha[..., None]
    out = background * (1 - a) + colour * a
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


# ---------------------------------------------------------------------------
# glyph: a circle inside a square (the Vitruvian proportion) crossed by a drafting divider
# ---------------------------------------------------------------------------

def glyph_layer(scale: int = 4) -> Image.Image:
    """RGBA of the glyph, drawn at `scale`× on a square of 1.4 × GLYPH_SIZE and downsampled."""
    box = int(GLYPH_SIZE * 1.4)
    big = box * scale
    c = big / 2
    u = GLYPH_SIZE * scale / 400.0  # 1 unit = 1 px of a 400 px glyph

    def P(x, y):
        return (c + x * u, c + y * u)

    def stroke_mask(draw_fn, width):
        m = Image.new("L", (big, big), 0)
        draw_fn(ImageDraw.Draw(m), int(width * u))
        return m

    def frame(d, w):  # square + inscribed circle
        d.rounded_rectangle([P(-150, -150), P(150, 150)], radius=14 * u, outline=255, width=w)
        d.ellipse([P(-150, -150), P(150, 150)], outline=255, width=w)

    def divider(d, w):  # a drafting divider: hinge at the top, two legs open to the base line
        hinge = P(0, -168)
        left, right = P(-118, 172), P(118, 172)
        d.line([left, hinge, right], fill=255, width=w, joint="curve")
        r = w * 0.9
        for x, y in (left, right):
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
        hr = 22 * u
        d.ellipse([hinge[0] - hr, hinge[1] - hr, hinge[0] + hr, hinge[1] + hr], fill=255)
        # the hinge hole
        d.ellipse([hinge[0] - hr * 0.42, hinge[1] - hr * 0.42, hinge[0] + hr * 0.42, hinge[1] + hr * 0.42], fill=0)

    top, bottom = np.array(GOLD_TOP, np.float32), np.array(GOLD_BOTTOM, np.float32)
    ramp = np.linspace(0, 1, big, dtype=np.float32)[:, None, None]
    gold = Image.fromarray(np.broadcast_to(top * (1 - ramp) + bottom * ramp, (big, big, 3)).astype(np.uint8), "RGB")
    outline_colour = Image.new("RGB", (big, big), OUTLINE)

    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    layer.paste(outline_colour, (0, 0), stroke_mask(frame, 40))
    layer.paste(gold, (0, 0), stroke_mask(frame, 18))
    layer.paste(outline_colour, (0, 0), stroke_mask(divider, 46))
    layer.paste(gold, (0, 0), stroke_mask(divider, 24))
    return layer.resize((box, box), Image.LANCZOS)


def compose(src: Image.Image) -> Image.Image:
    base = recolour_dragon(src).convert("RGBA")
    glyph = glyph_layer()
    x = GLYPH_CENTER[0] - glyph.width // 2
    y = GLYPH_CENTER[1] - glyph.height // 2
    base.alpha_composite(glyph, (x, y))
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--src", type=Path, default=None, help="The family dragon (dragon-src.png)")
    parser.add_argument("--preview", type=Path, default=None, help="Also write a 400 px preview here")
    args = parser.parse_args()
    src_path = args.src or default_source()
    if src_path is None or not src_path.is_file():
        print("dragon-src.png not found: pass --src")
        return 2
    icon = compose(Image.open(src_path))
    icon.save(ROOT / "app-icon.png", optimize=True)
    public = ROOT / "client" / "public"
    public.mkdir(parents=True, exist_ok=True)
    icon.resize((512, 512), Image.LANCZOS).save(public / "icon-512.png", optimize=True)
    icon.resize((192, 192), Image.LANCZOS).save(public / "icon-192.png", optimize=True)
    icon.convert("RGBA").save(public / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    dist = ROOT / "dist-icons"
    dist.mkdir(exist_ok=True)
    icon.save(dist / "Vitruvius hoard.png", optimize=True)
    if args.preview:
        icon.resize((400, 400), Image.LANCZOS).convert("RGB").save(args.preview)
    print(f"icon written from {src_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
