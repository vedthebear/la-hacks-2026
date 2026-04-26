"""Tests for the task registry + check coverage."""
from __future__ import annotations

import pytest

from lookout.tasks import all_tasks, get
from lookout.tasks.checks import CHECKS


def test_ten_tasks_registered():
    tasks = all_tasks()
    ids = [t.task_id for t in tasks]
    assert len(tasks) == 10
    assert ids == [f"T{i:02d}" for i in range(1, 11)]


def test_every_task_has_a_check():
    for t in all_tasks():
        assert t.success_check_name in CHECKS, f"{t.task_id} -> missing {t.success_check_name}"


def test_get_unknown_task_raises():
    with pytest.raises(KeyError):
        get("T99")


def test_check_T01_pass_case():
    assert CHECKS["check_T01_browser_use_stars"](
        "https://github.com/browser-use/browser-use",
        "Browser Use · 12.3k stars · 1.2k forks",
    )


def test_check_T01_wrong_url_fails():
    assert not CHECKS["check_T01_browser_use_stars"](
        "https://github.com/some-other/repo",
        "12.3k stars",
    )


def test_check_T03_secure_url_pass():
    assert CHECKS["check_T03_login_secure"]("https://the-internet.herokuapp.com/secure", "")
    assert CHECKS["check_T03_login_secure"]("https://the-internet.herokuapp.com/secure/", "")


def test_check_T03_login_url_fails():
    assert not CHECKS["check_T03_login_secure"]("https://the-internet.herokuapp.com/login", "")


def test_check_T08_dropdown_option_2():
    assert CHECKS["check_T08_dropdown_option_2"]("", "", selected_option="Option 2")
    assert not CHECKS["check_T08_dropdown_option_2"]("", "", selected_option="Option 1")
    assert not CHECKS["check_T08_dropdown_option_2"]("", "", selected_option=None)


def test_check_T10_numeric_required():
    assert CHECKS["check_T10_hn_top_story_points"]("https://news.ycombinator.com", "", agent_return="342 points")
    assert not CHECKS["check_T10_hn_top_story_points"]("https://news.ycombinator.com", "", agent_return="")
    assert not CHECKS["check_T10_hn_top_story_points"]("https://example.com", "", agent_return="100")
