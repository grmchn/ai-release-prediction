"""Shared helpers for fetch / classify / merge / predict / render scripts.

All fetchers should use these utilities to keep HTTP behavior, raw-data
persistence, version normalization and error logging consistent.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

USER_AGENT = (
    "ai-release-prediction/0.1 "
    "(+https://github.com/grmchn/ai-release-prediction)"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
LOGS_DIR = REPO_ROOT / "logs"


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """Return current UTC time as `2026-04-17T03:00:00Z`."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_compact() -> str:
    """Return UTC timestamp usable as a filename suffix (`YYYYMMDDHHMMSS`)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class HTTPError(RuntimeError):
    """Raised when `http_get` exhausts all retries."""


def http_get(
    url: str,
    *,
    timeout: float = 10.0,
    retries: int = 3,
    headers: dict[str, str] | None = None,
    backoff_base: float = 1.5,
) -> requests.Response:
    """GET `url` with a stable User-Agent, timeout and exponential backoff.

    The returned response has `encoding` populated — callers should hand the
    response body to feedparser / json.loads via `.text` / `.json()` so the
    declared encoding is honored.
    """
    merged_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        merged_headers.update(headers)

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=merged_headers, timeout=timeout)
            resp.raise_for_status()
            # Make sure feedparser / json see a concrete encoding.
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                # requests falls back to iso-8859-1 for text/* without charset;
                # prefer apparent_encoding when that happens.
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp
        except Exception as err:  # noqa: BLE001 — re-raised after retries
            last_err = err
            if attempt == retries - 1:
                break
            time.sleep(backoff_base ** attempt)
    raise HTTPError(f"GET {url} failed after {retries} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------


def load_models(path: str | Path = "data/models.yaml") -> list[dict[str, Any]]:
    """Load the `models:` array from `data/models.yaml`."""
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    models = data.get("models") or []
    if not isinstance(models, list):
        raise ValueError(f"{p}: `models` must be a list")
    return models


# ---------------------------------------------------------------------------
# Raw payload persistence
# ---------------------------------------------------------------------------


def save_raw(model_id: str, source_type: str, payload: Any) -> Path:
    """Persist `payload` under `data/raw/{model_id}/{source}_{ts}.json`."""
    subdir = RAW_DIR / model_id
    subdir.mkdir(parents=True, exist_ok=True)
    out = subdir / f"{source_type}_{utc_now_compact()}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return out


# ---------------------------------------------------------------------------
# Version normalization & dedup keys
# ---------------------------------------------------------------------------


_VERSION_NUMERIC_RE = re.compile(r"(\d+(?:[.\-_]\d+){0,4})([a-zA-Z0-9+]*)")
_TRIM_PREFIX_RE = re.compile(r"^(version|ver\.?|v)\s*", re.IGNORECASE)

# Suffixes that denote format/precision/distillation variants of the SAME base
# release — strip them for dedup. Order matters: longer patterns first so
# `bf16` doesn't shadow `fp16`. Matches trailing tokens after `-` / `_` / space.
_QUANT_SUFFIX_RE = re.compile(
    r"([-_.\s]+(?:"
    r"fp16|fp8|fp4|bf16|bf8|"
    r"int4|int8|int16|"
    r"q[2-8](?:[_-][a-z0-9]+)*|"
    r"4bit|8bit|16bit|"
    r"gguf|awq|gptq|aqlm|exl2|mlx|"
    r"distilled|distill|"
    r"lora|qlora|qat|"
    r"safetensors|onnx"
    r"))+\s*$",
    re.IGNORECASE,
)


def normalize_version(value: str | None) -> str:
    """Normalize a version string for dedup comparison.

    Rules (kept deliberately simple — we only need stable equality):
    - Lowercase, strip whitespace
    - Drop leading `v` / `version` / `ver.`
    - Collapse `_` and `-` separators between digits to `.`
    - Preserve suffix qualifiers such as `pro`, `max`, `mini` — those are
      different releases, not spelling variants.
    """
    if value is None:
        return ""
    s = str(value).strip().lower()
    if not s:
        return ""
    s = _TRIM_PREFIX_RE.sub("", s)
    # Strip format/precision/distillation suffixes so `LTX-2.3-fp8` and
    # `LTX-2.3` collapse to the same version. Apply repeatedly until a fixed
    # point because variants sometimes chain (`...-fp8-safetensors`).
    prev = None
    while prev != s:
        prev = s
        s = _QUANT_SUFFIX_RE.sub("", s).rstrip("-_. ")
    # Change digit separators `_`/`-` to `.` so `4-7` and `4.7` compare equal.
    s = re.sub(r"(?<=\d)[_\-](?=\d)", ".", s)
    # Convert remaining `-`/`_` (word separators) to whitespace so
    # `claude-sonnet-4-7` matches `Claude Sonnet 4.7`.
    s = re.sub(r"[_\-]+", " ", s)
    # Collapse trailing `.0` blocks: `3.0` ≡ `3`, `4.5.0` ≡ `4.5`,
    # `5.0 Lite` ≡ `5 Lite`. Preserves `3.01` / `3.10` etc. untouched.
    s = re.sub(r"(\.0)+(?=\s|$|[^0-9])", "", s)
    # Collapse repeated whitespace.
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def dedup_key(model_id: str, version: str | None) -> str:
    """Composite `(model_id, normalized_version)` key for dedup comparisons."""
    return f"{model_id}::{normalize_version(version or '')}"


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------


def log_error(source: str, err: Exception | str, *, extra: dict[str, Any] | None = None) -> None:
    """Append a single error line to `logs/errors.jsonl` (UTC timestamped).

    Designed so a single fetcher failure never stops the full pipeline.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "ts": utc_now_iso(),
        "source": source,
        "error": str(err),
        "error_type": type(err).__name__ if isinstance(err, Exception) else "str",
    }
    if extra:
        record["extra"] = extra
    with (LOGS_DIR / "errors.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def write_json(path: str | Path, payload: Any) -> Path:
    """Write `payload` to `path` as pretty UTF-8 JSON."""
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return p


def load_json(path: str | Path, default: Any = None) -> Any:
    """Load JSON from `path`; return `default` if the file does not exist."""
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)
