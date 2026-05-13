# Zero Human Touch Pipeline — Implementation Plan

A fully automated, no-human-in-the-loop delivery system. The product manager files a
Jira story tagged `ai-ready` with a `requirements.md` attachment, and the pipeline
takes it from idea → built app → tested code → GitHub PR → live Vercel deployment →
QA-tested live site → emailed report → terminal Jira state, with **zero human
intervention** between story creation and final Jira transition.

---

## End-to-end flow

```mermaid
flowchart TD
    A[Product Manager creates Jira story<br/>label=ai-ready, status=To Do<br/>attaches requirements.md] --> B

    subgraph CRON[pipeline.py — schedule every 5 min]
        B[Poll Jira<br/>find_ready_stories]
    end

    B -->|issues found| C[Download requirements.md<br/>→ workspace/KEY/]
    C --> D[Transition Jira → In Progress]
    D --> E[Stage 2: Build<br/>claude --print prompt<br/>writes index.html]
    E --> F[Stage 3: Tests<br/>claude writes index.test.js<br/>npx jest --json]
    F -->|fail| G{Iteration < 5?}
    G -->|yes| H[claude --print fix prompt<br/>rewrites index.html]
    H --> F
    G -->|no| Z1
    F -->|pass| I[Stage 4: GitHub<br/>branch + commit + push<br/>REST POST /pulls]
    I --> J[Stage 5: Vercel<br/>POST /v13/deployments<br/>poll readyState until READY<br/>HTTP 200 health check]
    J --> K[Stage 6: QA<br/>claude writes qa/test_site.py<br/>python qa/test_site.py<br/>claude writes bug-report.md]
    K --> L[Stage 7: Email<br/>SendGrid<br/>body=bug-report.md<br/>attach all qa/*.png]
    L --> M{QA passed?}
    M -->|yes| N[Comment + transition Jira → Done]
    M -->|no| Z2[Comment + transition Jira → Bug Reported]

    Z1[Comment + transition Jira → Bug Reported]

    E -.->|exception| Z3
    F -.->|exception| Z3
    I -.->|exception| Z3
    J -.->|exception| Z3
    K -.->|exception| Z3
    Z3[Log traceback to logs/pipeline.log<br/>Jira comment with failing stage<br/>transition → Bug Reported]

    N --> END[Terminal state]
    Z1 --> END
    Z2 --> END
    Z3 --> END
```

---

## Stage-by-stage detail

### Stage 1 — Jira polling (`stages/jira.py`)

`find_ready_stories()` calls `POST /rest/api/3/search/jql` with HTTP Basic Auth
(email + API token) and JQL `project = KEY AND labels = "ai-ready" AND status = "To Do"`,
falling back to the legacy `GET /search` endpoint for older Jira sites.
`download_requirements(issue, work_dir)` walks `fields.attachment[]`, picks the file
named `requirements.md` (case-insensitive), GETs its `content` URL with auth, and
writes the bytes to `workspace/{KEY}/requirements.md`. `transition_issue(key, name)`
lists transitions and matches by name **or** destination-status name, then POSTs the
matching id. `comment(key, body)` wraps the body in an ADF document so Jira accepts it.
Every non-2xx response raises `JiraError` with the response body.

### Stage 2 — Build (`stages/build_agent.py`)

`build_app(work_dir, requirements_text)` formats `BUILD_PROMPT_TEMPLATE` with the raw
requirements and runs:

```python
subprocess.run(["claude", "--print", "--no-ansi", prompt],
               capture_output=True, text=True, cwd=str(work_dir), timeout=900)
```

The prompt forbids clarifying questions, requires a single self-contained `index.html`
with inline CSS/JS, vanilla JavaScript only, stable `id` / `data-testid` attributes,
and `localStorage` persistence when implied. After the call we assert `index.html`
exists and is non-empty; otherwise `BuildError`.

### Stage 3 — Tests (`stages/test_runner.py`)

`_ensure_jest_installed(work_dir)` is idempotent: it writes `package.json` configured
for `jest-environment-jsdom` and runs `npm install jest jest-environment-jsdom jsdom`
on first call only. Claude Code is then asked to write `index.test.js` that injects
`index.html` into the JSDOM and asserts every acceptance criterion using stable
selectors. `_run_jest(work_dir)` shells out to `npx --yes jest --json`, slices the
JSON object from stdout, and inspects `success` + `numFailedTests`. On failure,
`_summarize_failures(parsed, raw)` extracts per-test failure messages and feeds them
back to Claude Code via `FIX_PROMPT_TEMPLATE` — Claude is restricted to editing
`index.html` only. Loops up to 5 times. The final human-readable summary is written
to `test-results.txt`. Still failing after 5 → `TestError`.

### Stage 4 — GitHub (`stages/github.py`)

Uses raw `git` via subprocess + the GitHub REST API (no PyGitHub auth surface to
debug). `_ensure_repo_clone` clones the configured repo into `repo-clone/` once,
sets `remote.origin.url` to `https://x-access-token:{TOKEN}@github.com/...` for
auth, configures a local-only `user.name` / `user.email` (never touches global git
config), and detects the default branch from `refs/remotes/origin/HEAD`. For each
issue we reset hard to the default branch, create `feature/{KEY}-{slug}` (slug
derived from the Jira summary, sanitised + truncated to 40 chars), copy artifacts
from `workspace/{KEY}/` into `repo-clone/{KEY}/` (skipping `node_modules`,
`package-lock.json`, `.git`), commit, force-push, and `POST /repos/.../pulls` with
title `"{KEY}: {summary}"`. A 422 response is treated as "PR already exists" and we
look up the open PR instead of erroring.

