#!/usr/bin/env python3
"""Wave 14G Phase 7 — generate NCL Desktop app icon set.

Renders a 1024x1024 master icon then resizes to all macOS asset sizes.
Style: dark navy radial gradient bg, mint-green pulse waveform glyph
suggesting a "brain heartbeat" — fits NCL's "personal-AI brain" identity.
"""

import math
import os
import subprocess


try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    subprocess.run(["pip", "install", "--break-system-packages", "Pillow"], check=True)
    from PIL import Image, ImageDraw, ImageFilter


def make_master(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Radial dark navy gradient via concentric circles
    cx, cy = size / 2, size / 2
    for r in range(size, 0, -2):
        # Blend: outer = #0a1228, inner = #1a3a5c
        t = 1.0 - (r / size)
        rcol = int(0x0A + (0x1A - 0x0A) * t)
        gcol = int(0x12 + (0x3A - 0x12) * t)
        bcol = int(0x28 + (0x5C - 0x28) * t)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(rcol, gcol, bcol, 255))

    # Rounded square mask (Big Sur-style)
    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    radius = int(size * 0.225)
    mdraw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)

    # Mint pulse waveform across the middle ~60% width
    pulse = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(pulse)
    w_pad = int(size * 0.18)
    h_pad = int(size * 0.45)
    pts = []
    span = size - 2 * w_pad
    # Build a waveform: flat, peak, dip, peak, flat — synthesized via sin lobes
    n = 800
    for i in range(n):
        x = w_pad + (i / n) * span
        t = i / n

        # Two narrow pulses at t=0.35 and t=0.65
        def gauss(t, mu, sigma):
            return math.exp(-((t - mu) ** 2) / (2 * sigma**2))

        peak = (
            gauss(t, 0.30, 0.04)
            - 0.4 * gauss(t, 0.40, 0.02)
            + gauss(t, 0.60, 0.04)
            - 0.5 * gauss(t, 0.70, 0.025)
        )
        # Baseline gentle EKG-style wave
        baseline = 0.08 * math.sin(t * math.pi * 3)
        amp = peak * 0.55 + baseline
        y = cy - amp * (size * 0.30)
        pts.append((x, y))
    # Stroke
    pdraw.line(pts, fill=(125, 255, 195, 255), width=int(size * 0.018))
    # Glow halo via blur
    glow = pulse.filter(ImageFilter.GaussianBlur(radius=int(size * 0.020)))
    out = Image.alpha_composite(out, glow)
    out = Image.alpha_composite(out, pulse)

    # Small "NCL" wordmark bottom centre, semi-transparent
    label = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(label)
    # Use default font (PIL ships a basic one)
    try:
        from PIL import ImageFont

        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Andale Mono.ttf", int(size * 0.13)
        )
    except Exception:
        font = None
    text = "NCL"
    if font is not None:
        bbox = ldraw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        ldraw.text(
            ((size - tw) / 2 - bbox[0], size * 0.74 - bbox[1]),
            text,
            fill=(255, 255, 255, 180),
            font=font,
        )
    out = Image.alpha_composite(out, label)
    return out


def export_sizes(master: Image.Image, out_dir: str) -> None:
    """Write all required macOS app icon sizes."""
    os.makedirs(out_dir, exist_ok=True)
    # (filename, pixels)
    targets = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for fn, px in targets:
        resized = master.resize((px, px), Image.LANCZOS)
        resized.save(os.path.join(out_dir, fn), "PNG")
        print(f"  wrote {fn} ({px}x{px})")


CONTENTS_JSON = """{
  "images" : [
    { "filename" : "icon_16x16.png",     "idiom" : "mac", "scale" : "1x", "size" : "16x16" },
    { "filename" : "icon_16x16@2x.png",  "idiom" : "mac", "scale" : "2x", "size" : "16x16" },
    { "filename" : "icon_32x32.png",     "idiom" : "mac", "scale" : "1x", "size" : "32x32" },
    { "filename" : "icon_32x32@2x.png",  "idiom" : "mac", "scale" : "2x", "size" : "32x32" },
    { "filename" : "icon_128x128.png",   "idiom" : "mac", "scale" : "1x", "size" : "128x128" },
    { "filename" : "icon_128x128@2x.png","idiom" : "mac", "scale" : "2x", "size" : "128x128" },
    { "filename" : "icon_256x256.png",   "idiom" : "mac", "scale" : "1x", "size" : "256x256" },
    { "filename" : "icon_256x256@2x.png","idiom" : "mac", "scale" : "2x", "size" : "256x256" },
    { "filename" : "icon_512x512.png",   "idiom" : "mac", "scale" : "1x", "size" : "512x512" },
    { "filename" : "icon_512x512@2x.png","idiom" : "mac", "scale" : "2x", "size" : "512x512" }
  ],
  "info" : { "author" : "xcode", "version" : 1 }
}
"""


def main() -> None:
    asset_root = "/Users/natrix/Projects/FirstStrike/MacResources/Assets.xcassets"
    icon_set = os.path.join(asset_root, "AppIcon.appiconset")
    os.makedirs(icon_set, exist_ok=True)
    master = make_master(1024)
    master.save(os.path.join("/Users/natrix/dev/NCL/outputs", "ncl_desktop_icon_1024.png"), "PNG")
    print("wrote master at /Users/natrix/dev/NCL/outputs/ncl_desktop_icon_1024.png")
    export_sizes(master, icon_set)
    with open(os.path.join(icon_set, "Contents.json"), "w") as f:
        f.write(CONTENTS_JSON)
    with open(os.path.join(asset_root, "Contents.json"), "w") as f:
        f.write('{"info":{"author":"xcode","version":1}}\n')
    print(f"asset catalog ready at {asset_root}")


if __name__ == "__main__":
    main()
