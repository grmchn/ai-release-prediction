"""Fetch Hugging Face Hub model metadata for models declared in models.yaml."""
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

HF_API_BASE = "https://huggingface.co/api/models"
HF_SEARCH_LIMIT = 30
HF_AUTHOR_LIMIT = 50

# Match ISO timestamps with optional fractional seconds and `Z` suffix.
_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def _normalize_ts(value: Any) -> str | None:
    """Normalize an HF timestamp to `YYYY-MM-DDTHH:MM:SSZ`."""
    if not value:
        return None
    s = str(value).strip()
    m = _TS_RE.match(s)
    if not m:
        return None
    return f"{m.group(1)}Z"


def _is_concrete_id(query: str) -> bool:
    """HF model ids look like `owner/name`."""
    return "/" in query and not any(c in query for c in " \t\n")


def _fetch_model_detail(hf_id: str) -> dict[str, Any]:
    """GET the detail endpoint for a single HF model id."""
    url = f"{HF_API_BASE}/{hf_id}"
    return common.http_get(url).json()


def _search_models(query: str) -> list[dict[str, Any]]:
    """GET the search endpoint; returns a list of summary entries."""
    url = (
        f"{HF_API_BASE}?search={query}"
        f"&limit={HF_SEARCH_LIMIT}&sort=downloads&direction=-1"
    )
    data = common.http_get(url).json()
    return data if isinstance(data, list) else []


def _list_by_author(author: str, *, limit: int = HF_AUTHOR_LIMIT) -> list[dict[str, Any]]:
    """List all models under an HF author/org, sorted by creation date (newest first).

    This is the future-proof alternative to pinning one concrete repo id:
    when an org publishes a new flagship version, it shows up at the top.
    """
    url = (
        f"{HF_API_BASE}?author={author}"
        f"&limit={limit}&sort=createdAt&direction=-1"
    )
    data = common.http_get(url).json()
    return data if isinstance(data, list) else []


def _normalize_entry(
    model_id: str, entry: dict[str, Any]
) -> dict[str, Any] | None:
    """Produce the normalized schema from a single HF entry."""
    hf_id = entry.get("id") or entry.get("modelId")
    if not hf_id:
        return None
    created = _normalize_ts(entry.get("createdAt"))
    modified = _normalize_ts(entry.get("lastModified"))
    tags = entry.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return {
        "model_id": model_id,
        "source_type": "hf",
        "hf_model_id": hf_id,
        "created_at": created,
        "last_modified": modified,
        "downloads": int(entry.get("downloads") or 0),
        "tags": tags,
        "html_url": f"https://huggingface.co/{hf_id}",
    }


def fetch_for_author_source(
    model_id: str,
    author: str,
    *,
    name_match: str | None = None,
    exclude: str | None = None,
    limit: int = HF_AUTHOR_LIMIT,
) -> list[dict[str, Any]]:
    """List an HF org's models (newest first) and keep those matching `name_match`.

    `name_match` is a regex applied to the repo name (post-slash). `exclude`
    filters out precision/distillation variants so the same release does not
    show up several times.
    """
    import re

    raw = _list_by_author(author, limit=limit)
    common.save_raw(model_id, "hf", {"author": author, "entries": raw})

    include_re = re.compile(name_match, re.IGNORECASE) if name_match else None
    exclude_re = re.compile(exclude, re.IGNORECASE) if exclude else None

    out: list[dict[str, Any]] = []
    for entry in raw:
        hf_id = entry.get("id") or entry.get("modelId") or ""
        repo_name = hf_id.split("/", 1)[-1] if "/" in hf_id else hf_id
        if include_re and not include_re.search(repo_name):
            continue
        if exclude_re and exclude_re.search(repo_name):
            continue
        norm = _normalize_entry(model_id, entry)
        if norm is not None:
            out.append(norm)
    return out


def fetch_for_source(model_id: str, query: str) -> list[dict[str, Any]]:
    """Fetch + normalize entries for a single `type: hf` source."""
    raw: Any
    entries: list[dict[str, Any]]
    if _is_concrete_id(query):
        raw = _fetch_model_detail(query)
        entries = [raw] if isinstance(raw, dict) else []
    else:
        raw = _search_models(query)
        entries = list(raw)
        # Backfill missing timestamps via the detail endpoint.
        for i, e in enumerate(entries):
            hf_id = e.get("id") or e.get("modelId")
            if not hf_id:
                continue
            if e.get("createdAt") and e.get("lastModified"):
                continue
            try:
                detail = _fetch_model_detail(hf_id)
            except Exception as exc:  # noqa: BLE001 — logged, keep going
                common.log_error(source=f"hf:{hf_id}", err=exc)
                continue
            merged = {**e, **{k: v for k, v in detail.items() if v is not None}}
            entries[i] = merged

    common.save_raw(model_id, "hf", raw)

    out: list[dict[str, Any]] = []
    for e in entries:
        norm = _normalize_entry(model_id, e)
        if norm is not None:
            out.append(norm)
    return out


def fetch_all(target_model: str | None = None) -> list[dict[str, Any]]:
    """Iterate all models; collect normalized entries from every `hf` source."""
    results: list[dict[str, Any]] = []
    for model in common.load_models():
        mid = model.get("id")
        if target_model and mid != target_model:
            continue
        for src in model.get("sources") or []:
            src_type = src.get("type")
            if src_type == "hf":
                query = src.get("query")
                if not query:
                    continue
                try:
                    results.extend(fetch_for_source(mid, query))
                except Exception as exc:  # noqa: BLE001 — per-source isolation
                    common.log_error(source=f"hf:{query}", err=exc)
            elif src_type == "hf_author":
                author = src.get("author")
                if not author:
                    continue
                try:
                    results.extend(
                        fetch_for_author_source(
                            mid,
                            author,
                            name_match=src.get("name_match"),
                            exclude=src.get("exclude"),
                            limit=int(src.get("limit", HF_AUTHOR_LIMIT)),
                        )
                    )
                except Exception as exc:  # noqa: BLE001 — per-source isolation
                    common.log_error(source=f"hf_author:{author}", err=exc)
    return results


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", help="Only fetch for this model id")
    p.add_argument("--out", help="Write output JSON to this path (else stdout)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    results = fetch_all(args.model)
    if args.out:
        common.write_json(args.out, results)
    else:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
