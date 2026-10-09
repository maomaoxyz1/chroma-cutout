#!/usr/bin/env python3
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPT = Path(__file__).parents[1] / "scripts" / "alpha_check.py"
_spec = importlib.util.spec_from_file_location("alpha_check", SCRIPT)
alpha_check = importlib.util.module_from_spec(_spec)
sys.modules["alpha_check"] = alpha_check
_spec.loader.exec_module(alpha_check)


def checkerboard(size=(64, 64), square=8, tones=(102, 204)):
    h, w = size
    ys, xs = np.mgrid[0:h, 0:w]
    mask = ((ys // square) + (xs // square)) % 2 == 0
    rgb = np.where(mask[:, :, None], tones[0], tones[1]).astype(np.uint8)
    return np.repeat(rgb, 3, axis=2)


class AnalyzeTests(unittest.TestCase):
    def test_clean_cutout_passes(self):
        rgba = np.zeros((64, 64, 4), dtype=np.uint8)
        rgba[20:44, 20:44] = [200, 120, 90, 255]

        result = alpha_check.analyze(rgba)

        self.assertTrue(result["ok"], result["reasons"])
        self.assertEqual(result["transparent"] + result["opaque"], 64 * 64)

    def test_flat_opaque_image_fails(self):
        rgba = np.full((64, 64, 4), [30, 40, 50, 255], dtype=np.uint8)

        result = alpha_check.analyze(rgba)

        self.assertFalse(result["ok"])
        self.assertIn("no transparent pixels: the background was not removed",
                      result["reasons"])

    def test_baked_checkerboard_is_detected(self):
        rgb = checkerboard()
        self.assertTrue(alpha_check.looks_like_baked_checkerboard(rgb))

        rgba = np.dstack((rgb, np.full((64, 64), 255, dtype=np.uint8)))
        result = alpha_check.analyze(rgba)

        self.assertFalse(result["ok"])
        self.assertTrue(result["checkerboard"])

    def test_colorful_border_is_not_called_a_checkerboard(self):
        rgb = np.zeros((64, 64, 3), dtype=np.uint8)
        rgb[:4] = [10, 200, 40]
        rgb[-4:] = [240, 60, 20]
        rgb[:, :4] = [20, 30, 220]
        rgb[:, -4:] = [250, 200, 10]

        self.assertFalse(alpha_check.looks_like_baked_checkerboard(rgb))

    def test_transparent_border_with_leftover_rgb_is_not_flagged(self):
        # Regression: on a real cutout the border is fully transparent and its
        # RGB is arbitrary leftover color. Judging it produced a false FAIL.
        rgb = checkerboard()
        alpha = np.zeros((64, 64), dtype=np.uint8)
        alpha[24:40, 24:40] = 255
        rgba = np.dstack((rgb, alpha))

        result = alpha_check.analyze(rgba)

        self.assertFalse(result["checkerboard"])
        self.assertTrue(result["ok"], result["reasons"])

    def test_photo_like_gray_border_is_not_a_checkerboard(self):
        rng = np.random.default_rng(7)
        rgb = rng.integers(90, 210, (64, 64, 3), dtype=np.uint8)
        rgb[:, :, 1] = rgb[:, :, 0]
        rgb[:, :, 2] = rgb[:, :, 0]

        self.assertFalse(alpha_check.looks_like_baked_checkerboard(rgb))

    def test_opaque_corner_fails_even_with_some_transparency(self):
        rgba = np.zeros((64, 64, 4), dtype=np.uint8)
        rgba[0:6, 0:6] = [10, 10, 10, 255]

        result = alpha_check.analyze(rgba)

        self.assertFalse(result["ok"])
        self.assertIn("corner alpha is not transparent", result["reasons"])


class CommandLineTests(unittest.TestCase):
    def run_check(self, image, tmp, name="in.png"):
        path = Path(tmp) / name
        image.save(path)
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(path)],
            capture_output=True, text=True, check=False,
        )

    def test_rgb_file_without_alpha_fails_with_explicit_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_check(Image.new("RGB", (32, 32), (12, 34, 56)), tmp)

        self.assertEqual(result.returncode, 1)
        self.assertIn("has_alpha_channel=False", result.stdout)
        self.assertIn("VERDICT: FAIL", result.stdout)

    def test_transparent_png_exits_zero(self):
        rgba = np.zeros((32, 32, 4), dtype=np.uint8)
        rgba[10:22, 10:22] = [5, 5, 5, 255]
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_check(Image.fromarray(rgba, "RGBA"), tmp)

        self.assertEqual(result.returncode, 0)
        self.assertIn("VERDICT: OK", result.stdout)

    def test_preview_is_written(self):
        rgba = np.zeros((32, 32, 4), dtype=np.uint8)
        rgba[10:22, 10:22] = [5, 5, 5, 255]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.png"
            out = Path(tmp) / "preview.png"
            Image.fromarray(rgba, "RGBA").save(src)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(src), "-o", str(out)],
                capture_output=True, text=True, check=False,
            )
            self.assertTrue(out.exists())
            preview = np.asarray(Image.open(out).convert("RGB"))
            # the transparent area must show the checkerboard, not a flat color
            corner = preview[0:32, 0:32].reshape(-1, 3)
            self.assertGreater(len(np.unique(corner, axis=0)), 1)
            self.assertFalse(
                np.array_equal(preview[0, 0], preview[0, 20]),
                "adjacent checker squares should differ",
            )

        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
