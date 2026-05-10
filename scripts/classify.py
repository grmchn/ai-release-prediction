"""Classify fetch_rss output with Gemma 4 (Gemini API) + litellm fallback chain.

CLI:
    python scripts/classify.py --in data/raw/rss.json [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except Exception:  # noqa: BLE001 — dotenv is optional at runtime
    pass

from scripts import common  # noqa: E402


# Larger batches = fewer LLM calls = less RPM pressure on the free tier.
# Cap at 10 so a full-batch JSON response comfortably fits MAX_TOKENS even
# when every entry extracts a long model_name/version.
BATCH_SIZE = 10
# Sleep between batches to stay under Gemini free-tier RPM limits. The free
# tier historically caps Gemma at a few RPM; 4s pacing keeps us well under.
BATCH_SLEEP_SEC = 4.0
# Per-request cap on generation. Must hold BATCH_SIZE JSON objects with
# headroom — each object is ~120-160 tokens, so 4000 covers a full batch
# with a safety margin. (The previous 800 truncated 20-item batches mid-JSON
# and silently dropped real releases such as GPT-5.5 on 2026-04-23.)
MAX_TOKENS = 4000
# Longest summary we feed the LLM per entry. Title carries most of the
# classification signal; summary is a backup.
SUMMARY_TRUNCATE = 300

# Primary → fallback chain per AGENTS.md §7.
# litellm model name format: <provider>/<model>. Gemini / Gemma flow through
# `gemini/*`; Groq goes via `groq/*` and needs GROQ_API_KEY.
LLM_FALLBACKS: list[str] = [
    "gemini/gemma-4-31b-it",
    "gemini/gemma-4-26b-a4b-it",
    "gemini/gemma-3-27b-it",
    "groq/llama-3.3-70b-versatile",
]


def _active_fallbacks() -> list[str]:
    """Drop fallback entries whose API key is not configured.

    Saves a pointless round-trip + error when e.g. GROQ_API_KEY is absent.
    """
    active: list[str] = []
    for model in LLM_FALLBACKS:
        if model.startswith("gemini/") and not os.environ.get("GEMINI_API_KEY"):
            continue
        if model.startswith("groq/") and not os.environ.get("GROQ_API_KEY"):
            continue
        active.append(model)
    return active


PROMPT_TEMPLATE = """You are a release-note classifier for an AI-model tracker.

For each input entry, decide if it is announcing a NEW model release (or a
meaningful versioned update of a model the team tracks: LLM, image, or video).
Posts about case studies, papers, unrelated product announcements, and
general commentary are NOT releases.

Return STRICT JSON: a single array with one object per entry, in the SAME order
as the inputs. No prose, no code fences, no trailing commas. Schema:

[
  {{
    "entry_index": 0,
    "is_release": true,
    "model_name": "Claude Sonnet 4.7",
    "version": "4.7",
    "category": "llm",
    "release_date": "2026-04-17",
    "confidence": 0.95
  }}
]

Fields:
- entry_index: integer, 0-based, matches the input order
- is_release: boolean
- model_name: human model name (e.g. "Claude Opus", "Qwen3"); null if unknown
- version: version string (e.g. "4.7", "3.1 Pro"); null if unknown
- category: one of "llm", "image", "video", "other"
- release_date: ISO date YYYY-MM-DD or null if unknown
- confidence: float 0..1

Examples of is_release=false: "Claude in education", "Anthropic research partnership",
"OpenAI enterprise launch", papers, case studies, token limit changes,
pricing updates that do not introduce a new model version.

Inputs (one JSON object per entry):

{entries_json}

