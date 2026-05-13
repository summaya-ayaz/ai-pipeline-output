"""Human-readable per-run stage logger.

Renders box-drawn stage banners with durations to stdout AND a per-issue log file
at logs/run-{KEY}.log. Sits alongside the standard `logging` output, which keeps
the developer-style debug trail in logs/pipeline.log.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

LINE_WIDTH = 80
DOUBLE = "=" * LINE_WIDTH
SINGLE = "─" * LINE_WIDTH


class HumanLog:
    def __init__(self, jira_key: str, summary: str, log_dir: Path, total_stages: int = 8) -> None:
        self.key = jira_key
        self.summary = summary
        self.total = total_stages
        self.stage_num = 0
        self.run_start = time.time()
        self.stage_start: Optional[float] = None
        self.stage_name: Optional[str] = None
        self.final_verdict: str = "UNKNOWN"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._f: TextIO = open(log_dir / f"run-{jira_key}.log", "a", encoding="utf-8")
        self._write_header()

    # ------------------------------------------------------------------ output

    def _emit(self, line: str = "") -> None:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        try:
            self._f.write(line + "\n")
            self._f.flush()
        except Exception:  # noqa: BLE001
            pass

    def _write_header(self) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._emit()
        self._emit(DOUBLE)
        self._emit(f"  PIPELINE RUN — {self.key}")
        self._emit(f"  Summary : {self.summary}")
        self._emit(f"  Started : {ts}")
        self._emit(DOUBLE)

    # ------------------------------------------------------------------ stages

    def begin_stage(self, name: str, description: str = "") -> None:
        self.stage_num += 1
        self.stage_name = name
        self.stage_start = time.time()
        self._emit()
        self._emit(SINGLE)
        self._emit(f"  Stage {self.stage_num}/{self.total} — {name.upper()}")
        if description:
            self._emit(f"  {description}")
        self._emit(SINGLE)

    def step(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._emit(f"  [{ts}]   • {msg}")

    def warn(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._emit(f"  [{ts}]   ! {msg}")

    def end_stage(self, status: str = "PASS", note: str = "") -> None:
        dur = time.time() - self.stage_start if self.stage_start else 0.0
        tail = f" — {note}" if note else ""
        self._emit(f"  RESULT: {status}{tail}   ({dur:.1f}s)")

    # ----------------------------------------------------------- end of run

    def finish_run(self, verdict: str, jira_status: str | None = None) -> None:
        total = time.time() - self.run_start
        self.final_verdict = verdict
        self._emit()
        self._emit(DOUBLE)
        self._emit(f"  RUN COMPLETE — {verdict}")
        if jira_status:
            self._emit(f"  Jira final  : {jira_status}")
        self._emit(f"  Duration    : {total:.1f}s")
        self._emit(f"  Finished    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._emit(DOUBLE)
        self._emit()
        try:
            self._f.close()
        except Exception:  # noqa: BLE001
            pass
