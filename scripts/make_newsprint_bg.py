#!/usr/bin/env python3
"""
Build the final newsprint background tile for The Daily Tech Prophet.

Source: Texturelabs PAPER_290 (free vintage newspaper texture).
Processing:
  1. Crop away the hard vertical crease (left 50% of the original)
  2. Warm cream tint (newsprint, not grey)
  3. Mirror-tile 2x2 — organic textures show no seam when mirrored,
     giving a perfectly tileable sheet at any page height
  4. Downscale to a 960x1280 tile (crisp on retina, ~150KB)

Output: <MEDIA_DIR>/newsprint_bg.jpg (served via the artifact
server's /media/ route — no data URI, no webview quirks).
"""
from pathlib import Path
import os
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

try:
    from reddit_newspaper_config import MEDIA_DIR as _MD
    MEDIA_DIR = Path(_MD)
except ImportError:
    MEDIA_DIR = Path(os.environ.get("HOME", "/root")) / ".hermes/artifacts/media"
SRC = MEDIA_DIR / "newsprint_texturelabs.jpg"
OUT = MEDIA_DIR / "newsprint_bg.jpg"


def main():
    img = Image.open(SRC).convert("RGB")
    w, h = img.size  # 1920x1281

    # 1. Crop left half — avoids the vertical fold crease
    img = img.crop((0, 0, w // 2, h))  # 960x1281

    # 2. Warm cream tint (newsprint, not grey)
    r, g, b = img.split()
    r = r.point(lambda v: min(255, int(v * 1.12 + 16)))
    g = g.point(lambda v: min(255, int(v * 1.07 + 9)))
    b = b.point(lambda v: int(v * 0.93))
    img = Image.merge("RGB", (r, g, b))
    img = ImageEnhance.Brightness(img).enhance(1.14)
    img = ImageEnhance.Color(img).enhance(0.92)
    img = img.filter(ImageFilter.GaussianBlur(0.5))

    # 3. Mirror-tile 2x2 for seamless repeat at any page height
    mx = ImageOps.mirror(img)
    my = ImageOps.flip(img)
    mxy = ImageOps.flip(mx)
    tile = Image.new("RGB", (img.width * 2, img.height * 2))
    tile.paste(img, (0, 0))
    tile.paste(mx, (img.width, 0))
    tile.paste(my, (0, img.height))
    tile.paste(mxy, (img.width, img.height))

    # 4. Final size: 960 wide (retina-sharp at ~480px display tile)
    tile = tile.resize((960, int(tile.height * 960 / tile.width)), Image.LANCZOS)

    tile.save(OUT, format="JPEG", quality=74, optimize=True)
    print(f"saved {OUT} {tile.size} {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()