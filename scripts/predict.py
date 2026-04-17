"""Compute next-release predictions from data/releases.json.

CLI:
    python scripts/predict.py [--in data/releases.json] [--out data/predictions.json]
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import common  # noqa: E402


# Number of most-recent intervals to consider. AGENTS.md §8 says 3-5 events,
# i.e. 2-4 intervals. Keep the last 4 intervals = last 5 events.
RECENT_WINDOW_EVENTS = 5
# 95% confidence interval multiplier.
CI95 = 1.96
# Minimum data count (in events). < 2 events → predict nothing.
MIN_EVENTS = 2


def _parse_date(s: str | None) -> date | None:
    """Accept `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SSZ` and return a `date`."""
    if not s:
        return None
    head = s[:10]
    try:
        return datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        return None


# First occurrence of `N.M[.O...]` — a dot-separated numeric run.
_DOTTED_VER_RE = re.compile(r"\d+(?:\.\d+)+")
# Fallback: first bare integer.
_INT_VER_RE = re.compile(r"\d+")


def guess_next_version(version: str | None) -> str | None:
    """Increment the trailing numeric component of `version` and append `?`.

    See AGENTS.md §8 (predicted_version) for the rationale / algorithm.
    Returns None when no numeric component exists in `version`.
    """
    if not version:
        return None
    s = str(version)

    # Prefer dotted versions (`4.7`, `2.6.3`) — bump the last component.
    m = _DOTTED_VER_RE.search(s)
    if m:
        parts = m.group(0).split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        return f"{s[:m.start()]}{'.'.join(parts)}{s[m.end():]}?"

    # Fall back to the first integer (covers `v3`, `Nano Banana 2`).
    m = _INT_VER_RE.search(s)
    if m:
        bumped = str(int(m.group(0)) + 1)
        return f"{s[:m.start()]}{bumped}{s[m.end():]}?"

    return None


def compute_intervals(dates: list[date]) -> list[int]:
    """Return day-intervals between consecutive sorted dates."""
    if len(dates) < 2:
        return []
    sorted_dates = sorted(dates)
    return [(b - a).days for a, b in zip(sorted_dates, sorted_dates[1:])]


def predict_for_model(
    model_id: str,
    releases: list[dict[str, Any]],
    today: date | None = None,
) -> dict[str, Any]:
    """Compute prediction payload for a single model."""
    today = today or datetime.now(timezone.utc).date()
    # Parse and filter to entries with valid dates, sort ascending.
    parsed = [(r, _parse_date(r.get("date"))) for r in releases]
    parsed = [(r, d) for r, d in parsed if d is not None]
    parsed.sort(key=lambda pair: pair[1])

    if len(parsed) < MIN_EVENTS:
        last = parsed[-1] if parsed else None
        last_version = last[0].get("version") if last else None
        return {
            "last_version": last_version,
            "last_date": (last[1].isoformat() if last else None),
            "predicted_date": None,
            "predicted_version": guess_next_version(last_version),
            "note": "insufficient_data",
        }

    recent = parsed[-RECENT_WINDOW_EVENTS:]
    recent_dates = [d for _, d in recent]
    intervals = compute_intervals(recent_dates)

    median_interval = int(round(statistics.median(intervals)))
    mean_interval = int(round(statistics.fmean(intervals)))
    if len(intervals) >= 2:
        stdev = statistics.stdev(intervals)
    else:
        stdev = 0.0
    confidence_range = int(round(CI95 * stdev))

    last_record, last_date = parsed[-1]
    predicted = last_date + timedelta(days=median_interval)
    days_until = (predicted - today).days

    return {
        "last_version": last_record.get("version"),
        "last_date": last_date.isoformat(),
        "predicted_date": predicted.isoformat(),
        "predicted_version": guess_next_version(last_record.get("version")),
        "confidence_range_days": confidence_range,
        "mean_interval_days": mean_interval,
        "median_interval_days": median_interval,
        "days_until": days_until,
    }


def build_predictions(
    releases_by_model: dict[str, list[dict[str, Any]]],
    today: date | None = None,
) -> dict[str, Any]:
    """Top-level predictions.json payload."""
    out: dict[str, Any] = {
        "updated_at": common.utc_now_iso(),
        "models": {},
    }
    for model_id, releases in releases_by_model.items():
        out["models"][model_id] = predict_for_model(model_id, releases, today=today)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute next-release predictions")
    parser.add_argument(
        "--in",
        dest="in_path",
        default="data/releases.json",
        help="input releases.json (default: data/releases.json)",
    )
    parser.add_argument(
        "--out",
        default="data/predictions.json",
        help="output predictions.json (default: data/predictions.json)",
    )
    args = parser.parse_args(argv)

    releases = common.load_json(args.in_path, default={}) or {}
    if not isinstance(releases, dict):
        print(f"error: {args.in_path} must be a JSON object", file=sys.stderr)
        return 1

    payload = build_predictions(releases)
    common.write_json(args.out, payload)
    print(f"wrote predictions for {len(payload['models'])} models to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
