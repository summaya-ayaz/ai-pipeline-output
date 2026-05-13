"""Zero Human Touch Pipeline orchestrator.

Cron-driven main loop: every 5 minutes polls Jira for stories with label `ai-ready`
in status `To Do`, then runs the full Build → Test → GitHub → Vercel → QA → Email →
Close-loop pipeline for each one. Every story is transitioned to a terminal state —
never left stuck in `In Progress`.

Run as:
    python pipeline.py            # start the cron loop
    python pipeline.py --once     # poll + run a single pass and exit
    python pipeline.py --issue PJC-12   # run the pipeline for a specific Jira key

Authentication: Claude Code authenticates via `claude login` (run once, manually).
No ANTHROPIC_API_KEY is used.
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import traceback
from pathlib import Path

import schedule
import time
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
WORKSPACE_ROOT = ROOT / "workspace"

load_dotenv(ROOT / ".env")

LOG_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


def _setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_h = logging.handlers.RotatingFileHandler(
        LOG_DIR / "pipeline.log", maxBytes=5_000_000, backupCount=5
    )
    file_h.setFormatter(fmt)
    stream_h = logging.StreamHandler(sys.stdout)
    stream_h.setFormatter(fmt)
    root.addHandler(file_h)
    root.addHandler(stream_h)


_setup_logging()
log = logging.getLogger("pipeline")

# Import stages AFTER load_dotenv so module-level env reads work.
from stages import jira as jira_stage           # noqa: E402
from stages import build_agent                   # noqa: E402
from stages import test_runner                   # noqa: E402
from stages import github as github_stage        # noqa: E402
from stages import vercel as vercel_stage        # noqa: E402
from stages import qa_agent                       # noqa: E402
from stages import email_report                   # noqa: E402
from stages.human_log import HumanLog             # noqa: E402


PROCESSED_KEYS: set[str] = set()


def _workspace_for(key: str) -> Path:
    p = WORKSPACE_ROOT / key
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_jira_comment(key: str, body: str) -> None:
    try:
        jira_stage.comment(key, body)
    except Exception:  # noqa: BLE001
        log.exception("Could not post Jira comment for %s", key)


def _safe_jira_transition(key: str, target: str) -> None:
    try:
        jira_stage.transition_issue(key, target)
    except Exception:  # noqa: BLE001
        log.exception("Could not transition %s to %s", key, target)


def run_pipeline_for_issue(issue: dict) -> None:
    """Run all stages for one issue. Always finishes in a terminal Jira state."""
    key = issue["key"]
    summary = jira_stage.summary_of(issue) or key
    work_dir = _workspace_for(key)
    hlog = HumanLog(key, summary, LOG_DIR, total_stages=8)

    log.info("=== START %s — %s ===", key, summary)
    current_stage = "init"
    final_verdict = "ERROR"
    try:
        # ---- Stage 1: Jira fetch ----
        current_stage = "jira-fetch"
        hlog.begin_stage("Jira fetch", "Download requirements.md and move story to In Progress.")
        hlog.step(f"Searching Jira issue {key} for requirements.md attachment")
        req_path = jira_stage.download_requirements(issue, work_dir)
        hlog.step(f"Saved requirements.md ({req_path.stat().st_size} bytes) to {req_path.relative_to(ROOT)}")
        hlog.step("Transitioning Jira: To Do → In Progress")
        _safe_jira_transition(key, "In Progress")
        requirements = req_path.read_text(errors="replace")
        hlog.end_stage("PASS", "Jira fetch complete")

        # ---- Stage 2: build ----
        current_stage = "build"
        hlog.begin_stage("Build", "Claude Code CLI writes index.html from requirements.md.")
        hlog.step("Invoking `claude --print --permission-mode acceptEdits`")
        build_agent.build_app(work_dir, requirements)
        idx = work_dir / "index.html"
        hlog.step(f"Generated index.html ({idx.stat().st_size} bytes)")
        hlog.end_stage("PASS", "Application built")

        # ---- Stage 3: tests ----
        current_stage = "tests"
        hlog.begin_stage("Tests", "Claude writes Jest tests; npx jest runs; up to 5 fix iterations.")
        hlog.step("Ensuring jest + jest-environment-jsdom are installed in workspace")
        hlog.step("Asking Claude to author index.test.js against requirements.md")
        hlog.step("Running `npx jest --json` (may iterate on failures)")
        test_result = test_runner.run_tests(work_dir)
        hlog.step(
            f"Tests passed: {test_result.get('numPassedTests', 0)}/"
            f"{test_result.get('numTotalTests', 0)}"
        )
        hlog.end_stage("PASS", "All Jest tests green")

        # ---- Stage 4: GitHub ----
        current_stage = "github"
        hlog.begin_stage("GitHub", "Create feature branch, push artifacts, open PR.")
        hlog.step("Cloning / refreshing repo-clone working tree")
        gh = github_stage.push_and_open_pr(work_dir, key, summary)
        hlog.step(f"Pushed branch: {gh['branch']}")
        hlog.step(f"PR opened: {gh.get('pr_url')}")
        hlog.step("Transitioning Jira: In Progress → In Review")
        _safe_jira_transition(key, "In Review")
        hlog.end_stage("PASS", f"PR #{gh.get('pr_number')} is open")

        # ---- Stage 5: Vercel ----
        current_stage = "vercel"
        hlog.begin_stage("Vercel", "Deploy the branch, wait for READY, health-check the URL.")
        hlog.step("Creating deployment via POST /v13/deployments")
        dep = vercel_stage.deploy(gh["branch"], gh["commit_sha"])
        live_url = dep["url"]
        hlog.step(f"Deployment READY: {live_url}")
        hlog.step("Health check returned HTTP 200")
        hlog.step("Transitioning Jira: In Review → QA")
        _safe_jira_transition(key, "QA")
        hlog.end_stage("PASS", "Live preview is reachable")

        # ---- Stage 6: QA ----
        current_stage = "qa"
        hlog.begin_stage("QA", "Claude writes Playwright tests; runs them; produces bug-report.md.")
        hlog.step("Generating qa/test_site.py with assertions per acceptance criterion")
        hlog.step("Running headless Chromium against live URL")
        qa = qa_agent.run_qa(work_dir, key, live_url)
        hlog.step(f"Captured {len(qa.get('screenshots') or [])} screenshot(s) in qa/")
        hlog.step(f"Bug report written: {qa.get('report_path')}")
        verdict = "PASS" if qa["passed"] else "FAIL"
        hlog.end_stage(verdict, "QA verdict from bug-report.md")

        # ---- Stage 7: email ----
        current_stage = "email"
        hlog.begin_stage("Email", "Send styled HTML QA report with PNG attachments via SendGrid.")
        hlog.step(f"Sending {verdict} report to {os.environ.get('EMAIL_TO', '<unset>')}")
        try:
            email_report.send_qa_report(
                jira_key=key,
                passed=qa["passed"],
                report_text=qa["report_text"],
                screenshots=qa["screenshots"],
                deployment_url=live_url,
                pr_url=gh.get("pr_url"),
                summary=summary,
            )
            hlog.step("SendGrid accepted message (status 202)")
            hlog.end_stage("PASS", "Email delivered")
        except email_report.EmailError as e:
            log.exception("Email stage failed (non-fatal): %s", e)
            hlog.warn(f"SendGrid failed: {e}")
            hlog.end_stage("WARN", "Email failed (non-fatal); pipeline continues")

        # ---- Stage 8: close loop ----
        current_stage = "close-loop"
        hlog.begin_stage("Close loop", "Comment on Jira and move the story to its terminal column.")
        if qa["passed"]:
            _safe_jira_comment(
                key,
                f"All QA tests passed.\n\nDeployment: {live_url}\nPR: {gh.get('pr_url')}\n\n{qa['report_text'][:5000]}",
            )
            hlog.step("Posted PASS comment on Jira issue")
            hlog.step("Transitioning Jira: QA → Done")
            _safe_jira_transition(key, "Done")
            final_verdict = "PASS"
            hlog.end_stage("PASS", "Story marked Done")
            log.info("=== DONE %s — PASS ===", key)
        else:
            _safe_jira_comment(
                key,
                f"QA reported failures.\n\nDeployment: {live_url}\nPR: {gh.get('pr_url')}\n\n{qa['report_text'][:20000]}",
            )
            hlog.step("Posted FAIL comment on Jira issue with bug report")
            hlog.step("Transitioning Jira: QA → In Review")
            _safe_jira_transition(key, "In Review")
            final_verdict = "FAIL"
            hlog.end_stage("FAIL", "Story moved to In Review for follow-up")
            log.info("=== DONE %s — FAIL ===", key)

    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc()
        log.exception("Pipeline failed at stage=%s for %s: %s", current_stage, key, exc)
        hlog.warn(f"Exception in stage '{current_stage}': {exc.__class__.__name__}: {exc}")
        hlog.end_stage("FAIL", f"Stage `{current_stage}` raised {exc.__class__.__name__}")
        body = (
            f"Pipeline failed at stage `{current_stage}`.\n\n"
            f"Error: {exc.__class__.__name__}: {exc}\n\n"
            f"Traceback (last 4000 chars):\n{tb[-4000:]}"
        )
        _safe_jira_comment(key, body)
        _safe_jira_transition(key, "In Review")
        final_verdict = f"ERROR ({current_stage})"
        log.info("=== DONE %s — ERROR (%s) ===", key, current_stage)
    finally:
        hlog.finish_run(final_verdict)


def poll_and_process() -> None:
    log.info("Polling Jira for ai-ready stories…")
    try:
        issues = jira_stage.find_ready_stories()
    except Exception:
        log.exception("Jira poll failed")
        return

    for issue in issues:
        key = issue["key"]
        if key in PROCESSED_KEYS:
            log.debug("Skipping already-processed %s in this process", key)
            continue
        PROCESSED_KEYS.add(key)
        try:
            run_pipeline_for_issue(issue)
        except Exception:
            log.exception("Unhandled error processing %s", key)


def _required_env() -> list[str]:
    return [
        "JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY",
        "GITHUB_TOKEN", "GITHUB_REPO_OWNER", "GITHUB_REPO_NAME",
        "VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID",
        "SENDGRID_API_KEY", "EMAIL_TO",
    ]


def _check_env() -> None:
    missing = [k for k in _required_env() if not (os.environ.get(k) or "").strip()]
    if missing:
        log.warning("Missing environment variables: %s", ", ".join(missing))


def main() -> int:
    parser = argparse.ArgumentParser(description="Zero Human Touch Pipeline")
    parser.add_argument("--once", action="store_true", help="Poll once, process matched stories, exit")
    parser.add_argument("--issue", help="Run the pipeline for a single Jira key (skips the poll filter)")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in minutes (default 5)")
    args = parser.parse_args()

    _check_env()

    if args.issue:
        # Fetch this single issue and run unconditionally.
        import requests
        from requests.auth import HTTPBasicAuth
        base = os.environ["JIRA_BASE_URL"].rstrip("/")
        auth = HTTPBasicAuth(os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
        resp = requests.get(
            f"{base}/rest/api/3/issue/{args.issue}",
            params={"fields": "summary,status,labels,attachment,description"},
            auth=auth,
            timeout=30,
        )
        if not resp.ok:
            log.error("Could not fetch issue %s: %s %s", args.issue, resp.status_code, resp.text[:500])
            return 2
        run_pipeline_for_issue(resp.json())
        return 0

    if args.once:
        poll_and_process()
        return 0

    schedule.every(args.interval).minutes.do(poll_and_process)
    log.info("Cron loop running. Polling every %d minute(s). Ctrl-C to stop.", args.interval)
    # Run one pass immediately so we don't sit idle until the first interval elapses.
    poll_and_process()
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
