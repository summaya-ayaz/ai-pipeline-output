"""Test stage: Claude Code writes Jest tests, npx jest runs them, Claude Code fixes failures."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

MAX_FIX_ITERATIONS = 5


class TestError(RuntimeError):
    pass


PACKAGE_JSON = {
    "name": "ai-pipeline-workspace",
    "version": "1.0.0",
    "private": True,
    "scripts": {"test": "jest --json"},
    "jest": {"testEnvironment": "jsdom"},
}


WRITE_TESTS_PROMPT = """You are an autonomous QA engineer. Write a Jest unit test file named `index.test.js`
that validates the web application defined in `index.html` in the current directory.

STRICT RULES:
- Use Jest's jsdom environment (it is already configured in package.json).
- Read `index.html` with `fs.readFileSync` and inject its body into `document.body.innerHTML`.
- Re-execute any `<script>` blocks inside index.html so that the app's JavaScript runs against the JSDOM.
- Cover EVERY acceptance criterion listed in `requirements.md` in the same directory.
- Use `document.querySelector` with the `id` / `data-testid` attributes that exist in `index.html`.
- Use `beforeEach` to reset `document.body.innerHTML` and `localStorage` between tests.
- Do NOT use any browser-only APIs that JSDOM does not support (no canvas drawing, no fetch network calls).
- Mock `window.alert`, `window.confirm`, and `window.prompt` when the app uses them.
- Tests must be deterministic, no random data, no network calls.
- Output ONLY the file `index.test.js`. Do not modify `index.html` or any other file.
- Do not output prose — just write the file.

When done, `index.test.js` MUST exist in the current working directory and be a valid Jest test file.
"""


FIX_PROMPT_TEMPLATE = """The Jest test suite for `index.html` is FAILING. Your task is to fix `index.html` so that ALL tests pass.

STRICT RULES:
- Modify ONLY `index.html`. Do NOT modify `index.test.js`.
- Keep the app self-contained (single file, inline CSS/JS, vanilla JavaScript only).
- After your fix, every existing test must pass.
- Do not output prose — just write the corrected `index.html`.

=== JEST FAILURE OUTPUT (iteration {iteration}) ===
{failures}
=== END FAILURE OUTPUT ===

