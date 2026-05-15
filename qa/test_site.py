import json
import os
import sys

from playwright.sync_api import sync_playwright, expect

URL = "https://project-42up2-glyaj6f03-summaya-ayazs-projects.vercel.app"
QA_DIR = os.path.dirname(os.path.abspath(__file__))
CONSOLE_LOG = os.path.join(QA_DIR, "console.log")

os.makedirs(QA_DIR, exist_ok=True)

results = []


def record(name, passed, reason=""):
    if passed:
        print(f"CRITERION | {name} | PASS")
        results.append(True)
    else:
        print(f"CRITERION | {name} | FAIL | {reason}")
        results.append(False)


def screenshot(page, index, slug):
    path = os.path.join(QA_DIR, f"{index:02d}-{slug}.png")
    page.screenshot(path=path, full_page=True)


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    log_entries = []

    def on_console(msg):
        if msg.type in ("error", "warning"):
            entry = {"type": msg.type, "text": msg.text, "location": msg.location}
            log_entries.append(entry)

    def on_pageerror(exc):
        entry = {"type": "pageerror", "text": str(exc), "location": ""}
        log_entries.append(entry)

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)

    page.goto(URL, wait_until="networkidle")
    screenshot(page, 1, "initial-load")

    # Criterion 1: h1 heading contains "Counter"
    try:
        heading = page.get_by_role("heading", level=1)
        expect(heading).to_contain_text("Counter")
        record("h1 heading contains Counter", True)
    except Exception as e:
        record("h1 heading contains Counter", False, str(e))

    # Criterion 2: Initial counter value is 0
    try:
        counter = page.get_by_test_id("counter-value")
        expect(counter).to_have_text("0")
        record("Initial counter value is 0", True)
    except Exception as e:
        record("Initial counter value is 0", False, str(e))

    # Criterion 3: Increment button increases counter by 1
    try:
        page.get_by_test_id("increment-btn").click()
        counter = page.get_by_test_id("counter-value")
        expect(counter).to_have_text("1")
        screenshot(page, 2, "after-increment")
        record("Increment button increases counter by 1", True)
    except Exception as e:
        screenshot(page, 2, "after-increment-fail")
        record("Increment button increases counter by 1", False, str(e))

    # Criterion 4: Decrement button decreases counter by 1
    try:
        # Ensure we start from a known state: click increment to get to 2, then decrement to 1
        page.get_by_test_id("increment-btn").click()
        page.get_by_test_id("decrement-btn").click()
        counter = page.get_by_test_id("counter-value")
        expect(counter).to_have_text("1")
        screenshot(page, 3, "after-decrement")
        record("Decrement button decreases counter by 1", True)
    except Exception as e:
        screenshot(page, 3, "after-decrement-fail")
        record("Decrement button decreases counter by 1", False, str(e))

    # Criterion 5: Reset button sets counter back to 0
    try:
        page.get_by_test_id("increment-btn").click()
        page.get_by_test_id("increment-btn").click()
        page.get_by_test_id("reset-btn").click()
        counter = page.get_by_test_id("counter-value")
        expect(counter).to_have_text("0")
        screenshot(page, 4, "after-reset")
        record("Reset button sets counter to 0", True)
    except Exception as e:
        screenshot(page, 4, "after-reset-fail")
        record("Reset button sets counter to 0", False, str(e))

    # Criterion 6: Counter persists across page reloads via localStorage key "counter"
    try:
        page.get_by_test_id("increment-btn").click()
        page.get_by_test_id("increment-btn").click()
        page.get_by_test_id("increment-btn").click()
        expected_value = page.get_by_test_id("counter-value").inner_text().strip()

        stored = page.evaluate("localStorage.getItem('counter')")
        assert stored is not None, "localStorage key 'counter' not found"
        assert str(stored) == str(expected_value), (
            f"localStorage value '{stored}' does not match displayed '{expected_value}'"
        )

        page.reload(wait_until="networkidle")
        screenshot(page, 5, "after-reload")

        counter = page.get_by_test_id("counter-value")
        expect(counter).to_have_text(expected_value)
        record("Counter persists across page reloads via localStorage", True)
    except Exception as e:
        screenshot(page, 5, "after-reload-fail")
        record("Counter persists across page reloads via localStorage", False, str(e))

    browser.close()

    with open(CONSOLE_LOG, "w") as f:
        for entry in log_entries:
            f.write(json.dumps(entry) + "\n")

overall = all(results)
print("OVERALL: PASS" if overall else "OVERALL: FAIL")
sys.exit(0)
