"""Jira integration: poll for ready stories, download attachments, transition, comment."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

import requests
from requests.auth import HTTPBasicAuth

log = logging.getLogger(__name__)


class JiraError(RuntimeError):
    pass


def _cfg() -> tuple[str, HTTPBasicAuth, str]:
    base = os.environ["JIRA_BASE_URL"].strip().rstrip("/")
    email = os.environ["JIRA_EMAIL"].strip()
    token = os.environ["JIRA_API_TOKEN"].strip()
    project = os.environ["JIRA_PROJECT_KEY"].strip()
    return base, HTTPBasicAuth(email, token), project


def _check(resp: requests.Response, what: str) -> None:
    if not resp.ok:
        raise JiraError(f"{what} failed [{resp.status_code}]: {resp.text[:1000]}")


def find_ready_stories() -> list[dict]:
    """Return Jira issues with label 'ai-ready' in status 'To Do' for the configured project."""
    base, auth, project = _cfg()
    jql = f'project = "{project}" AND labels = "ai-ready" AND status = "To Do"'
    url = f"{base}/rest/api/3/search/jql"
    payload = {
        "jql": jql,
        "fields": ["summary", "status", "labels", "attachment", "description"],
        "maxResults": 50,
    }
    resp = requests.post(url, json=payload, auth=auth, timeout=30)
    if resp.status_code == 410 or resp.status_code == 404:
        # Fall back to the legacy /search endpoint for older Jira instances.
        legacy = f"{base}/rest/api/3/search"
        resp = requests.get(
            legacy,
            params={"jql": jql, "fields": "summary,status,labels,attachment,description", "maxResults": 50},
            auth=auth,
            timeout=30,
        )
    _check(resp, "Jira search")
    data = resp.json()
    issues = data.get("issues", []) or []
    log.info("Jira: found %d ready story(ies)", len(issues))
    return issues


def download_requirements(issue: dict, work_dir: Path) -> Path:
    """Find requirements.md attachment, download it into work_dir, return its path."""
    base, auth, _ = _cfg()
    key = issue["key"]
    attachments = (issue.get("fields") or {}).get("attachment") or []
    target = None
    for att in attachments:
        if (att.get("filename") or "").strip().lower() == "requirements.md":
            target = att
            break
    if target is None:
        # Fall back to any .md file.
        for att in attachments:
            if (att.get("filename") or "").lower().endswith(".md"):
                target = att
                break
    if target is None:
        raise JiraError(f"{key}: no requirements.md attachment found")

    content_url = target.get("content")
    if not content_url:
        raise JiraError(f"{key}: attachment has no content URL")

    resp = requests.get(content_url, auth=auth, timeout=60, allow_redirects=True)
    _check(resp, f"download {target.get('filename')}")
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / "requirements.md"
    out.write_bytes(resp.content)
    log.info("Jira: downloaded %s -> %s (%d bytes)", target.get("filename"), out, out.stat().st_size)
    return out


def _list_transitions(base: str, auth: HTTPBasicAuth, key: str) -> list[dict]:
    resp = requests.get(f"{base}/rest/api/3/issue/{key}/transitions", auth=auth, timeout=30)
    _check(resp, f"list transitions for {key}")
    return resp.json().get("transitions", []) or []


def transition_issue(key: str, target_state: str) -> None:
    """Transition `key` to the named state. Matches transition name OR destination status name."""
    base, auth, _ = _cfg()
    transitions = _list_transitions(base, auth, key)
    target_lc = target_state.strip().lower()
    chosen = None
    for t in transitions:
        if (t.get("name") or "").strip().lower() == target_lc:
            chosen = t
            break
        to = (t.get("to") or {}).get("name") or ""
        if to.strip().lower() == target_lc:
            chosen = t
            break
    if chosen is None:
        names = ", ".join(sorted({(t.get("name") or "") for t in transitions}))
        raise JiraError(f"{key}: no transition matches '{target_state}'. Available: {names}")
    resp = requests.post(
        f"{base}/rest/api/3/issue/{key}/transitions",
        json={"transition": {"id": chosen["id"]}},
        auth=auth,
        timeout=30,
    )
    _check(resp, f"transition {key} -> {target_state}")
    log.info("Jira: %s transitioned to %s", key, target_state)


def comment(key: str, body: str) -> None:
    """Add a plain-text comment to the issue (rendered via ADF doc)."""
    base, auth, _ = _cfg()
    # Atlassian Document Format paragraph(s)
    paragraphs = []
    for chunk in body.split("\n"):
        if not chunk.strip():
            paragraphs.append({"type": "paragraph", "content": []})
        else:
            paragraphs.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": chunk}],
            })
    doc = {"type": "doc", "version": 1, "content": paragraphs or [{"type": "paragraph", "content": []}]}
    resp = requests.post(
        f"{base}/rest/api/3/issue/{key}/comment",
        json={"body": doc},
        auth=auth,
        timeout=30,
    )
    _check(resp, f"comment on {key}")
    log.info("Jira: commented on %s (%d chars)", key, len(body))


def summary_of(issue: dict) -> str:
    return ((issue.get("fields") or {}).get("summary") or "").strip()


def iter_keys(issues: Iterable[dict]) -> list[str]:
    return [i["key"] for i in issues]
