import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect, TimeoutError as PWTimeoutError

URL = "https://project-42up2-hkmof4j0v-summaya-ayazs-projects.vercel.app"
QA_DIR = Path(__file__).resolve().parent
QA_DIR.mkdir(parents=True, exist_ok=True)
CONSOLE_LOG = QA_DIR / "console.log"

results = []
shot_counter = {"n": 0}


def shot(page, slug):
    shot_counter["n"] += 1
    n = f"{shot_counter['n']:02d}"
    path = QA_DIR / f"{n}-{slug}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception as e:
        print(f"screenshot failed for {slug}: {e}", file=sys.stderr)


def log_console(entry):
    try:
        with CONSOLE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def record(name, ok, reason=""):
    if ok:
        print(f"CRITERION | {name} | PASS")
        results.append(True)
    else:
        print(f"CRITERION | {name} | FAIL | {reason}")
        results.append(False)


def run_criterion(name, fn):
    try:
        fn()
        record(name, True)
    except AssertionError as e:
        record(name, False, str(e).replace("\n", " ")[:300])
    except Exception as e:
        record(name, False, f"{type(e).__name__}: {str(e).replace(chr(10), ' ')[:300]}")


def main():
    # Reset console log
    try:
        if CONSOLE_LOG.exists():
            CONSOLE_LOG.unlink()
    except Exception:
        pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_console(msg):
            try:
                t = msg.type
                if t in ("error", "warning"):
                    loc = ""
                    try:
                        l = msg.location
                        loc = f"{l.get('url','')}:{l.get('lineNumber','')}:{l.get('columnNumber','')}"
                    except Exception:
                        loc = ""
                    log_console({"type": t, "text": msg.text, "location": loc})
            except Exception:
                pass

        def on_pageerror(err):
            log_console({"type": "pageerror", "text": str(err), "location": ""})

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)

        try:
            page.goto(URL, wait_until="networkidle", timeout=60000)
        except PWTimeoutError:
            try:
                page.goto(URL, wait_until="load", timeout=60000)
            except Exception as e:
                print(f"Failed to navigate: {e}", file=sys.stderr)

        shot(page, "initial-load")

        counter = page.get_by_test_id("counter-value")
        inc = page.get_by_test_id("increment-btn")
        dec = page.get_by_test_id("decrement-btn")
        reset = page.get_by_test_id("reset-btn")

        # Ensure clean state for tests that depend on it
        try:
            page.evaluate("() => { try { localStorage.removeItem('counter'); } catch(e){} }")
            page.reload(wait_until="networkidle", timeout=60000)
        except Exception:
            pass

        shot(page, "post-clear-reload")

        # Criterion 1: initial counter value is 0
        def c1():
            expect(counter).to_be_visible(timeout=10000)
            expect(counter).to_have_text("0", timeout=10000)
        run_criterion("initial-counter-zero", c1)

        # Criterion 2: h1 contains "Counter"
        def c2():
            h1 = page.locator("h1").first
            expect(h1).to_be_visible(timeout=10000)
            expect(h1).to_contain_text("Counter", timeout=10000)
        run_criterion("h1-contains-counter", c2)

        # Criterion 3: increment increases by 1
        def c3():
            inc.click()
            expect(counter).to_have_text("1", timeout=10000)
            inc.click()
            expect(counter).to_have_text("2", timeout=10000)
        run_criterion("increment-button", c3)
        shot(page, "after-increment")

        # Criterion 4: decrement decreases by 1
        def c4():
            dec.click()
            expect(counter).to_have_text("1", timeout=10000)
        run_criterion("decrement-button", c4)
        shot(page, "after-decrement")

        # Criterion 5: reset sets to 0
        def c5():
            reset.click()
            expect(counter).to_have_text("0", timeout=10000)
        run_criterion("reset-button", c5)
        shot(page, "after-reset")

        # Criterion 6: persists across reload via localStorage 'counter'
        def c6():
            inc.click()
            inc.click()
            inc.click()
            expect(counter).to_have_text("3", timeout=10000)
            stored = page.evaluate("() => localStorage.getItem('counter')")
            assert stored is not None, "localStorage 'counter' is null"
            # Could be stored as string "3" or JSON 3
            normalized = str(stored).strip().strip('"')
            assert normalized == "3", f"localStorage counter expected '3', got {stored!r}"
            page.reload(wait_until="networkidle", timeout=60000)
            expect(page.get_by_test_id("counter-value")).to_have_text("3", timeout=10000)
        run_criterion("persists-via-localStorage", c6)
        shot(page, "after-reload-persistence")

        context.close()
        browser.close()

    overall = "PASS" if results and all(results) else "FAIL"
    print(f"OVERALL: {overall}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        print("OVERALL: FAIL")
        sys.exit(0)
