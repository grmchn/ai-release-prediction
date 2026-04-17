"""Fetch RSS/Atom feeds declared in data/models.yaml and normalize entries.

CLI:
    python scripts/fetch_rss.py [--model MODEL_ID] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import common  # noqa: E402


def _feed_entry_to_iso(entry: Any) -> str | None:
    """Return `published` (or `updated`) from a feedparser entry as UTC ISO."""
    for key in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, key, None) or (entry.get(key) if isinstance(entry, dict) else None)
        if struct:
            try:
                dt = datetime(*struct[:6], tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:  # noqa: BLE001 — bad struct, try the next key
                continue
    return None


def _entry_field(entry: Any, name: str, default: str = "") -> str:
    """Access `entry.name` safely whether the entry is an object or dict."""
    value = getattr(entry, name, None)
    if value is None and isinstance(entry, dict):
        value = entry.get(name)
    if value is None:
        return default
    return str(value)


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    """Fetch an RSS/Atom feed via the shared HTTP client, then hand it to feedparser."""
    resp = common.http_get(url, timeout=10, retries=3)
    # Hand the text body (with response encoding applied) to feedparser.
    # Passing `.text` avoids feedparser guessing encoding from bytes.
    return feedparser.parse(resp.text)


def normalize_entries(
    model_id: str,
    source_url: str,
    feed: feedparser.FeedParserDict,
    match: str | None = None,
) -> list[dict[str, Any]]:
    """Convert a parsed feed into the fetch_rss common schema."""
    match_re = re.compile(match, re.IGNORECASE) if match else None
    out: list[dict[str, Any]] = []
    for entry in feed.entries or []:
        title = _entry_field(entry, "title")
        if match_re and not match_re.search(title):
            continue
        out.append(
            {
                "model_id": model_id,
                "source_type": "rss",
                "source_url": source_url,
                "entry_id": _entry_field(entry, "id") or _entry_field(entry, "link"),
                "title": title,
                "link": _entry_field(entry, "link"),
                "published": _feed_entry_to_iso(entry),
                "summary": _entry_field(entry, "summary"),
                "raw_content": _entry_field(entry, "content") or _entry_field(entry, "summary"),
            }
        )
    return out


def fetch_for_model(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Run all RSS sources for a single model, tolerating per-source failure."""
    model_id = model["id"]
    results: list[dict[str, Any]] = []
    for source in model.get("sources", []):
        if source.get("type") != "rss":
            continue
        url = source.get("url")
        if not url:
            continue
        try:
            feed = fetch_feed(url)
            raw_payload = {
                "source_url": url,
                "fetched_at": common.utc_now_iso(),
                "feed_title": feed.feed.get("title", "") if getattr(feed, "feed", None) else "",
                "entries": [dict(e) for e in (feed.entries or [])],
            }
            common.save_raw(model_id, "rss", raw_payload)
            entries = normalize_entries(model_id, url, feed, source.get("match"))
            results.extend(entries)
        except Exception as err:  # noqa: BLE001 — per-source resilience
            common.log_error(
                source=f"rss:{url}",
                err=err,
                extra={"model_id": model_id},
            )
    return results


def run(model_filter: str | None = None) -> list[dict[str, Any]]:
    models = common.load_models()
    all_entries: list[dict[str, Any]] = []
    for model in models:
        if model_filter and model.get("id") != model_filter:
            continue
        if not any(s.get("type") == "rss" for s in model.get("sources", [])):
            continue
        all_entries.extend(fetch_for_model(model))
    return all_entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch RSS feeds for models.yaml sources")
    parser.add_argument("--model", default=None, help="filter to a single model id")
    parser.add_argument("--out", default=None, help="write JSON to this file (default: stdout)")
    args = parser.parse_args(argv)

    entries = run(model_filter=args.model)
    if args.out:
        common.write_json(args.out, entries)
        print(f"wrote {len(entries)} entries to {args.out}", file=sys.stderr)
    else:
        json.dump(entries, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
