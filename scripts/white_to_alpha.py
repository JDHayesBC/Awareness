#!/usr/bin/env python3
"""
white_to_alpha.py — turn a white-background image into a clean transparent PNG.

Built for the tattoo workflow: image-gen tools return art on a solid white (or
near-white) background with NO alpha channel. Second Life BOM tattoos need the
ink on transparency. This keys the background out to alpha and leaves crisp,
fringe-free ink behind.

Why it's more than `alpha = 255 - luminance`:
  * Auto-detects the REAL background color from the corners — image-gen output is
    usually off-white (248-252, sometimes faintly cream/gray), so a hard 255 test
    leaves a dirty halo.
  * Smooth ramp between a white-point and black-point → anti-aliased edges stay
    smooth instead of jagged.
  * Re-colors the ink (default solid black) so anti-aliased edge pixels don't
    carry leftover white and fringe when composited over skin. Use --keep-color
    for coloured art.
  * Floors out faint background speckle so you don't ship a field of 2%-alpha dust.

Usage:
  .venv/bin/python3 scripts/white_to_alpha.py in.png
  .venv/bin/python3 scripts/white_to_alpha.py in.png -o out.png
  .venv/bin/python3 scripts/white_to_alpha.py in.png --ink '#101010' --show
  .venv/bin/python3 scripts/white_to_alpha.py in.png --white 250 --black 60

Defaults are tuned for black-line tattoo art. Run with the project venv python
(needs Pillow + numpy): /mnt/c/Users/Jeff/Claude_Projects/Awareness/.venv/bin/python3
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def _lum(rgb):
    # perceptual luminance, rgb float 0..1
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def detect_bg_luma(lum, frac=0.06):
    """Median luminance of the four corner patches = the background level."""
    h, w = lum.shape
    ph, pw = max(1, int(h * frac)), max(1, int(w * frac))
    corners = np.concatenate([
        lum[:ph, :pw].ravel(), lum[:ph, -pw:].ravel(),
        lum[-ph:, :pw].ravel(), lum[-ph:, -pw:].ravel(),
    ])
    return float(np.median(corners))


def parse_ink(s):
    if s.lower() in ("keep", "none"):
        return None
    s = s.lstrip("#")
    if s.lower() == "black":
        return (0, 0, 0)
    if s.lower() == "white":
        return (255, 255, 255)
    if len(s) == 6:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    raise argparse.ArgumentTypeError(f"bad --ink value: {s!r} (use black|white|keep|#RRGGBB)")


def white_to_alpha(img, ink=(0, 0, 0), white=None, black=45.0,
                   auto=True, gamma=1.0, speck=8, feather=0):
    """Return an RGBA PIL image with the light background keyed to transparency."""
    rgb = np.asarray(img.convert("RGB")).astype(np.float32) / 255.0
    lum255 = _lum(rgb) * 255.0

    wp = detect_bg_luma(lum255) if (auto and white is None) else (white if white is not None else 250.0)
    wp = max(wp, black + 1.0)  # guard against degenerate range
    # coverage: 0 at/above white-point (background), 1 at/below black-point (ink)
    alpha = np.clip((wp - lum255) / (wp - black), 0.0, 1.0)
    if gamma != 1.0:
        alpha = alpha ** gamma
    if speck > 0:
        alpha[alpha < (speck / 255.0)] = 0.0  # kill background dust

    out = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    if ink is None:
        out[..., :3] = (rgb * 255).astype(np.uint8)  # preserve original colour
    else:
        out[..., :3] = np.array(ink, dtype=np.uint8)  # flat ink → no edge fringe
    out[..., 3] = (alpha * 255).astype(np.uint8)

    res = Image.fromarray(out, "RGBA")
    if feather > 0:
        from PIL import ImageFilter
        a = res.getchannel("A").filter(ImageFilter.GaussianBlur(feather))
        res.putalpha(a)
    return res, wp


def main():
    ap = argparse.ArgumentParser(description="Key a white/near-white background out to transparency.")
    ap.add_argument("input", help="input image (png/jpg/webp)")
    ap.add_argument("-o", "--output", help="output PNG (default: <input>_alpha.png)")
    ap.add_argument("--ink", type=parse_ink, default=(0, 0, 0),
                    help="ink colour: black (default) | white | keep | #RRGGBB")
    ap.add_argument("--white", type=float, default=None,
                    help="luminance (0-255) that is fully transparent; default = auto-detect from corners")
    ap.add_argument("--black", type=float, default=45.0,
                    help="luminance (0-255) at/below which ink is fully opaque (default 45)")
    ap.add_argument("--no-auto", dest="auto", action="store_false",
                    help="disable corner auto-detect; use --white as the white-point")
    ap.add_argument("--gamma", type=float, default=1.0,
                    help="curve on alpha; <1 bolder, >1 lighter (default 1.0)")
    ap.add_argument("--speck", type=int, default=8,
                    help="zero out alpha below this (0-255) to remove background dust (default 8; 0=off)")
    ap.add_argument("--feather", type=float, default=0.0,
                    help="gaussian-blur the alpha edge by N px (default 0)")
    ap.add_argument("--show", action="store_true",
                    help="composite over gray + open it (WSL→Windows) so you can see the transparency")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"no such file: {args.input}", file=sys.stderr)
        return 2
    img = Image.open(args.input)
    res, wp = white_to_alpha(img, ink=args.ink, white=args.white, black=args.black,
                             auto=args.auto, gamma=args.gamma, speck=args.speck, feather=args.feather)
    out = args.output or (os.path.splitext(args.input)[0] + "_alpha.png")
    res.save(out)
    a = np.asarray(res.getchannel("A"))
    print(f"wrote {out}  ({res.width}x{res.height})  white-point={wp:.0f}  "
          f"opaque={int((a>200).sum())}px  edge={int(((a>8)&(a<200)).sum())}px")

    if args.show:
        bg = Image.new("RGBA", res.size, (128, 128, 128, 255))
        comp = Image.alpha_composite(bg, res).convert("RGB")
        prev = os.path.splitext(out)[0] + "_preview.png"
        comp.save(prev)
        winpath = prev
        if prev.startswith("/mnt/"):
            drive = prev[5]
            winpath = f"{drive.upper()}:" + prev[6:].replace("/", "\\")
        os.system(f'powershell.exe -c "Start-Process \'{winpath}\'" >/dev/null 2>&1')
        print(f"preview (over gray): {prev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
