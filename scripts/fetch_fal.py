"""Fetch recently-added model listings from fal.ai.

fal.ai aggregates both cloud and open-weight generative models with structured
`publishedAt` timestamps and a stable `modelFamily` label. This is a rare
vendor-neutral source that covers weak-RSS vendors (ByteDance Seed, Kuaishou
Kling, Shengshu Vidu) alongside the usual suspects.

CLI:
    python scripts/fetch_fal.py [--model MODEL_ID] [--out PATH] [--pages N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import common  # noqa: E402

FAL_API_BASE = "https://fal.ai/api/models"
PAGE_SIZE = 50
DEFAULT_PAGES = 4  # 200 most-recent models — covers several months of drops


def _list_recent(pages: int = DEFAULT_PAGES) -> list[dict[str, Any]]:
    """Fetch the `pages` newest pages of fal.ai models."""
    collected: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        url = f"{FAL_API_BASE}?sort=recently_added&page={page}&size={PAGE_SIZE}"
        body = common.http_get(url, timeout=15).json()
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list) or not items:
            break
        collected.extend(items)
        # Stop early when we hit a page that wasn't full.
        if len(items) < PAGE_SIZE:
            break
    return collected


def _ts_to_date(value: Any) -> str | None:
    """`2026-02-26T16:20:09.685Z` → `2026-02-26`."""
    if not value:
        return None
    s = str(value)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _fields_for_match(item: dict[str, Any]) -> str:
    """Concatenate the fields we run the per-model regex against."""
    fam = item.get("modelFamily")
    fam_str = fam.get("title") if isinstance(fam, dict) else (fam or "")
    return " || ".join(
        [
            str(item.get("id") or ""),
            str(item.get("title") or ""),
            fam_str or "",
            str(item.get("shortDescription") or ""),
        ]
    )


def _derive_version(match_re: re.Pattern[str], item: dict[str, Any]) -> str | None:
    """Strip the brand phrase from `modelFamily` / `id` to isolate the version tail.

    `Seedream 4.5` → `4.5`, `Kling v3` → `v3`, `Nano Banana 2` → `2`.
    Returns None if nothing usable remains (e.g. `modelFamily == "Nano Banana"`).
    """
    fam = item.get("modelFamily")
    fam_str = fam.get("title") if isinstance(fam, dict) else (fam or "")
    candidates = [fam_str, (item.get("id") or "").split("/")[-1]]
    for cand in candidates:
        if not cand:
            continue
        stripped = match_re.sub(" ", cand, count=1).strip(" -_./")
        # Collapse repeated whitespace.
        stripped = re.sub(r"\s+", " ", stripped)
        if stripped:
            return stripped
    return None


def _normalize(model_id: str, item: dict[str, Any], match_re: re.Pattern[str]) -> dict[str, Any] | None:
    """Project a raw fal item into the release-candidate shape."""
    fam = item.get("modelFamily")
    fam_str = fam.get("title") if isinstance(fam, dict) else fam
    version = _derive_version(match_re, item)
    if not version:
        return None
    return {
        "model_id": model_id,
        "source_type": "fal",
        "fal_id": item.get("id"),
        "title": item.get("title"),
        "family": fam_str,
        "category": item.get("category"),
        # tag_name is the normalized version string so merge_releases dedups
        # correctly against RSS / HF / seeded entries.
        "tag_name": version,
        "published_at": item.get("publishedAt") or item.get("date"),
        "release_date_only": _ts_to_date(item.get("publishedAt") or item.get("date")),
        "html_url": f"https://fal.ai/models/{item.get('id', '').lstrip('/')}",
        "short_description": item.get("shortDescription"),
    }


def fetch_for_model(
    model: dict[str, Any],
    all_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply each `type: fal` source's match regex to the shared item list."""
    model_id = model["id"]
    out: list[dict[str, Any]] = []
    for src in model.get("sources") or []:
        if src.get("type") != "fal":
            continue
        match = src.get("match")
        if not match:
            continue
        match_re = re.compile(match, re.IGNORECASE)
        exclude_re = re.compile(src["exclude"], re.IGNORECASE) if src.get("exclude") else None
        matched: list[dict[str, Any]] = []
        for item in all_items:
            haystack = _fields_for_match(item)
            if not match_re.search(haystack):
                continue
            if exclude_re and exclude_re.search(haystack):
                continue
            norm = _normalize(model_id, item, match_re)
            if norm is not None:
                matched.append(norm)
        # Persist raw per-source matches for inspection.
        common.save_raw(model_id, "fal", {"match": match, "matched": matched})
        out.extend(matched)
    return out


def fetch_all(model_filter: str | None = None, pages: int = DEFAULT_PAGES) -> list[dict[str, Any]]:
    models = common.load_models()
    if not any(s.get("type") == "fal" for m in models for s in m.get("sources") or []):
        return []
    try:
        all_items = _list_recent(pages=pages)
    except Exception as exc:  # noqa: BLE001 — one upstream failure should not kill the run
        common.log_error(source="fal:list", err=exc)
        return []

    results: list[dict[str, Any]] = []
    for model in models:
        if model_filter and model.get("id") != model_filter:
            continue
        try:
            results.extend(fetch_for_model(model, all_items))
        except Exception as exc:  # noqa: BLE001
            common.log_error(source=f"fal:{model.get('id')}", err=exc)
    return results


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", help="Only fetch for this model id")
    p.add_argument("--out", help="Write JSON output to this file (else stdout)")
    p.add_argument("--pages", type=int, default=DEFAULT_PAGES, help="How many listing pages to walk")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    results = fetch_all(model_filter=args.model, pages=args.pages)
    if args.out:
        common.write_json(args.out, results)
        print(f"wrote {len(results)} fal entries to {args.out}", file=sys.stderr)
    else:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
