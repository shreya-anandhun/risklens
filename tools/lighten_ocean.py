"""One-off asset step: recolour the satellite image's oceans to the chosen
ocean blue (#235696), keeping land, ice and a subtle depth shading.

    .venv/bin/pip install pillow   # dev-only dependency
    .venv/bin/python tools/lighten_ocean.py
"""
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent / "app/static/vendor/earth/earth-blue-marble.jpg"
DST = SRC.with_name("earth-light-ocean.jpg")

DEEP = np.array([35, 86, 150], dtype=float)       # open ocean: the chosen #235696
SHALLOW = np.array([50, 108, 172], dtype=float)   # shelves and shallow seas, a touch lighter


def main():
    img = np.asarray(Image.open(SRC).convert("RGB"), dtype=float)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # Ocean = blue-dominant and fairly dark. Soft ramps avoid a hard coastline.
    blue_dom = np.clip(((b - r) - 6) / 14, 0, 1) * np.clip(((b - g) + 12) / 14, 0, 1)
    dark = np.clip((125 - lum) / 25, 0, 1)
    m = blue_dom * dark
    # Deep open ocean is near-black navy; treat any very dark, blue-leaning pixel as fully ocean.
    deep_water = np.clip((45 - lum) / 15, 0, 1) * ((b >= r) & (b >= g - 3))
    m = np.maximum(m, deep_water)[..., None]
    depth = np.clip((b - 25) / 95, 0, 1)[..., None]      # brighter original blue = shallower water
    ocean = DEEP + (SHALLOW - DEEP) * depth
    out = img * (1 - m) + ocean * m
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(DST, quality=88, optimize=True, progressive=True)
    print(f"wrote {DST.name}: ocean share {float(m.mean()):.0%}")


if __name__ == "__main__":
    main()
