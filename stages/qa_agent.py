"""QA stage: Claude Code writes a Playwright script, runs it, then writes bug-report.md."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class QAError(RuntimeError):
    pass


WRITE_PLAYWRIGHT_PROMPT_TEMPLATE = """You are an autonomous QA engineer. Write a Python file at `qa/test_site.py`
that uses `playwright.sync_api` to test the deployed web application live in a real browser.

LIVE DEPLOYMENT URL:
{url}

ACCEPTANCE CRITERIA (from requirements.md):
=== BEGIN REQUIREMENTS ===
{requirements}
=== END REQUIREMENTS ===

STRICT RULES:
- The script MUST be self-contained and runnable as: `python qa/test_site.py`.
- Use the Chromium browser via `sync_playwright`. Headless mode.
- Navigate to the URL above. Wait for the network to be idle before asserting.
- Subscribe to `page.on("console", ...)` and `page.on("pageerror", ...)` BEFORE navigation.
  Append every console message of type "error" / "warning" and every page error to `qa/console.log`
  (one JSON-line per entry: {{"type": ..., "text": ..., "location": ...}}).
- For EACH acceptance criterion, perform the user action and assert the observable outcome
  using `expect(...)` from `playwright.sync_api`. Use `locator.get_by_role`, `get_by_text`,
  or `data-testid` selectors. Avoid brittle CSS selectors.
- After each meaningful state, call `page.screenshot(path="qa/<n>-<slug>.png", full_page=True)`
  where `<n>` is a zero-padded order index starting at 01 and `<slug>` is a kebab-case label.
- Print a single line per criterion in this exact format:
  `CRITERION | <name> | PASS` or `CRITERION | <name> | FAIL | <reason>`
- At the very end, print exactly one of:
  `OVERALL: PASS` or `OVERALL: FAIL`
- Catch assertion errors PER criterion so one failure does not stop the others.
  Use try/except around each criterion's assertions.
- Exit code MUST be 0 even when criteria fail (the orchestrator parses the printed lines).
- Create the `qa/` directory if it does not exist.
- Do NOT install Playwright. Assume `playwright` and chromium browsers are already installed.
- Do not output prose — just write the file `qa/test_site.py`.
"""


WRITE_BUG_REPORT_PROMPT_TEMPLATE = """You are a QA reporter. Read the QA artifacts in the current directory and produce
a single Markdown file named `bug-report.md` summarising the results.

INPUTS:
- `qa/run.log`   — combined stdout/stderr from running the Playwright script.
- `qa/console.log` — browser console + pageerror events (one JSON per line).
- `qa/` PNG screenshots taken during the run.
- `requirements.md` — the acceptance criteria source of truth.
- The live deployment URL: {url}

REQUIRED STRUCTURE for `bug-report.md`:

# QA Report — {key}

**Deployment:** {url}

## Result table
| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | ...       | PASS / FAIL | screenshot file or note |
...

## Browser console errors
(Bulleted list. If none, say "None observed.")

## Screenshots
(Bulleted list of files in qa/ with a one-line caption each.)

## Summary
(2–4 sentences in plain English describing what works and what does not.)

## OVERALL
Write EXACTLY one of these lines on its own:
`OVERALL: PASS` or `OVERALL: FAIL`

Rules:
- The overall verdict is PASS only if every row in the result table is PASS AND there are no fatal browser errors.
- Parse the `CRITERION | ... | PASS/FAIL` lines from `qa/run.log` to populate the table.
- Do not invent criteria not present in `requirements.md`.
- Do not output prose outside `bug-report.md`. Write the file directly.
"""


def _claude(work_dir: Path, prompt: str, *, what: str, timeout: int = 600) -> str:
    log.info("QA: claude %s", what)
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
        raise QAError(
            f"Claude Code ({what}) failed rc={result.returncode}\n"
            f"STDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout[-2000:]}"
        )
    return result.stdout


def run_qa(work_dir: Path, jira_key: str, live_url: str) -> dict:
    """Generate Playwright script, run it, generate bug-report.md. Returns result metadata."""
    if shutil.which("claude") is None:
        raise QAError("`claude` CLI not on PATH.")
    if shutil.which("python") is None and shutil.which("python3") is None:
        raise QAError("python not on PATH.")

    requirements_path = work_dir / "requirements.md"
    if not requirements_path.exists():
        raise QAError("requirements.md missing in workspace")
    requirements = requirements_path.read_text(errors="replace")

    qa_dir = work_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    # Reset run artifacts so reports reflect this run only.
    for stale in qa_dir.glob("*.png"):
        stale.unlink()
    for fname in ("run.log", "console.log"):
        p = qa_dir / fname
        if p.exists():
            p.unlink()

    # Step 1 — write the Playwright script.
    _claude(
        work_dir,
        WRITE_PLAYWRIGHT_PROMPT_TEMPLATE.format(url=live_url, requirements=requirements.strip()),
        what="write qa/test_site.py",
        timeout=600,
    )
    script = work_dir / "qa" / "test_site.py"
    if not script.exists():
        raise QAError("Claude Code did not produce qa/test_site.py")

    # Step 2 — run the Playwright script.
    python_bin = shutil.which("python") or shutil.which("python3")
    log.info("QA: running qa/test_site.py")
    proc = subprocess.run(
        [python_bin, "qa/test_site.py"],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=900,
    )
    combined = (
        f"--- exit code: {proc.returncode} ---\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}\n"
    )
    (qa_dir / "run.log").write_text(combined)
    if not (qa_dir / "console.log").exists():
        (qa_dir / "console.log").write_text("")
    log.info("QA: Playwright run finished (exit=%d, log=%s)", proc.returncode, qa_dir / "run.log")

    # Step 3 — generate bug-report.md
    _claude(
        work_dir,
        WRITE_BUG_REPORT_PROMPT_TEMPLATE.format(url=live_url, key=jira_key),
        what="write bug-report.md",
        timeout=600,
    )
    report_path = work_dir / "bug-report.md"
    if not report_path.exists():
        raise QAError("Claude Code did not produce bug-report.md")

    report_text = report_path.read_text(errors="replace")
    passed = _verdict_from_report(report_text, combined)
    screenshots = sorted(p for p in qa_dir.glob("*.png"))

    log.info("QA: verdict=%s screenshots=%d", "PASS" if passed else "FAIL", len(screenshots))
    return {
        "passed": passed,
        "report_path": str(report_path),
        "report_text": report_text,
        "screenshots": [str(p) for p in screenshots],
        "run_log_path": str(qa_dir / "run.log"),
    }


def _verdict_from_report(report_text: str, run_log: str) -> bool:
    """Determine PASS/FAIL. Trust 'OVERALL: PASS' in the report; fall back to run log."""
    rt = report_text.upper()
    if "OVERALL: PASS" in rt:
        return True
    if "OVERALL: FAIL" in rt:
        return False
    rl = run_log.upper()
    if "OVERALL: PASS" in rl:
        return True
    return False
