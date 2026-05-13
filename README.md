# Zero Human Touch Pipeline

A fully automated, end-to-end software delivery pipeline. A product manager files a Jira
story tagged `ai-ready` with a `requirements.md` attachment — and the pipeline takes it
all the way from idea to deployed, QA-tested, emailed report with zero human intervention.

```
Jira (To Do)  ─►  Build (Claude Code CLI)  ─►  Jest tests  ─►  GitHub PR
                                                                     │
                            ◄────────── Email (SendGrid) ◄─── QA (Playwright) ◄── Vercel deploy
Jira (Done / Bug Reported)
```

## Prerequisites

- **Node.js 20+** and **npm** (for `npx jest` and the Claude Code CLI)
- **Python 3.10+**
- **git** on `PATH`
- A Vercel project linked to the GitHub repo (so deployments can be triggered by branch ref).
  Disable **Deployment Protection / SSO** on the project (or provision a Protection Bypass for
  Automation secret) so the pipeline's health check and Playwright QA can hit preview URLs.
- A Jira workflow with statuses **"To Do"**, **"In Progress"**, **"Done"**, and one terminal
  failure status — the pipeline uses **"In Review"** by default (configurable in `pipeline.py`).
- A SendGrid sender / domain identity verified for the `EMAIL_FROM` address (or `EMAIL_TO`
  if `EMAIL_FROM` is unset). Otherwise the QA email step logs a non-fatal `403` and the run
  still completes.

### Install Python dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### Install the Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
claude login    # ← one-time browser-based login with your Claude Pro account
```

> The pipeline never calls `api.anthropic.com` directly. Every AI step shells out
> to the `claude` binary, which uses your logged-in Pro session. **No
> `ANTHROPIC_API_KEY` is required.**

### (Optional) Pre-warm Jest in the workspace

The test stage installs `jest` + `jest-environment-jsdom` automatically on first run.
If you want to pre-install them globally to skip the per-workspace install:

```bash
npm install -g jest jest-environment-jsdom
```

## `.env` setup

Create `.env` in the project root:

```ini
# Jira
JIRA_BASE_URL=https://yourcompany.atlassian.net/
JIRA_EMAIL=you@yourcompany.com
JIRA_API_TOKEN=...
JIRA_PROJECT_KEY=ABC

# GitHub
GITHUB_TOKEN=ghp_...
GITHUB_REPO_OWNER=your-org-or-user
GITHUB_REPO_NAME=your-repo

# Vercel
VERCEL_TOKEN=...
VERCEL_ORG_ID=team_...
VERCEL_PROJECT_ID=prj_...

