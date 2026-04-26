"""Tests for the verifier's JSON parser. No API calls."""
from __future__ import annotations

import pytest

from lookout.verifier import _parse_verdict_json


def test_strict_json():
    raw = '{"verdict":"pass","confidence":0.9,"reason":"clear","recommend":null}'
    out = _parse_verdict_json(raw)
    assert out["verdict"] == "pass"
    assert out["confidence"] == 0.9
    assert out["reason"] == "clear"
    assert out["recommend"] is None


def test_code_fenced_json():
    raw = '```json\n{"verdict":"fail","confidence":0.8,"reason":"no change","recommend":"try again"}\n```'
    out = _parse_verdict_json(raw)
    assert out["verdict"] == "fail"
    assert out["recommend"] == "try again"


def test_prosey_leak():
    raw = 'Looking at this, my analysis is: {"verdict":"uncertain","confidence":0.5,"reason":"unclear","recommend":"zoom in"}'
    out = _parse_verdict_json(raw)
    assert out["verdict"] == "uncertain"
    assert out["confidence"] == 0.5


def test_no_json_raises():
    with pytest.raises((ValueError, Exception)):
        _parse_verdict_json("This is just prose with no json object at all.")


def test_nested_braces_in_reason():
    raw = '{"verdict":"pass","confidence":0.95,"reason":"the field {x} is now filled","recommend":null}'
    out = _parse_verdict_json(raw)
    assert out["verdict"] == "pass"
    assert "{x}" in out["reason"]
