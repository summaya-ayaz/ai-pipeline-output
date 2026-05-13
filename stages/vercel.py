"""Vercel stage: trigger a deployment from the pushed branch and wait until READY."""
from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger(__name__)

VERCEL_API = "https://api.vercel.com"
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 20 * 60  # 20 minutes


class VercelError(RuntimeError):
    pass


def _cfg() -> tuple[str, str, str | None]:
    token = os.environ["VERCEL_TOKEN"].strip()
    project_id = os.environ["VERCEL_PROJECT_ID"].strip()
    team_id = (os.environ.get("VERCEL_ORG_ID") or "").strip() or None
    return token, project_id, team_id


def _team_qs(team_id: str | None) -> dict:
    return {"teamId": team_id} if team_id else {}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_project(token: str, project_id: str, team_id: str | None) -> dict:
    resp = requests.get(
        f"{VERCEL_API}/v9/projects/{project_id}",
        headers=_headers(token),
        params=_team_qs(team_id),
        timeout=30,
    )
    if not resp.ok:
        raise VercelError(f"Get project failed [{resp.status_code}]: {resp.text[:1000]}")
    return resp.json()


def _resolve_project_name(token: str, project_id: str, team_id: str | None) -> str:
    return _get_project(token, project_id, team_id)["name"]


def _resolve_github_repo_id(token: str, project_id: str, team_id: str | None) -> int | None:
    proj = _get_project(token, project_id, team_id)
    link = proj.get("link") or {}
    if link.get("type") == "github":
        return link.get("repoId")
    return None


def trigger_deployment(branch: str, commit_sha: str | None = None) -> dict:
    """Create a deployment from the linked GitHub repo on the given branch."""
    token, project_id, team_id = _cfg()
    project_name = _resolve_project_name(token, project_id, team_id)
    repo_id = _resolve_github_repo_id(token, project_id, team_id)

    git_source: dict = {"type": "github", "ref": branch}
    if commit_sha:
        git_source["sha"] = commit_sha
    if repo_id is not None:
        git_source["repoId"] = repo_id
    else:
        owner = os.environ.get("GITHUB_REPO_OWNER", "").strip()
        repo = os.environ.get("GITHUB_REPO_NAME", "").strip()
        git_source["org"] = owner
        git_source["repo"] = repo

    payload = {
        "name": project_name,
        "project": project_id,
        "gitSource": git_source,
    }
    resp = requests.post(
        f"{VERCEL_API}/v13/deployments",
        headers=_headers(token),
        params=_team_qs(team_id),
        json=payload,
        timeout=60,
    )
    if not resp.ok:
        raise VercelError(f"Create deployment failed [{resp.status_code}]: {resp.text[:1500]}")
    data = resp.json()
    log.info("Vercel: deployment created id=%s url=%s", data.get("id"), data.get("url"))
    return data


def wait_until_ready(deployment_id: str) -> dict:
    """Poll the deployment until READY (or ERROR/CANCELED/timeout)."""
    token, _, team_id = _cfg()
    deadline = time.time() + POLL_TIMEOUT_S
    last_state = ""
    while time.time() < deadline:
        resp = requests.get(
            f"{VERCEL_API}/v13/deployments/{deployment_id}",
            headers=_headers(token),
            params=_team_qs(team_id),
            timeout=30,
        )
        if not resp.ok:
            raise VercelError(f"Poll deployment failed [{resp.status_code}]: {resp.text[:1000]}")
        data = resp.json()
        state = data.get("readyState") or data.get("status") or ""
        if state != last_state:
            log.info("Vercel: deployment %s state=%s", deployment_id, state)
            last_state = state
        if state == "READY":
            return data
        if state in ("ERROR", "CANCELED"):
            raise VercelError(f"Deployment {deployment_id} ended in state {state}: {data.get('errorMessage') or ''}")
        time.sleep(POLL_INTERVAL_S)
    raise VercelError(f"Deployment {deployment_id} did not become READY within {POLL_TIMEOUT_S}s")


def deployment_url(data: dict) -> str:
    """Extract the public URL from a deployment payload."""
    url = data.get("url")
    if not url:
        alias = data.get("alias") or []
        if alias:
            url = alias[0]
    if not url:
        raise VercelError("Deployment has no URL")
    if not url.startswith("http"):
        url = f"https://{url}"
    return url


def health_check(url: str, attempts: int = 12, delay_s: int = 5) -> None:
    """GET the URL, expect HTTP 200. Retries to absorb cold-start latency."""
    last_status = None
    last_err = None
    for i in range(1, attempts + 1):
        try:
            resp = requests.get(url, timeout=20, allow_redirects=True)
            last_status = resp.status_code
            if resp.status_code == 200:
                log.info("Vercel: health check OK (%s)", url)
                return
        except requests.RequestException as e:
            last_err = e
        log.info("Vercel: health check attempt %d/%d -> %s", i, attempts, last_status or last_err)
        time.sleep(delay_s)
    raise VercelError(f"Health check failed for {url}: last_status={last_status} last_err={last_err}")


def deploy(branch: str, commit_sha: str | None = None) -> dict:
    """End-to-end: trigger deployment, wait until READY, health check. Returns metadata."""
    created = trigger_deployment(branch, commit_sha)
    dep_id = created["id"]
    final = wait_until_ready(dep_id)
    url = deployment_url(final)
    health_check(url)
    return {"id": dep_id, "url": url, "state": final.get("readyState"), "inspector_url": final.get("inspectorUrl")}
