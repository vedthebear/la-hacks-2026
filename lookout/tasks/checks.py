"""Success-check functions for each task. Pure functions: (final_url, page_text, **kwargs) -> bool.

Each task in definitions.py references one of these by name.
"""
from __future__ import annotations

import re


def _norm(s: str) -> str:
    return (s or "").strip().lower().rstrip("/")


def check_T01_browser_use_stars(final_url: str, page_text: str, **_) -> bool:
    """Agent must land on github.com/browser-use/browser-use and have a number visible near 'Stars'."""
    if "github.com/browser-use/browser-use" not in _norm(final_url):
        return False
    # PRD says: "page contains a number near the Stars label"
    return bool(re.search(r"(\d[\d,.]*\s*k?)\s*(stars?|⭐)", page_text or "", re.I))


def check_T02_wikipedia_photosynthesis(final_url: str, page_text: str, **_) -> bool:
    return "/wiki/photosynthesis" in _norm(final_url)


def check_T03_login_secure(final_url: str, page_text: str, **_) -> bool:
    return _norm(final_url).endswith("/secure")


def check_T04_saucedemo_cart_with_backpack(final_url: str, page_text: str, **_) -> bool:
    if not _norm(final_url).endswith("/cart.html"):
        return False
    return "sauce labs backpack" in (page_text or "").lower()


def check_T05_dynamic_loading_hello_world(final_url: str, page_text: str, **_) -> bool:
    return "hello world!" in (page_text or "").lower()


def check_T06_hn_top_story_title(final_url: str, page_text: str, *, agent_return: str | None = None, **_) -> bool:
    if "news.ycombinator.com" not in _norm(final_url):
        return False
    return bool((agent_return or "").strip())


def check_T07_both_checkboxes_checked(final_url: str, page_text: str, *, checkbox_states: list[bool] | None = None, **_) -> bool:
    if checkbox_states is None:
        return False
    return len(checkbox_states) >= 2 and all(checkbox_states[:2])


def check_T08_dropdown_option_2(final_url: str, page_text: str, *, selected_option: str | None = None, **_) -> bool:
    return _norm(selected_option or "") == "option 2"


def check_T09_js_confirm_clicked_ok(final_url: str, page_text: str, *, result_text: str | None = None, **_) -> bool:
    target = (result_text or page_text or "").strip().lower()
    return "you clicked: ok" in target


def check_T10_hn_top_story_points(final_url: str, page_text: str, *, agent_return: str | None = None, **_) -> bool:
    if "news.ycombinator.com" not in _norm(final_url):
        return False
    val = (agent_return or "").strip()
    if not val:
        return False
    # "any numeric value" - accept ints, e.g. "342", "342 points"
    return bool(re.search(r"\b\d+\b", val))


CHECKS: dict[str, callable] = {
    "check_T01_browser_use_stars": check_T01_browser_use_stars,
    "check_T02_wikipedia_photosynthesis": check_T02_wikipedia_photosynthesis,
    "check_T03_login_secure": check_T03_login_secure,
    "check_T04_saucedemo_cart_with_backpack": check_T04_saucedemo_cart_with_backpack,
    "check_T05_dynamic_loading_hello_world": check_T05_dynamic_loading_hello_world,
    "check_T06_hn_top_story_title": check_T06_hn_top_story_title,
    "check_T07_both_checkboxes_checked": check_T07_both_checkboxes_checked,
    "check_T08_dropdown_option_2": check_T08_dropdown_option_2,
    "check_T09_js_confirm_clicked_ok": check_T09_js_confirm_clicked_ok,
    "check_T10_hn_top_story_points": check_T10_hn_top_story_points,
}