### Stage 5 — Vercel (`stages/vercel.py`)

`trigger_deployment(branch, sha)` first calls `GET /v9/projects/{id}` to resolve the
project name and the linked GitHub `repoId`, then `POST /v13/deployments` with
`gitSource = {type:"github", repoId, ref, sha}` and `target:"preview"`. If the
project isn't linked we fall back to `{org, repo}` instead of `repoId`. `wait_until_ready`
polls `GET /v13/deployments/{id}` every 5 s for up to 20 min, raising on `ERROR` or
`CANCELED`. `health_check` issues `requests.get(url)` up to 12 times with 5 s
spacing — 200 wins, anything else is a `VercelError`. `deploy(branch, sha)` is the
single entry point that returns `{id, url, state, inspector_url}`.

### Stage 6 — QA (`stages/qa_agent.py`)

Builds `WRITE_PLAYWRIGHT_PROMPT_TEMPLATE` containing the live URL + the raw
`requirements.md`, and asks Claude Code to write `qa/test_site.py`. Hard rules in
the prompt: `playwright.sync_api`, Chromium headless, subscribe to `page.on("console")`
and `page.on("pageerror")` **before** navigation and write JSON-line entries to
`qa/console.log`, screenshot at every meaningful state (`qa/{NN}-{slug}.png`),
per-criterion try/except so one failure doesn't stop the rest, print
`CRITERION | name | PASS/FAIL` lines and a final `OVERALL: PASS` or `OVERALL: FAIL`,
exit code 0 regardless (orchestrator parses the lines). The orchestrator then runs
`python qa/test_site.py` with `subprocess.run(..., cwd=work_dir, timeout=900)`,
writes the combined stdout/stderr to `qa/run.log`, and makes a second Claude Code
call to produce `bug-report.md` with a Markdown PASS/FAIL table, console errors
section, screenshot list, plain-English summary, and an explicit `OVERALL: PASS|FAIL`
verdict line. `_verdict_from_report` returns `True` only if the report says
`OVERALL: PASS`.

### Stage 7 — Email (`stages/email_report.py`)

Reads `SENDGRID_API_KEY` + `EMAIL_TO` (and optional `EMAIL_FROM`, defaulting to
`EMAIL_TO`). Constructs `Mail(from, to, subject="QA Report — {KEY} — {PASS|FAIL}",
plain_text_content=report)` and iterates `qa/*.png`, base64-encoding each and
attaching with the correct MIME type via `Attachment(FileContent, FileName,
FileType, Disposition("attachment"))`. Sends via `SendGridAPIClient.send(message)`;
non-2xx → `EmailError`. The orchestrator treats email failures as **non-fatal** —
the close-loop step still runs so the Jira state is always terminal.

### Stage 8 — Close loop (`pipeline.py::run_pipeline_for_issue`)

After QA returns, on PASS we comment the deployment URL + PR + first 5 KB of the
report and transition to **Done**; on FAIL we comment the first 20 KB of the report
and transition to **Bug Reported**. The whole per-issue flow lives inside a single
`try/except Exception`: any exception logs the full traceback, posts a Jira comment
naming the failing stage variable (`current_stage`), and transitions to **Bug
Reported**. `_safe_jira_comment` / `_safe_jira_transition` swallow secondary
failures so a broken Jira call can't leave the issue stuck — the transition is the
last action attempted.

---

## File map

| Path | Purpose |
| --- | --- |
| `pipeline.py` | `schedule` loop (every 5 min), `--once`, `--issue KEY`, per-issue try/except, logging setup |
| `stages/jira.py` | poll, attachment download, transitions, comments |
| `stages/build_agent.py` | Claude Code CLI → `index.html` |
| `stages/test_runner.py` | Claude Code → `index.test.js`; Jest run; ≤5-iter fix loop |
| `stages/github.py` | clone, branch, copy artifacts, commit, force-push, open PR |
| `stages/vercel.py` | `POST /v13/deployments`, poll `readyState`, health-check |
| `stages/qa_agent.py` | Claude Code → Playwright script → run → Claude Code → `bug-report.md` |
| `stages/email_report.py` | SendGrid `Mail` with PNG attachments |
| `workspace/{KEY}/` | per-story output (git-ignored) |
| `logs/pipeline.log` | rotating 5 MB × 5 backups |
| `.env` | secrets (git-ignored) |
| `requirements.txt` | Python deps |
| `README.md` | setup + run docs |

## Claude Code CLI contract (applies to every AI call)

```python
result = subprocess.run(
    ["claude", "--print", "--no-ansi", prompt],
    capture_output=True, text=True,
    cwd=str(work_dir), timeout=...,
)
if result.returncode != 0:
    raise <StageError>(result.stderr)
```

- `--print` → non-interactive (no TUI).
- `--no-ansi` → clean log output.
- `cwd=work_dir` → Claude Code reads/writes files in the per-story workspace.
- Auth via one-time `claude login` (Claude Pro session). **No `ANTHROPIC_API_KEY`.**

## Error-handling guarantees

1. Every stage raises a typed exception (`JiraError`, `BuildError`, `TestError`,
   `GitHubError`, `VercelError`, `QAError`, `EmailError`).
2. `run_pipeline_for_issue` wraps the full sequence in `try/except`; any failure
   logs the traceback, posts a Jira comment, and transitions to **Bug Reported**.
3. The Jira transition is the **last** action attempted on the failure path — so
   even if the comment call dies, the state still moves.
4. Email failures are explicitly non-fatal so a SendGrid outage cannot strand a
   story in **In Progress**.
