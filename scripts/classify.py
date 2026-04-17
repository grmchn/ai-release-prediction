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


BATCH_SIZE = 10

# Primary → fallback chain per AGENTS.md §7.
# litellm model name format: <provider>/<model>. Gemini / Gemma flow through
# `gemini/*`; Groq goes via `groq/*` and needs GROQ_API_KEY.
LLM_FALLBACKS: list[str] = [
    "gemini/gemma-4-31b-it",
    "gemini/gemma-4-26b-a4b-it",
    "gemini/gemma-3-27b-it",
    "groq/llama-3.3-70b-versatile",
]


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
                "summary": (entry.get("summary") or "")[:800],
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
        max_tokens=1500,
    )
    # litellm returns an OpenAI-style object.
    return response.choices[0].message.content or ""


def classify_batch(
    batch: list[dict[str, Any]],
    *,
    fallbacks: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Classify a batch, trying each model in the fallback chain until success."""
    models = fallbacks or LLM_FALLBACKS
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

    # All fallbacks failed — return a conservative "unknown" result per entry
    # so the pipeline can still move forward without the LLM.
    raise RuntimeError(f"classify: all models failed: {last_err}")


def classify_entries(
    entries: list[dict[str, Any]],
    *,
    batch_size: int = BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Run the classifier over `entries` and merge results back into each entry."""
    out: list[dict[str, Any]] = []
    for start in range(0, len(entries), batch_size):
        batch = entries[start : start + batch_size]
        try:
            judgments = classify_batch(batch)
        except Exception as err:  # noqa: BLE001 — skip the batch, continue pipeline
            common.log_error(
                source="classify:batch",
                err=err,
                extra={"start": start, "size": len(batch)},
            )
            # Emit unclassified entries so downstream merge sees something.
            for entry in batch:
                out.append({**entry, "classification": None})
            continue

        for i, entry in enumerate(batch):
            judgment = _find_judgment(judgments, i)
            out.append({**entry, "classification": judgment})
    return out


def _find_judgment(judgments: list[dict[str, Any]], idx: int) -> dict[str, Any] | None:
    """Retrieve the judgment for `idx`, tolerating missing or renumbered items."""
    if idx < len(judgments) and judgments[idx].get("entry_index") == idx:
        return judgments[idx]
    for j in judgments:
        if j.get("entry_index") == idx:
            return j
    return judgments[idx] if idx < len(judgments) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify fetch_rss output with Gemma 4")
    parser.add_argument("--in", dest="in_path", required=True, help="path to fetch_rss JSON")
    parser.add_argument("--out", default=None, help="write classified JSON here (default: stdout)")
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

    classified = classify_entries(entries)
    if args.out:
        common.write_json(args.out, classified)
        print(f"wrote {len(classified)} classified entries to {args.out}", file=sys.stderr)
    else:
        json.dump(classified, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
