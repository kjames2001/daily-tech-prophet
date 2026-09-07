#!/usr/bin/env python3
"""Generate a newsprint background texture as a data URI (PIL)."""
import base64
import io
import random

from PIL import Image, ImageDraw, ImageFilter


def generate_newsprint(
    width=720, height=720,
    base=(246, 240, 227),
    foxing_strength=0.5,
    grain_strength=14,
    halftone_strength=8,
) -> str:
    """Generate an aged newsprint texture and return a PNG data URI."""
    rng = random.Random(20260904)  # deterministic
    img = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(img)

    # ── Foxing / aging stains (soft blotches) ──
    for _ in range(28):
        cx, cy = rng.randint(0, width), rng.randint(0, height)
        r = rng.randint(40, 160)
        shade = rng.randint(6, 18 + int(14 * foxing_strength))
        col = (base[0] - shade, base[1] - shade, base[2] - shade - 4)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    img = img.filter(ImageFilter.GaussianBlur(radius=30))

    # ── Print bleed-through (horizontal bands) ──
    for _ in range(10):
        y = rng.randint(0, height)
        band_h = rng.randint(2, 6)
        shade = rng.randint(2, 6)
        draw.rectangle(
            [0, y, width, y + band_h],
            fill=(base[0] - shade, base[1] - shade, base[2] - shade),
        )
    img = img.filter(ImageFilter.GaussianBlur(radius=1.2))

    # ── Fiber grain noise ──
    px = img.load()
    for y in range(height):
        for x in range(0, width, 2):  # stride 2 for speed
            n = rng.randint(-grain_strength, grain_strength)
            r = max(0, min(255, px[x, y][0] + n))
            g = max(0, min(255, px[x, y][1] + n))
            b = max(0, min(255, px[x, y][2] + n))
            px[x, y] = (r, g, b)
            if x + 1 < width:
                px[x + 1, y] = (r, g, b)

    # ── Halftone dot grid (very subtle, like offset printing) ──
    dot_layer = Image.new("L", (width, height), 255)
    dot_draw = ImageDraw.Draw(dot_layer)
    dot_spacing = 4
    for y in range(0, height, dot_spacing):
        for x in range(0, width, dot_spacing):
            if rng.random() < 0.5:
                dot_draw.ellipse(
                    [x, y, x + 2, y + 2], fill=rng.randint(236, 248)
                )
    img = Image.composite(
        img, Image.new("RGB", (width, height), tuple(max(0, c - halftone_strength) for c in base)), dot_layer
    )

    # ── Fold crease down the middle (very subtle) ──
    for x_off in (-1, 0, 1):
        draw.line(
            [(width // 2 + x_off, 0), (width // 2 + x_off, height)],
            fill=tuple(max(0, c - 10) for c in base),
            width=1,
        )

    # ── Vignette (darker edges, like old paper) ──
    vig = Image.new("L", (width, height), 0)
    vig_draw = ImageDraw.Draw(vig)
    vig_draw.ellipse(
        [-width // 3, -height // 3, width + width // 3, height + height // 3],
        fill=255,
    )
    vig = vig.filter(ImageFilter.GaussianBlur(radius=80))
    dark = Image.new("RGB", (width, height), (214, 205, 182))
    img = Image.composite(img, dark, vig)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"


if __name__ == "__main__":
    uri = generate_newsprint()
    print(f"length: {len(uri)}")
    with open("/tmp/newsprint_uri.txt", "w") as f:
        f.write(uri)
    # Save a preview PNG for visual inspection
    import re
    data = base64.b64decode(uri.split(",")[1])
    with open("/tmp/newsprint_preview.jpg", "wb") as f:
        f.write(data)
    print("saved /tmp/newsprint_preview.jpg")