Now rewrite `index.html` so the tests pass.
"""


def _ensure_jest_installed(work_dir: Path) -> None:
    pkg = work_dir / "package.json"
    if not pkg.exists():
        pkg.write_text(json.dumps(PACKAGE_JSON, indent=2))
    node_modules = work_dir / "node_modules"
    if (node_modules / "jest").exists() and (node_modules / "jest-environment-jsdom").exists():
        return
    log.info("Test: installing jest + jest-environment-jsdom in %s", work_dir)
    result = subprocess.run(
        ["npm", "install", "--silent", "--no-audit", "--no-fund",
         "jest@^29", "jest-environment-jsdom@^29", "jsdom@^24"],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise TestError(f"npm install failed:\n{result.stderr}\n{result.stdout}")


def _claude(work_dir: Path, prompt: str, *, what: str, timeout: int = 600) -> str:
    log.info("Test: claude %s", what)
    result = subprocess.run(
        ["claude", "--print",
         "--permission-mode", "acceptEdits",
         prompt],
        capture_output=True,
        text=True,
        cwd=str(work_dir),
        timeout=timeout,
    )
    if result.returncode != 0:
        raise TestError(
            f"Claude Code ({what}) failed rc={result.returncode}\n"
            f"STDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout[-2000:]}"
        )
    return result.stdout


def _run_jest(work_dir: Path) -> tuple[bool, dict, str]:
    """Run npx jest --json. Returns (passed, parsed_json, raw_combined_output)."""
    result = subprocess.run(
        ["npx", "--yes", "jest", "--json"],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=600,
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    # Jest --json writes JSON to stdout. Locate the JSON object boundary.
    parsed: dict = {}
    stdout = result.stdout or ""
    start = stdout.find("{")
    if start != -1:
        try:
            parsed = json.loads(stdout[start:])
        except json.JSONDecodeError:
            parsed = {}
    if not parsed:
        # jest exit code != 0 with no parseable JSON means setup error.
        return False, {}, combined
    passed = bool(parsed.get("success")) and parsed.get("numFailedTests", 0) == 0
    return passed, parsed, combined


def _summarize_failures(parsed: dict, raw: str) -> str:
    if not parsed:
        return raw[-8000:]
    lines: list[str] = []
    lines.append(
        f"Totals: tests={parsed.get('numTotalTests', 0)} "
        f"passed={parsed.get('numPassedTests', 0)} "
        f"failed={parsed.get('numFailedTests', 0)} "
        f"suites_failed={parsed.get('numFailedTestSuites', 0)}"
    )
    for suite in parsed.get("testResults", []) or []:
        if suite.get("status") != "passed":
            lines.append(f"\nSUITE: {suite.get('name')}")
            msg = suite.get("message") or ""
            if msg.strip():
                lines.append(msg.strip()[:4000])
        for tc in suite.get("assertionResults", []) or []:
            if tc.get("status") != "passed":
                lines.append(f"  ✗ {tc.get('fullName') or tc.get('title')}")
                for m in (tc.get("failureMessages") or [])[:3]:
                    lines.append("    " + m.replace("\n", "\n    ")[:2000])
    out = "\n".join(lines)
    return out if out.strip() else raw[-8000:]


def _human_summary(parsed: dict, passed: bool, raw: str) -> str:
    if not parsed:
        return f"Jest produced no parseable JSON. Raw output:\n{raw[-4000:]}"
    head = (
        f"Result: {'PASS' if passed else 'FAIL'}\n"
        f"Total tests: {parsed.get('numTotalTests', 0)}\n"
        f"Passed: {parsed.get('numPassedTests', 0)}\n"
        f"Failed: {parsed.get('numFailedTests', 0)}\n"
        f"Failed suites: {parsed.get('numFailedTestSuites', 0)}\n"
        f"Time: {parsed.get('startTime')}\n\n"
    )
    cases: list[str] = []
    for suite in parsed.get("testResults", []) or []:
        for tc in suite.get("assertionResults", []) or []:
            mark = "✓" if tc.get("status") == "passed" else "✗"
            cases.append(f"  {mark} {tc.get('fullName') or tc.get('title')}")
    return head + "\n".join(cases) + "\n"


def run_tests(work_dir: Path) -> dict:
    """Drive the write-tests / run / fix loop. Returns final parsed Jest result on success."""
    if shutil.which("npx") is None:
        raise TestError("`npx` not found on PATH. Install Node.js 20+ and npm.")
    if shutil.which("claude") is None:
        raise TestError("`claude` CLI not found on PATH. Run `npm install -g @anthropic-ai/claude-code` and `claude login`.")

    _ensure_jest_installed(work_dir)

    # Step 1: write tests
    _claude(work_dir, WRITE_TESTS_PROMPT, what="write index.test.js", timeout=600)
    test_file = work_dir / "index.test.js"
    if not test_file.exists():
        raise TestError("Claude Code did not produce index.test.js")

    # Step 2: run / fix loop
    last_parsed: dict = {}
    last_raw: str = ""
    last_passed = False
    for i in range(1, MAX_FIX_ITERATIONS + 1):
        log.info("Test: jest run iteration %d/%d", i, MAX_FIX_ITERATIONS)
        passed, parsed, raw = _run_jest(work_dir)
        last_parsed, last_raw, last_passed = parsed, raw, passed
        if passed:
            (work_dir / "test-results.txt").write_text(_human_summary(parsed, True, raw))
            log.info("Test: all tests passed on iteration %d", i)
            return parsed
        failures = _summarize_failures(parsed, raw)
        if i == MAX_FIX_ITERATIONS:
            break
        _claude(
            work_dir,
            FIX_PROMPT_TEMPLATE.format(iteration=i, failures=failures),
            what=f"fix index.html (iteration {i})",
            timeout=900,
        )

    (work_dir / "test-results.txt").write_text(_human_summary(last_parsed, last_passed, last_raw))
    raise TestError(
        f"Tests still failing after {MAX_FIX_ITERATIONS} fix iterations. "
        f"See {work_dir / 'test-results.txt'}."
    )
