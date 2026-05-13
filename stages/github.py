"""GitHub stage: create feature branch, commit generated files, push, open PR."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

import requests

log = logging.getLogger(__name__)


class GitHubError(RuntimeError):
    pass


def _cfg() -> tuple[str, str, str]:
    token = os.environ["GITHUB_TOKEN"].strip()
    owner = os.environ["GITHUB_REPO_OWNER"].strip()
    repo = os.environ["GITHUB_REPO_NAME"].strip()
    return token, owner, repo


def _slug(text: str, max_len: int = 40) -> str:
    text = re.sub(r"\[AI-PIPELINE\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Za-z0-9\s\-_]+", "", text).strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text[:max_len] or "story").strip("-") or "story"


def _git(args: list[str], cwd: Path, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    log.debug("git %s (cwd=%s)", " ".join(args), cwd)
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if check and result.returncode != 0:
        raise GitHubError(f"git {' '.join(args)} failed:\n{result.stderr}\n{result.stdout}")
    return result


def _ensure_repo_clone(repo_root: Path, owner: str, repo: str, token: str) -> str:
    """Clone the GitHub repo into repo_root if missing. Returns the default branch name."""
    auth_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    if not (repo_root / ".git").exists():
        repo_root.mkdir(parents=True, exist_ok=True)
        # Clean any partial contents to allow clone-into-existing-empty-dir.
        if any(repo_root.iterdir()):
            for p in repo_root.iterdir():
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
        log.info("GitHub: cloning %s/%s into %s", owner, repo, repo_root)
        result = subprocess.run(
            ["git", "clone", auth_url, str(repo_root)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            raise GitHubError(f"git clone failed:\n{result.stderr}\n{result.stdout}")
    else:
        # Make sure remote URL has the token for push.
        _git(["remote", "set-url", "origin", auth_url], cwd=repo_root)
        _git(["fetch", "origin", "--prune"], cwd=repo_root)

    # Local identity (does not affect global config).
    _git(["config", "user.email", "ai-pipeline@users.noreply.github.com"], cwd=repo_root)
    _git(["config", "user.name", "AI Pipeline Bot"], cwd=repo_root)

    # Determine default branch.
    head = _git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo_root, check=False)
    if head.returncode == 0 and head.stdout.strip():
        default = head.stdout.strip().rsplit("/", 1)[-1]
    else:
        # Try `main` then `master`.
        for cand in ("main", "master"):
            ls = _git(["ls-remote", "--heads", "origin", cand], cwd=repo_root, check=False)
            if ls.stdout.strip():
                default = cand
                break
        else:
            default = "main"
    return default


def _copy_outputs(work_dir: Path, dest_dir: Path) -> list[Path]:
    """Copy generated artifacts from workspace/{KEY} into repo subfolder, return relative paths."""
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    # Files to ship (everything except node_modules / package-lock).
    skip_names = {"node_modules", ".git", "package-lock.json"}
    for src in work_dir.iterdir():
        if src.name in skip_names:
            continue
        target = dest_dir / src.name
        if src.is_dir():
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("node_modules", ".git"))
        else:
            shutil.copy2(src, target)
        copied.append(target)
    return copied


def push_and_open_pr(work_dir: Path, jira_key: str, summary: str) -> dict:
    """Create branch, copy files into a checked-out clone, push, open PR. Returns metadata."""
    token, owner, repo = _cfg()
    # Place the clone next to the workspace so we don't pollute it.
    repo_root = work_dir.parent.parent / "repo-clone"

    default_branch = _ensure_repo_clone(repo_root, owner, repo, token)

    # Fresh checkout of the default branch.
    _git(["checkout", default_branch], cwd=repo_root)
    _git(["reset", "--hard", f"origin/{default_branch}"], cwd=repo_root)
    _git(["clean", "-fdx"], cwd=repo_root)

    branch = f"feature/{jira_key}-{_slug(summary)}"

    # Delete branch locally if it exists (idempotent re-run).
    _git(["branch", "-D", branch], cwd=repo_root, check=False)
    _git(["checkout", "-b", branch], cwd=repo_root)

    # Copy artifacts to the repo ROOT (not a subfolder) so Vercel serves index.html at "/".
    # Each feature branch is independent of main; `git clean -fdx` above already wiped the
    # working tree. We must NOT delete repo_root itself (that would nuke .git).
    skip = {"node_modules", ".git", "package-lock.json"}
    for src in work_dir.iterdir():
        if src.name in skip:
            continue
        target = repo_root / src.name
        if src.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("node_modules", ".git"))
        else:
            shutil.copy2(src, target)

    _git(["add", "-A"], cwd=repo_root)
    status = _git(["status", "--porcelain"], cwd=repo_root)
    if not status.stdout.strip():
        raise GitHubError(f"{jira_key}: nothing to commit (workspace appears empty)")

    commit_msg = f"{jira_key}: {summary}".strip() or jira_key
    _git(["commit", "-m", commit_msg], cwd=repo_root)
    head_sha = _git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    _git(["push", "-u", "origin", branch, "--force"], cwd=repo_root)

    pr = _open_pr(token, owner, repo, branch, default_branch, jira_key, summary)
    log.info("GitHub: PR opened %s", pr.get("html_url"))
    return {
        "branch": branch,
        "default_branch": default_branch,
        "pr_url": pr.get("html_url"),
        "pr_number": pr.get("number"),
        "commit_sha": head_sha,
        "repo_root": str(repo_root),
    }


def _open_pr(token: str, owner: str, repo: str, branch: str, base: str, key: str, summary: str) -> dict:
    api = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    title = f"{key}: {summary}".strip()
    body = (
        f"Automated PR for Jira issue **{key}**.\n\n"
        f"Generated by the Zero Human Touch Pipeline.\n\n"
        f"Branch: `{branch}`"
    )
    resp = requests.post(api, headers=headers, json={"title": title, "head": branch, "base": base, "body": body}, timeout=30)
    if resp.status_code == 422:
        # Likely "A pull request already exists" — look it up.
        list_resp = requests.get(
            api,
            headers=headers,
            params={"head": f"{owner}:{branch}", "state": "open"},
            timeout=30,
        )
        if list_resp.ok and list_resp.json():
            return list_resp.json()[0]
    if not resp.ok:
        raise GitHubError(f"Open PR failed [{resp.status_code}]: {resp.text[:1000]}")
    return resp.json()
