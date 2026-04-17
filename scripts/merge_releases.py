"""Merge new release candidates into data/releases.json with dedup.

CLI:
    python scripts/merge_releases.py --in PATH [--releases data/releases.json]

Input entries may come from three shapes:
1. fetch_rss + classify:   {model_id, classification: {is_release, version, ...}, ...}
2. fetch_github:           {model_id, tag_name, published_at, html_url, ...}
3. fetch_hf:               {model_id, hf_model_id, created_at, html_url, ...}

The merger extracts (model_id, version, date) from each shape, normalizes the
version, and appends only new (model_id, normalized_version) tuples.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import common  # noqa: E402


_HF_VERSION_RE = re.compile(r"[-_/]([vV]?\d[\w.\-]*)$")


def _date_only(iso_or_date: str | None) -> str | None:
    """Take `2026-04-17T03:00:00Z` → `2026-04-17`. Return input if already a date."""
    if not iso_or_date:
        return None
    s = str(iso_or_date)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


def extract_candidate(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Pull (model_id, version, date, url, source) from an arbitrary entry.

    Returns None if the entry can't be turned into a release candidate
    (e.g. classified as non-release, or missing critical fields).
    """
    model_id = entry.get("model_id")
    if not model_id:
        return None

    # RSS + classify path
    classification = entry.get("classification")
    if classification:
        if not classification.get("is_release"):
            return None
        version = classification.get("version")
        if not version:
            return None
        date = classification.get("release_date") or _date_only(entry.get("published"))
        return {
            "model_id": model_id,
            "version": str(version),
            "date": date,
            "url": entry.get("link"),
            "source": entry.get("source_url") or entry.get("source_type") or "rss",
            "note": classification.get("model_name") or "",
        }

    # fal.ai path — source_type is "fal", tag_name carries the modelFamily.
    if entry.get("source_type") == "fal":
        return {
            "model_id": model_id,
            "version": str(entry.get("tag_name") or entry.get("family") or entry.get("title") or ""),
            "date": _date_only(entry.get("published_at")),
            "url": entry.get("html_url"),
            "source": f"fal:{entry.get('fal_id', '')}",
            "note": entry.get("short_description") or "",
        }

    # GitHub path
    if entry.get("tag_name") is not None:
        tag = str(entry["tag_name"])
        return {
            "model_id": model_id,
            "version": tag,
            "date": _date_only(entry.get("published_at")),
            "url": entry.get("html_url"),
            "source": f"github:{entry.get('repo', '')}",
            "note": entry.get("name") or "",
        }

    # HF path — try to peel a version suffix off hf_model_id.
    if entry.get("hf_model_id"):
        hf_id = str(entry["hf_model_id"])
        match = _HF_VERSION_RE.search(hf_id)
        version = match.group(1) if match else hf_id.split("/")[-1]
        return {
            "model_id": model_id,
            "version": version,
            "date": _date_only(entry.get("created_at")),
            "url": entry.get("html_url"),
            "source": f"hf:{hf_id}",
            "note": hf_id,
        }

    return None


def merge_candidate(
    releases: dict[str, list[dict[str, Any]]],
    candidate: dict[str, Any],
) -> bool:
    """Append `candidate` into releases if not already present. Returns True if added."""
    model_id = candidate["model_id"]
    version = candidate["version"]
    if not version or not candidate.get("date"):
        return False

    bucket = releases.setdefault(model_id, [])
    target_key = common.dedup_key(model_id, version)
    for existing in bucket:
        if common.dedup_key(model_id, existing.get("version", "")) == target_key:
            return False

    bucket.append(
        {
            "version": version,
            "date": candidate["date"],
            "url": candidate.get("url") or "",
            "source": candidate.get("source") or "",
            "detected_at": common.utc_now_iso(),
            "note": candidate.get("note") or "",
        }
    )
    # Keep the bucket sorted by date ascending so downstream predict.py has a
    # deterministic order regardless of merge order.
    bucket.sort(key=lambda r: r.get("date") or "")
    return True


def merge_entries(
    entries: list[dict[str, Any]],
    releases: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], int, int]:
    """Merge candidates from `entries` into `releases`. Returns (releases, added, skipped)."""
    releases = releases if releases is not None else {}
    added = 0
    skipped = 0
    for entry in entries:
        candidate = extract_candidate(entry)
        if candidate is None:
            skipped += 1
            continue
        if merge_candidate(releases, candidate):
            added += 1
        else:
            skipped += 1
    return releases, added, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge new releases into releases.json")
    parser.add_argument("--in", dest="in_path", required=True, help="path to fetch/classify JSON")
    parser.add_argument(
        "--releases",
        default="data/releases.json",
        help="path to the cumulative releases.json (default: data/releases.json)",
    )
    args = parser.parse_args(argv)

    entries = common.load_json(args.in_path, default=[])
    if not isinstance(entries, list):
        print(f"error: {args.in_path} must contain a JSON array", file=sys.stderr)
        return 1

    releases = common.load_json(args.releases, default={}) or {}
    if not isinstance(releases, dict):
        print(f"error: {args.releases} must be a JSON object", file=sys.stderr)
        return 1

    merged, added, skipped = merge_entries(entries, releases)
    common.write_json(args.releases, merged)
    print(f"merged: added={added} skipped={skipped} total_models={len(merged)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
