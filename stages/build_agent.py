"""Build stage: invoke Claude Code CLI to generate a working web app from requirements.md."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class BuildError(RuntimeError):
    pass


BUILD_PROMPT_TEMPLATE = """You are an autonomous software engineer. Build a complete, working web application based on the requirements below.

STRICT RULES:
- Do NOT ask any clarifying questions. Make every decision yourself.
- Produce a single file named `index.html` in the current working directory.
- All CSS and JavaScript MUST be inline inside `index.html` (no external files, no CDN scripts).
- The app must run by simply opening `index.html` in a browser — no build step.
- Use vanilla JavaScript only. No frameworks. No external libraries.
- Use semantic HTML, accessible labels, and reasonable styling.
- Implement EVERY acceptance criterion in the requirements.
- All interactive elements must have stable, descriptive `id` or `data-testid` attributes
  so that automated DOM tests can select them reliably.
- Persist state to `localStorage` when the requirements imply persistence
  (e.g. todo lists, counters, preferences).
- Do not output prose or explanations — just write the file.

When finished, the file `index.html` MUST exist in the current working directory
and must be a complete, self-contained, runnable web application.

=== REQUIREMENTS.MD ===
{requirements}
=== END REQUIREMENTS ===

Now write `index.html`.
"""


def build_app(work_dir: Path, requirements_text: str) -> str:
    """Run Claude Code CLI to produce work_dir/index.html. Returns its stdout."""
    work_dir.mkdir(parents=True, exist_ok=True)
    prompt = BUILD_PROMPT_TEMPLATE.format(requirements=requirements_text.strip())

    log.info("Build: invoking Claude Code CLI in %s", work_dir)
    result = subprocess.run(
        ["claude", "--print",
         "--permission-mode", "acceptEdits",
         prompt],
        capture_output=True,
        text=True,
        cwd=str(work_dir),
        timeout=900,
    )
    if result.returncode != 0:
        raise BuildError(
            f"Claude Code build failed (rc={result.returncode}).\n"
            f"STDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout[-2000:]}"
        )

    index_path = work_dir / "index.html"
    if not index_path.exists() or index_path.stat().st_size == 0:
        raise BuildError(
            "Claude Code finished but index.html was not created.\n"
            f"STDOUT tail:\n{result.stdout[-2000:]}"
        )

    log.info("Build: index.html ready (%d bytes)", index_path.stat().st_size)
    return result.stdout
