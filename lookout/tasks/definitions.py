"""The 10 tasks. Conforms to PLAN.md §Task suite.

Run `python -m lookout.tasks.definitions --list` to print the registered tasks.
"""
from __future__ import annotations

from .registry import Task, all_tasks, register


register(Task(
    task_id="T01",
    description=(
        "Open https://github.com/browser-use/browser-use and report the star count "
        "shown on the repository's main page. Stop after you have read the number."
    ),
    starting_url="https://github.com/browser-use/browser-use",
    success_check_name="check_T01_browser_use_stars",
    timeout_steps=12,
))

register(Task(
    task_id="T02",
    description=(
        "Open https://en.wikipedia.org and search for 'photosynthesis'. "
        "Open the article and report the first sentence."
    ),
    starting_url="https://en.wikipedia.org",
    success_check_name="check_T02_wikipedia_photosynthesis",
    timeout_steps=12,
))

register(Task(
    task_id="T03",
    description=(
        "Open https://the-internet.herokuapp.com/login. "
        "Log in with the username 'tomsmith' and the password 'SuperSecretPassword!'. "
        "Stop when you have successfully logged in."
    ),
    starting_url="https://the-internet.herokuapp.com/login",
    success_check_name="check_T03_login_secure",
    timeout_steps=10,
))

register(Task(
    task_id="T04",
    description=(
        "Open https://www.saucedemo.com. Log in as 'standard_user' with password 'secret_sauce'. "
        "Add the 'Sauce Labs Backpack' to the cart, then go to the cart page."
    ),
    starting_url="https://www.saucedemo.com",
    success_check_name="check_T04_saucedemo_cart_with_backpack",
    timeout_steps=20,
))

register(Task(
    task_id="T05",
    description=(
        "Open https://the-internet.herokuapp.com/dynamic_loading/2. "
        "Click the Start button and wait for 'Hello World!' to appear."
    ),
    starting_url="https://the-internet.herokuapp.com/dynamic_loading/2",
    success_check_name="check_T05_dynamic_loading_hello_world",
    timeout_steps=10,
))

register(Task(
    task_id="T06",
    description=(
        "Open https://news.ycombinator.com and report the title of the top story."
    ),
    starting_url="https://news.ycombinator.com",
    success_check_name="check_T06_hn_top_story_title",
    timeout_steps=10,
))

register(Task(
    task_id="T07",
    description=(
        "Open https://the-internet.herokuapp.com/checkboxes. "
        "Ensure both checkboxes are checked. Stop when both are checked."
    ),
    starting_url="https://the-internet.herokuapp.com/checkboxes",
    success_check_name="check_T07_both_checkboxes_checked",
    timeout_steps=8,
))

register(Task(
    task_id="T08",
    description=(
        "Open https://the-internet.herokuapp.com/dropdown. Select 'Option 2' from the dropdown."
    ),
    starting_url="https://the-internet.herokuapp.com/dropdown",
    success_check_name="check_T08_dropdown_option_2",
    timeout_steps=8,
))

register(Task(
    task_id="T09",
    description=(
        "Open https://the-internet.herokuapp.com/javascript_alerts. "
        "Click 'Click for JS Confirm' and accept the dialog (click OK)."
    ),
    starting_url="https://the-internet.herokuapp.com/javascript_alerts",
    success_check_name="check_T09_js_confirm_clicked_ok",
    timeout_steps=8,
))

register(Task(
    task_id="T10",
    description=(
        "Open https://news.ycombinator.com and report the points (score) of the top story."
    ),
    starting_url="https://news.ycombinator.com",
    success_check_name="check_T10_hn_top_story_points",
    timeout_steps=10,
))


def _cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Task registry")
    parser.add_argument("--list", action="store_true", help="List all registered tasks")
    args = parser.parse_args()
    if args.list:
        tasks = all_tasks()
        print(f"{len(tasks)} tasks registered:")
        for t in tasks:
            print(f"  {t.task_id:<5} | {t.description[:80]}{'...' if len(t.description) > 80 else ''}")
            print(f"        check: {t.success_check_name}, timeout_steps: {t.timeout_steps}")


if __name__ == "__main__":
    _cli()
