#!/usr/bin/env python3
"""Verify that a PNG really has a transparent background.

Exit code 0 = genuine transparency, 1 = FAIL (details on stdout), 2 = bad input.

The classic failure of "ask an image model for a transparent background" is a
checkerboard or a flat white/gray matte painted into RGB, with no alpha channel
at all. Looking at such a file in a viewer makes it look transparent, so this
check exists to catch it before the asset ships.
"""
import argparse
import sys

import numpy as np
from PIL import Image


def corner_alpha(alpha, border=6):
    """Return the highest alpha found in each corner block (0 = fully clear)."""
    h, w = alpha.shape
    b = max(1, min(border, h, w))
    return {
        "tl": int(alpha[:b, :b].max()),
        "tr": int(alpha[:b, w - b:].max()),
        "bl": int(alpha[h - b:, :b].max()),
        "br": int(alpha[h - b:, w - b:].max()),
    }


def looks_like_baked_checkerboard(rgb, alpha=None, band=0.02, min_visible=0.2):
    """Detect a two-tone gray checkerboard painted into RGB.

    Only *visible* pixels are considered. On a genuine cutout the border is
    transparent, and the RGB stored under fully transparent pixels is arbitrary
    leftover color — judging it would flag clean images. Looks at the top and
    bottom strips, keeps them only if they are essentially gray and dominated by
    two well-separated tones, then requires the tone to actually alternate along
    a scanline. A real photo border rarely does all three, which keeps the
    false-positive rate low.
    """
    h, w, _ = rgb.shape
    rows = max(1, int(h * band))
    strip = np.concatenate((rgb[:rows, :, :].reshape(-1, 3),
                            rgb[h - rows:, :, :].reshape(-1, 3)), axis=0)
    if alpha is not None:
        visible = np.concatenate((alpha[:rows, :].ravel(), alpha[h - rows:, :].ravel()),
                                 axis=0) > 8
        if visible.mean() < min_visible:
            # The border is transparent, so there is no painted background here.
            return False
        strip = strip[visible]

    saturation = (strip.max(axis=1).astype(int) - strip.min(axis=1).astype(int))
    if saturation.mean() > 12:
        return False
    lum = strip.mean(axis=1)
    quantized = np.round(lum / 8.0).astype(int)
    values, counts = np.unique(quantized, return_counts=True)
    if len(values) < 2:
        return False
    top = values[np.argsort(counts)[::-1][:2]]
    low, high = int(top.min()), int(top.max())
    if high - low < 2:
        return False
    kept = counts[np.isin(values, [low, high])].sum() / counts.sum()
    if kept < 0.85:
        return False

    line_rgb = rgb[0:max(1, rows // 2), :, :]
    if alpha is not None:
        line_alpha = alpha[0:max(1, rows // 2), :]
        weights = (line_alpha > 8)
        counts = weights.sum(axis=0)
        totals = (line_rgb.mean(axis=2) * weights).sum(axis=0)
        line = np.where(counts > 0, totals / np.maximum(counts, 1), np.nan)
        line = line[~np.isnan(line)]
    else:
        line = line_rgb.mean(axis=(0, 2))
    if line.size < 8:
        return False
    tones = (np.abs(line - low * 8) >= np.abs(line - high * 8)).astype(int)
    toggles = int(np.abs(np.diff(tones)).sum())
    return toggles >= 4


def analyze(rgba):
    """Return measurements and pass/fail reasons for an RGBA array."""
    alpha = rgba[:, :, 3]
    result = {
        "corners": corner_alpha(alpha),
        "opaque": int((alpha >= 235).sum()),
        "soft": int(((alpha > 20) & (alpha < 235)).sum()),
        "transparent": int((alpha <= 20).sum()),
        "checkerboard": bool(looks_like_baked_checkerboard(rgba[:, :, :3], alpha)),
    }
    reasons = []
    if result["transparent"] == 0:
        reasons.append("no transparent pixels: the background was not removed")
    if max(result["corners"].values()) > 8:
        reasons.append("corner alpha is not transparent")
    if result["checkerboard"]:
        reasons.append("baked checkerboard detected in RGB, not a real alpha channel")
    result["reasons"] = reasons
    result["ok"] = not reasons
    return result


def make_preview(rgba, square=16, dark=(102, 102, 102), light=(204, 204, 204)):
    """Composite over a checkerboard so genuine transparency is obvious."""
    h, w = rgba.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w]
    mask = ((ys // square) + (xs // square)) % 2 == 0
    background = np.where(mask[:, :, None], np.array(light, np.uint8),
                          np.array(dark, np.uint8)).astype(np.uint8)
    alpha = rgba[:, :, 3:4].astype(np.float32) / 255.0
    composited = rgba[:, :, :3].astype(np.float32) * alpha + background * (1 - alpha)
    return Image.fromarray(np.clip(composited, 0, 255).astype(np.uint8), "RGB")


def report(path, result, has_alpha):
    corners = result["corners"]
    total = result["opaque"] + result["soft"] + result["transparent"]
    print(f"file={path} has_alpha_channel={has_alpha}")
    print(f"corners_alpha={corners}")
    print(f"opaque={result['opaque']} soft={result['soft']} "
          f"transparent={result['transparent']} "
          f"transparent_share={result['transparent'] / max(total, 1) * 100:.1f}%")
    if not has_alpha:
        print("note: this file has no alpha channel at all; every pixel is opaque")
    for reason in result["reasons"]:
        print("reason:", reason)
    print("VERDICT:", "OK" if result["ok"] else "FAIL")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src", help="PNG (or other image) to verify")
    parser.add_argument("-o", "--out", help="write a checkerboard preview here")
    args = parser.parse_args()

    try:
        with Image.open(args.src) as image:
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {args.src}: {exc}", file=sys.stderr)
        return 2

    result = analyze(rgba)
    if not has_alpha:
        result["reasons"].insert(0, "file has no alpha channel")
        result["ok"] = False
    report(args.src, result, has_alpha)

    if args.out:
        make_preview(rgba).save(args.out)
        print("preview:", args.out)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
