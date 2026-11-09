"""Cut the 画城 icon out of the website logo into a transparent PNG.

    python -X utf8 templates/explainer/make_logo.py [huacheng-logo-full.png]

The website logo (https://www.huacheng.city/huacheng_assets/huacheng-logo-full.png, kept as
assets/huacheng_logo_full.png) is the recycling icon above 画城环保 and the slogan, on an opaque white background.
This keeps the rows above the first gap (the icon), turns the white into transparency with soft edges, and removes
the white fringe, so the icon sits cleanly on the dark corner badge and end card. Writes assets/logo_icon.png.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "assets" / "huacheng_logo_full.png"
TARGET = HERE / "assets" / "logo_icon.png"


def main(source=SOURCE):
    rgb = np.asarray(Image.open(source).convert("RGB")).astype(np.float32)
    ink = 255 - rgb.min(axis=2)                       # how far each pixel is from white
    rows = np.where((ink > 60).any(axis=1))[0]
    # The icon is the first run of inked rows; the gap after it separates it from 画城环保.
    gaps = np.where(np.diff(rows) > 8)[0]
    top, bottom = rows[0], rows[gaps[0]] if len(gaps) else rows[-1]
    cols = np.where((ink[top:bottom + 1] > 60).any(axis=0))[0]
    left, right = cols[0], cols[-1]
    pad = 6
    box = (max(0, top - pad), min(rgb.shape[0], bottom + pad + 1), max(0, left - pad), min(rgb.shape[1], right + pad + 1))
    rgb, ink = rgb[box[0]:box[1], box[2]:box[3]], ink[box[0]:box[1], box[2]:box[3]]
    # Opaque once clearly off-white (light greens stay solid); the soft ramp only covers anti-aliased edges.
    alpha = np.clip((ink - 12) / 48, 0, 1)
    alpha = alpha * alpha * (3 - 2 * alpha)
    # Un-mix the white that the edge pixels were blended with.
    safe = np.maximum(alpha, 1e-3)[..., None]
    color = np.clip((rgb - (1 - safe) * 255) / safe, 0, 255)
    out = np.dstack([color, alpha[..., None] * 255]).round().astype(np.uint8)
    out[alpha == 0] = 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, "RGBA").save(TARGET, optimize=True)
    print(f"{TARGET}  {out.shape[1]}x{out.shape[0]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE)
