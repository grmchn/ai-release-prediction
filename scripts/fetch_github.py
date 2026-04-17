"""Fetch GitHub Releases for every model whose `sources` include `type: github`.

Structured data only — no LLM calls. One source failure must not stop the run.
See AGENTS.md §7, §13, §15.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Allow running as `python scripts/fetch_github.py` without install.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.common import (  # noqa: E402
    http_get,
    load_models,
    log_error,
    save_raw,
    write_json,
)

GITHUB_API_BASE = "https://api.github.com"
PER_PAGE = 30


def _auth_headers() -> dict[str, str]:
    """Build headers — attach a token when `GITHUB_TOKEN` is set."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _normalize(model_id: str, repo: str, release: dict[str, Any]) -> dict[str, Any]:
    """Project a raw GitHub release into our flat schema."""
    return {
        "model_id": model_id,
        "source_type": "github",
        "repo": repo,
        "tag_name": release.get("tag_name"),
        "name": release.get("name"),
        "published_at": release.get("published_at"),
        "html_url": release.get("html_url"),
        "body": release.get("body"),
        "prerelease": bool(release.get("prerelease", False)),
        "draft": bool(release.get("draft", False)),
    }


def fetch_one(
    model_id: str,
    repo: str,
    *,
    include_prerelease: bool = False,
    include_draft: bool = False,
) -> list[dict[str, Any]]:
    """Fetch and normalize releases for a single `{owner}/{repo}`.

    Returns an empty list on rate-limit exhaustion so the caller can continue
    with the next source. Other exceptions propagate to the caller, which is
    expected to catch them via `log_error`.
    """
    url = f"{GITHUB_API_BASE}/repos/{repo}/releases?per_page={PER_PAGE}"
    resp = http_get(url, headers=_auth_headers(), timeout=15.0)

    # GitHub returns remaining=0 with 403 once the window is used up; treat
    # any remaining=0 response as "back off and move on".
    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining is not None and remaining == "0":
        log_error(
            source=f"github:{repo}",
            err="rate limit reached (X-RateLimit-Remaining=0)",
            extra={
                "reset": resp.headers.get("X-RateLimit-Reset"),
                "limit": resp.headers.get("X-RateLimit-Limit"),
            },
        )
        return []

    raw = resp.json()
    if not isinstance(raw, list):
        # Typical shape for error payloads — a dict with `message`.
        raise RuntimeError(f"unexpected GitHub payload for {repo}: {raw!r}")

    save_raw(model_id, "github", raw)

    out: list[dict[str, Any]] = []
    for rel in raw:
        if not isinstance(rel, dict):
            continue
        if rel.get("draft") and not include_draft:
            continue
        if rel.get("prerelease") and not include_prerelease:
            continue
        out.append(_normalize(model_id, repo, rel))
    return out


def fetch_all(
    *,
    model_filter: str | None = None,
    include_prerelease: bool = False,
    include_draft: bool = False,
) -> list[dict[str, Any]]:
    """Iterate every model with `type: github` sources and collect releases."""
    results: list[dict[str, Any]] = []
    for model in load_models():
        model_id = model.get("id")
        if model_filter and model_id != model_filter:
            continue
        for source in model.get("sources") or []:
            if source.get("type") != "github":
                continue
            repo = source.get("repo")
            if not repo:
                log_error(source=f"github:{model_id}", err="missing `repo` in source")
                continue
            try:
                results.extend(
                    fetch_one(
                        model_id,
                        repo,
                        include_prerelease=include_prerelease,
                        include_draft=include_draft,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — single-source isolation
                log_error(source=f"github:{repo}", err=exc)
                continue
    return results


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch GitHub Releases for tracked models.")
    p.add_argument("--model", help="Limit to a single model id.")
    p.add_argument("--out", help="Write JSON output to this path instead of stdout.")
    p.add_argument(
        "--include-prerelease",
        action="store_true",
        help="Include prereleases (default: excluded).",
    )
    p.add_argument(
        "--include-draft",
        action="store_true",
        help="Include drafts (default: excluded).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    releases = fetch_all(
        model_filter=args.model,
        include_prerelease=args.include_prerelease,
        include_draft=args.include_draft,
    )
    if args.out:
        write_json(args.out, releases)
    else:
        json.dump(releases, sys.stdout, ensure_ascii=False, indent=2, default=str)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