Return only the JSON array."""


def _strip_code_fences(text: str) -> str:
    """Remove ```json / ``` wrapping and strip leading/trailing whitespace."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """Parse `text` as a JSON array, tolerating stray prose around it."""
    cleaned = _strip_code_fences(text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fall back to grabbing the first `[...]` block.
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise ValueError(f"expected JSON array, got {type(parsed).__name__}")
    return parsed


def _build_prompt(batch: list[dict[str, Any]]) -> str:
    """Render `batch` into the classifier prompt."""
    entries_for_llm = []
    for i, entry in enumerate(batch):
        entries_for_llm.append(
            {
                "entry_index": i,
                "title": entry.get("title", ""),
                "summary": (entry.get("summary") or "")[:SUMMARY_TRUNCATE],
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "hint_model_id": entry.get("model_id", ""),
            }
        )
    return PROMPT_TEMPLATE.format(entries_json=json.dumps(entries_for_llm, ensure_ascii=False, indent=2))


def _call_litellm(model: str, prompt: str) -> str:
    """Single LLM call via litellm; returns raw text content."""
    import litellm  # imported lazily so tests can mock it without extras

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=MAX_TOKENS,
        timeout=60,
    )
    # litellm returns an OpenAI-style object.
    return response.choices[0].message.content or ""


def classify_batch(
    batch: list[dict[str, Any]],
    *,
    fallbacks: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Classify a batch, trying each model in the fallback chain until success."""
    models = fallbacks if fallbacks is not None else _active_fallbacks()
    if not models:
        raise RuntimeError("classify: no LLM keys configured (GEMINI_API_KEY / GROQ_API_KEY)")
    prompt = _build_prompt(batch)
    last_err: Exception | None = None

    for model in models:
        try:
            raw = _call_litellm(model, prompt)
            parsed = _extract_json_array(raw)
            if len(parsed) != len(batch):
                raise ValueError(
                    f"{model}: expected {len(batch)} items, got {len(parsed)}"
                )
            return parsed
        except Exception as err:  # noqa: BLE001 — try next model
            common.log_error(
                source=f"classify:{model}",
                err=err,
                extra={"batch_size": len(batch)},
            )
            last_err = err
            continue

    # All fallbacks failed — raise so the caller can skip the batch rather
    # than silently producing empty classifications.
    raise RuntimeError(f"classify: all models failed: {last_err}")


def classify_entries(
    entries: list[dict[str, Any]],
    *,
    batch_size: int = BATCH_SIZE,
    batch_sleep_sec: float = BATCH_SLEEP_SEC,
) -> list[dict[str, Any]]:
    """Run the classifier over `entries` and merge results back into each entry."""
    out: list[dict[str, Any]] = []
    total_batches = (len(entries) + batch_size - 1) // batch_size
    for idx, start in enumerate(range(0, len(entries), batch_size)):
        batch = entries[start : start + batch_size]
        if idx > 0 and batch_sleep_sec > 0:
            # Space out LLM calls to stay under free-tier RPM caps.
            time.sleep(batch_sleep_sec)

        print(
            f"[classify] batch {idx + 1}/{total_batches} ({len(batch)} entries)",
            file=sys.stderr,
            flush=True,
        )

        try:
            judgments = classify_batch(batch)
        except Exception as err:  # noqa: BLE001 — try split-retry before giving up
            common.log_error(
                source="classify:batch",
                err=err,
                extra={"start": start, "size": len(batch), "phase": "initial"},
            )
            judgments = _classify_with_split_retry(batch)

        for i, entry in enumerate(batch):
            judgment = _find_judgment(judgments, i)
            out.append({**entry, "classification": judgment})
    return out


