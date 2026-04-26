"""Tests for pixel_diff_pct."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PIL import Image

from lookout.diffs import pixel_diff_pct


@pytest.fixture
def tmp_png(tmp_path):
    def make(size=(100, 100), color="white", name="img.png"):
        p = tmp_path / name
        Image.new("RGB", size, color).save(p)
        return p
    return make


def test_identical_returns_zero(tmp_png):
    a = tmp_png(color="white", name="a.png")
    b = tmp_png(color="white", name="b.png")
    assert pixel_diff_pct(a, b) == pytest.approx(0.0)


def test_inverted_returns_100(tmp_png):
    a = tmp_png(color="white", name="a.png")
    b = tmp_png(color="black", name="b.png")
    assert pixel_diff_pct(a, b) == pytest.approx(100.0)


def test_partial_diff_in_range(tmp_png):
    a = tmp_png(color="white", name="a.png")
    # half-half image
    b = Image.new("RGB", (100, 100), "white")
    for y in range(100):
        for x in range(50):
            b.putpixel((x, y), (0, 0, 0))
    p = a.parent / "b.png"
    b.save(p)
    pct = pixel_diff_pct(a, p)
    assert 40.0 < pct < 60.0  # ~50%


def test_missing_file_returns_zero(tmp_path):
    a = tmp_path / "nonexistent_a.png"
    b = tmp_path / "nonexistent_b.png"
    assert pixel_diff_pct(a, b) == 0.0


def test_different_sizes_resized(tmp_png):
    a = tmp_png(size=(100, 100), color="white", name="a.png")
    b = tmp_png(size=(50, 50), color="white", name="b.png")
    # Same color, different size -> resize, expect ~0
    assert pixel_diff_pct(a, b) == pytest.approx(0.0)