# Email
SENDGRID_API_KEY=SG.xxxxxxxx
EMAIL_TO=qa@yourcompany.com
# EMAIL_FROM is optional; defaults to EMAIL_TO if omitted. Must be a SendGrid
# verified sender / domain.
EMAIL_FROM=noreply@yourcompany.com
```

> `.env` is git-ignored. Never commit it.

### Jira API token

Create one at <https://id.atlassian.com/manage-profile/security/api-tokens>.

### GitHub token

Use a fine-grained PAT or classic PAT with `repo` (read/write) and `workflow` scopes.

### Vercel token + IDs

- `VERCEL_TOKEN` from <https://vercel.com/account/tokens>
- `VERCEL_ORG_ID` from your team settings (Team ID).
- `VERCEL_PROJECT_ID` from the project's settings page. The project must be
  **linked to the GitHub repo** so that branch-based deployments resolve.

### SendGrid

- API key with **Mail Send → Full Access**.
- Either verify the `EMAIL_FROM` address as a Single Sender, or set up domain
  authentication.

## Running the pipeline

Start the cron loop (every 5 minutes by default):

```bash
python pipeline.py
```

Run a single poll-and-process pass, then exit (handy for cron / CI):

```bash
python pipeline.py --once
```

Run end-to-end against a specific Jira key (skips the To-Do filter — useful for re-runs):

```bash
python pipeline.py --issue ABC-42
```

Custom polling interval (minutes):

```bash
python pipeline.py --interval 10
```

Logs stream to stdout and to `logs/pipeline.log` (rotated at 5 MB × 5 backups).

## Triggering the pipeline from Jira

1. Create a Jira story:
   - **Title:** `[AI-PIPELINE] Build me a Pomodoro timer`
   - **Labels:** add `ai-ready`
   - **Status:** `To Do`
2. Attach a file named `requirements.md` (case-insensitive). It should describe the
   web app and list acceptance criteria — one per bullet. Example:

   ```markdown
   # Pomodoro Timer

   Build a single-page web app with the following acceptance criteria:

   - Start, pause, and reset buttons control a 25-minute countdown.
   - The remaining time is displayed as MM:SS.
   - When the timer reaches 0, an audible alarm plays and the title flashes.
   - Completed pomodoros count persists across page reloads (localStorage).
   - Switching to a 5-minute break is possible via a "Break" button.
   ```

3. Wait. Within the polling interval, the pipeline will:
   1. Transition the story to **In Progress**.
   2. Generate `index.html`, `index.test.js`, run Jest, push to a branch, open a PR.
   3. Trigger a Vercel deployment, wait for `READY`, health-check the URL.
   4. Run a generated Playwright suite against the live URL, capture screenshots.
   5. Email a structured `bug-report.md` (with screenshots attached) to `EMAIL_TO`.
   6. Transition the story to **Done** (all green) or **In Review** (anything failed).

## Verifying each stage

| Stage | What to check |
| --- | --- |
| Jira poll | Story moves out of **To Do** within the interval. |
| Build | `workspace/{KEY}/index.html` exists. |
| Tests | `workspace/{KEY}/test-results.txt` shows `Result: PASS`. |
| GitHub | A branch `feature/{KEY}-...` and an open PR. |
| Vercel | A deployment with `readyState=READY` in the Vercel dashboard. |
| QA | `workspace/{KEY}/qa/*.png` screenshots and `bug-report.md`. |
| Email | An email arrives at `EMAIL_TO` with the report and PNG attachments. |
| Close loop | Story ends in **Done** (PASS) or **In Review** (FAIL/error) — never stuck in **In Progress**. |

If something goes wrong, `logs/pipeline.log` contains the full traceback for every
failure, and the corresponding Jira issue gets a comment naming the failing stage.

## Project layout

```
.
├── .env                      # secrets (git-ignored)
├── .gitignore
├── pipeline.py               # cron loop + per-issue orchestration
├── requirements.txt
├── stages/
│   ├── __init__.py
│   ├── jira.py               # poll, download attachment, transition, comment
│   ├── build_agent.py        # Claude Code CLI → index.html
│   ├── test_runner.py        # Claude Code → tests, npx jest, fix loop (≤5)
│   ├── github.py             # branch + commit + push + PR
│   ├── vercel.py             # deploy via /v13/deployments, poll, health-check
│   ├── qa_agent.py           # Claude Code → Playwright script + bug-report.md
│   └── email_report.py       # SendGrid send with PNG attachments
├── workspace/                # per-story output (git-ignored)
│   └── {JIRA-KEY}/
│       ├── requirements.md
│       ├── index.html
│       ├── index.test.js
│       ├── test-results.txt
│       ├── bug-report.md
│       └── qa/
│           ├── test_site.py
│           ├── run.log
│           ├── console.log
│           └── *.png
└── logs/
    └── pipeline.log
```

## Notes on Claude Code CLI usage

Every AI invocation in this codebase follows this exact pattern:

```python
result = subprocess.run(
    ["claude", "--print", "--no-ansi", prompt],
    capture_output=True,
    text=True,
    cwd=str(work_dir),
    timeout=...,
)
if result.returncode != 0:
    raise SomeStageError(result.stderr)
```

- `--print` makes the CLI non-interactive (no TUI).
- `--no-ansi` strips colour codes so logs stay readable.
- `cwd=work_dir` makes Claude Code read and write files inside the per-story
  workspace (it picks up `requirements.md`, writes `index.html`, etc.).

## Error handling guarantees

- Every stage raises a typed exception on failure (`BuildError`, `TestError`, …).
- `pipeline.run_pipeline_for_issue` catches any exception, logs the full traceback,
  posts a Jira comment naming the failing stage, and transitions the story to
  **Bug Reported**.
- An issue is never left in **In Progress** — even if the email or close-loop
  comment itself fails, the transition is attempted last and logged.