def _classify_with_split_retry(
    batch: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Retry a failed batch by halving it until each call succeeds.

    When a batch fails (e.g. the LLM truncates the JSON response mid-array),
    this halves the batch and retries each side. Single entries that still
    fail after all fallback models receive a null judgment so the downstream
    merge step skips them cleanly rather than misclassifying them.
    """
    if not batch:
        return []
    if len(batch) == 1:
        try:
            judgments = classify_batch(batch)
            return [{**judgments[0], "entry_index": 0}]
        except Exception as err:  # noqa: BLE001 — give up on this single entry
            common.log_error(
                source="classify:batch-split-single",
                err=err,
                extra={"title": batch[0].get("title", "")[:120]},
            )
            return [{"entry_index": 0, **_null_judgment()}]

    mid = len(batch) // 2
    halves = [(0, batch[:mid]), (mid, batch[mid:])]
    results: list[dict[str, Any]] = []
    for offset, half in halves:
        try:
            judgments = classify_batch(half)
        except Exception as err:  # noqa: BLE001 — recurse into smaller chunks
            common.log_error(
                source="classify:batch-split",
                err=err,
                extra={"half_size": len(half)},
            )
            judgments = _classify_with_split_retry(half)
        for i in range(len(half)):
            j = _find_judgment(judgments, i) if judgments else None
            if j is None:
                j = _null_judgment()
            results.append({**j, "entry_index": offset + i})
    return results


def _null_judgment() -> dict[str, Any]:
    """Neutral judgment used when an LLM call for a single entry still fails."""
    return {
        "is_release": False,
        "model_name": None,
        "version": None,
        "category": "other",
        "release_date": None,
        "confidence": 0.0,
    }


def _find_judgment(judgments: list[dict[str, Any]], idx: int) -> dict[str, Any] | None:
    """Retrieve the judgment for `idx`, tolerating missing or renumbered items."""
    if idx < len(judgments) and judgments[idx].get("entry_index") == idx:
        return judgments[idx]
    for j in judgments:
        if j.get("entry_index") == idx:
            return j
    return judgments[idx] if idx < len(judgments) else None


def _entry_cache_key(entry: dict[str, Any]) -> str | None:
    """Return a stable identity key for one RSS entry."""
    link = str(entry.get("link") or "").strip()
    if link:
        return f"link::{link}"

    model_id = str(entry.get("model_id") or "").strip()
    title = str(entry.get("title") or "").strip()
    published = str(entry.get("published") or "").strip()
    if model_id and title and published:
        return f"entry::{model_id}::{title}::{published}"
    return None


def _load_classification_cache(path: str | Path | None) -> dict[str, dict[str, Any]]:
    """Load previous classified entries keyed by RSS entry identity."""
    if not path:
        return {}
    cached_entries = common.load_json(path, default=[])
    if not isinstance(cached_entries, list):
        return {}

    cache: dict[str, dict[str, Any]] = {}
    for entry in cached_entries:
        if not isinstance(entry, dict):
            continue
        classification = entry.get("classification")
        if not isinstance(classification, dict):
            continue
        key = _entry_cache_key(entry)
        if key:
            cache[key] = classification
    return cache


def _load_existing_release_cache(path: str | Path = "data/releases.json") -> dict[str, dict[str, Any]]:
    """Load existing releases keyed by source URL.

    The cache is deliberately URL-only. Version inference from RSS titles is
    easy to make too aggressive; URLs already present in releases.json are a
    safe skip target because merge_releases.py would deduplicate them anyway.
    """
    releases = common.load_json(path, default={}) or {}
    if not isinstance(releases, dict):
        return {}

    cache: dict[str, dict[str, Any]] = {}
    for model_id, items in releases.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            cache[url] = {
                "is_release": True,
                "model_name": item.get("note") or None,
                "version": item.get("version"),
                "category": "other",
                "release_date": item.get("date"),
                "confidence": 1.0,
                "cached_from": "releases.json",
                "cached_model_id": model_id,
            }
    return cache


def classify_entries_with_cache(
    entries: list[dict[str, Any]],
    *,
    previous_classified_path: str | Path | None = None,
    releases_path: str | Path = "data/releases.json",
    batch_size: int = BATCH_SIZE,
    batch_sleep_sec: float = BATCH_SLEEP_SEC,
) -> list[dict[str, Any]]:
    """Classify only entries that are not already known."""
    classification_cache = _load_classification_cache(previous_classified_path)
    release_cache = _load_existing_release_cache(releases_path)

    out: list[dict[str, Any] | None] = [None] * len(entries)
    pending: list[tuple[int, dict[str, Any]]] = []
    cache_hits = 0
    release_hits = 0

    for idx, entry in enumerate(entries):
        key = _entry_cache_key(entry)
        cached = classification_cache.get(key or "")
        if cached is not None:
            out[idx] = {**entry, "classification": cached}
            cache_hits += 1
            continue

        link = str(entry.get("link") or "").strip()
        release_cached = release_cache.get(link)
        if release_cached is not None:
            out[idx] = {**entry, "classification": release_cached}
            release_hits += 1
            continue

        pending.append((idx, entry))

    total_batches = (len(pending) + batch_size - 1) // batch_size if pending else 0
    print(
        "[classify] input="
        f"{len(entries)} cached={cache_hits} existing_releases={release_hits} "
        f"llm={len(pending)} batches={total_batches}",
        file=sys.stderr,
        flush=True,
    )

    if pending:
        classified_pending = classify_entries(
            [entry for _, entry in pending],
            batch_size=batch_size,
            batch_sleep_sec=batch_sleep_sec,
        )
        for (original_idx, _), classified in zip(pending, classified_pending, strict=True):
            out[original_idx] = classified

    return [item if item is not None else {**entries[idx], "classification": None} for idx, item in enumerate(out)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify fetch_rss output with Gemma 4")
    parser.add_argument("--in", dest="in_path", required=True, help="path to fetch_rss JSON")
    parser.add_argument("--out", default=None, help="write classified JSON here (default: stdout)")
    parser.add_argument(
        "--releases",
        default="data/releases.json",
        help="path to cumulative releases.json for safe RSS skip checks",
    )
    args = parser.parse_args(argv)

    entries = common.load_json(args.in_path, default=[])
    if not entries:
        print("no entries to classify", file=sys.stderr)
        if args.out:
            common.write_json(args.out, [])
        return 0

    # Require at least one key to proceed; otherwise the LLM calls will all fail.
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")):
        print(
            "warning: no GEMINI_API_KEY or GROQ_API_KEY in environment; "
            "classification will log errors per batch",
            file=sys.stderr,
        )

    classified = classify_entries_with_cache(
        entries,
        previous_classified_path=args.out,
        releases_path=args.releases,
    )
    if args.out:
        common.write_json(args.out, classified)
        print(f"wrote {len(classified)} classified entries to {args.out}", file=sys.stderr)
    else:
        json.dump(classified, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
