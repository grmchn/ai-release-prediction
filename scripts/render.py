"""Render docs/index.html from releases.json + predictions.json.

CLI:
    python scripts/render.py \\
      [--releases data/releases.json] \\
      [--predictions data/predictions.json] \\
      [--template templates/index.html.j2] \\
      [--out docs/index.html]
"""
from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import common  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")

# Display ordering: category buckets, then model order inside each bucket.
CATEGORY_ORDER = ["llm", "image", "video"]
CATEGORY_JP = {"llm": "LLM", "image": "IMAGE", "video": "VIDEO"}


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _format_dot_date(d: date | None) -> str:
    return d.strftime("%Y.%m.%d") if d else ""


def display_version(name: str, version: str | None) -> str:
    """Join `name` + `version` without duplicating the brand prefix.

    Tokenize the name on alphanumeric runs and greedily match tokens at the
    start of `version`, skipping non-alphanumeric separators between them.
    Whatever is left after the longest match is the real version tail.

    Examples (all verified in tests/test_render.py):
        display_version("Claude Opus", "4.7")              → "Claude Opus 4.7"
        display_version("Nano Banana", "Nano Banana 2 …")  → "Nano Banana 2 …"
        display_version("GPT-Image", "gpt-image-1.5")       → "GPT-Image 1.5"
        display_version("LTX Video", "LTX-2.3")             → "LTX Video 2.3"
        display_version("Qwen", "Qwen3.6-Plus")             → "Qwen 3.6-Plus"
    """
    import re as _re

    v = (version or "").strip()
    n = (name or "").strip()
    if not v:
        return n
    if not n:
        return v
    name_tokens = [t.lower() for t in _re.findall(r"[A-Za-z0-9]+", n)]
    if not name_tokens:
        return f"{n} {v}".strip()

    i = 0
    last_matched_end = 0
    for token in name_tokens:
        # Skip any leading separators before the next token.
        while i < len(v) and not v[i].isalnum():
            i += 1
        if i + len(token) > len(v):
            break
        if v[i : i + len(token)].lower() != token:
            break
        i += len(token)
        last_matched_end = i

    if last_matched_end > 0:
        remainder = v[last_matched_end:].lstrip(" -_.")
        return f"{n} {remainder}".strip() if remainder else n
    return f"{n} {v}".strip()


def _format_short_date(d: date | None) -> str:
    return d.strftime("%m.%d") if d else ""


def build_month_window(today: date, *, back: int = 16, total: int = 24) -> list[dict[str, Any]]:
    """Return `total` month cells starting `back` months before `today`.

    Defaults to a 24-month window (~16 months back, ~8 months forward) so the
    UI can scroll back to the previous calendar year while still showing a
    reasonable prediction horizon ahead.
    """
    # Walk back `back` months from today's first-of-month.
    y, m = today.year, today.month
    m -= back
    while m <= 0:
        m += 12
        y -= 1
    start = date(y, m, 1)

    cells: list[dict[str, Any]] = []
    for i in range(total):
        yy, mm = start.year, start.month + i
        while mm > 12:
            mm -= 12
            yy += 1
        cell: dict[str, Any] = {
            "year": yy,
            "month": mm,
            "label": f"{mm}月",
            "is_now": yy == today.year and mm == today.month,
            "year_label": None,
            "days_in_month": calendar.monthrange(yy, mm)[1],
        }
        # Annotate year label on January (or on the first cell when the
        # window starts mid-year).
        if mm == 1 or i == 0:
            cell["year_label"] = f"'{str(yy)[-2:]}"
        cells.append(cell)
    return cells


def window_bounds(cells: list[dict[str, Any]]) -> tuple[date, date, int]:
    """Return (window_start, window_end_exclusive, total_days)."""
    start = date(cells[0]["year"], cells[0]["month"], 1)
    last = cells[-1]
    end_month_last_day = calendar.monthrange(last["year"], last["month"])[1]
    end = date(last["year"], last["month"], end_month_last_day) + timedelta(days=1)
    return start, end, (end - start).days


def date_to_percent(target: date, cells: list[dict[str, Any]]) -> float | None:
    """Map `target` into 0..100 across the 12-month window. None if out of range."""
    start, end, total = window_bounds(cells)
    if target < start or target >= end:
        return None
    offset = (target - start).days
    return round(100.0 * offset / total, 3)


def now_percent(today: date, cells: list[dict[str, Any]]) -> float:
    """Percentage position of today's date within the window (clamped to 0..100)."""
    p = date_to_percent(today, cells)
    return p if p is not None else 0.0


def now_month_index(today: date, cells: list[dict[str, Any]]) -> int:
    """Index (0..11) of today's month cell; -1 if the window doesn't include it."""
    for i, cell in enumerate(cells):
        if cell["year"] == today.year and cell["month"] == today.month:
            return i
    return -1


def build_timeline_rows(
    models_config: list[dict[str, Any]],
    releases: dict[str, list[dict[str, Any]]],
    predictions: dict[str, Any],
    cells: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble the timelineData array the client JS expects."""
    out: list[dict[str, Any]] = []
    for cat in CATEGORY_ORDER:
        # Category header row
        out.append({"category": CATEGORY_JP[cat]})
        for model in models_config:
            if model.get("category") != cat:
                continue
            model_id = model["id"]
            bucket = releases.get(model_id, [])
            prediction = (predictions.get("models") or {}).get(model_id) or {}

            events = []
            for r in sorted(bucket, key=lambda x: x.get("date") or ""):
                d = _parse_date(r.get("date"))
                if not d:
                    continue
                pct = date_to_percent(d, cells)
                if pct is None:
                    continue
                version_str = r.get("version") or ""
                events.append(
                    {
                        "percent": pct,
                        "version": version_str,
                        "date": _format_dot_date(d),
                        "note": r.get("note") or "",
                        "label": display_version(model["name"], version_str) if version_str else model["name"],
                    }
                )
            # Mark the last event as major so the UI styles it distinctly.
            if events:
                events[-1]["major"] = True

            row: dict[str, Any] = {
                "name": model["name"],
                "vendor": model["vendor"],
                "events": events,
            }

            predicted = _parse_date(prediction.get("predicted_date"))
            if predicted:
                range_days = prediction.get("confidence_range_days") or 0
                start_pct = date_to_percent(predicted - timedelta(days=range_days), cells)
                end_pct = date_to_percent(predicted + timedelta(days=range_days), cells)
                peak_pct = date_to_percent(predicted, cells)
                # Clamp to [0, 100] so the band still renders when the range
                # spills outside the window.
                if peak_pct is not None:
                    if start_pct is None:
                        start_pct = 0.0
                    if end_pct is None:
                        end_pct = 100.0
                    pv = prediction.get("predicted_version")
                    row["prediction"] = {
                        "start": max(0.0, start_pct),
                        "end": min(100.0, end_pct),
                        "peak": peak_pct,
                        "date": _format_dot_date(predicted),
                        "range": f"±{range_days}日",
                        "predicted_version": pv,
                        "predicted_full": display_version(model["name"], pv) if pv else model["name"],
                    }
            out.append(row)
    return out


def build_cards(
    models_config: list[dict[str, Any]],
    releases: dict[str, list[dict[str, Any]]],
    predictions: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the per-model card context."""
    cards: list[dict[str, Any]] = []
    # Preserve category ordering: llm → image → video.
    ordered = sorted(
        models_config,
        key=lambda m: (CATEGORY_ORDER.index(m.get("category", "other"))
                       if m.get("category") in CATEGORY_ORDER else len(CATEGORY_ORDER)),
    )
    for model in ordered:
        model_id = model["id"]
        bucket = releases.get(model_id, [])
        latest = max(bucket, key=lambda r: r.get("date") or "") if bucket else {}
        prediction = (predictions.get("models") or {}).get(model_id) or {}
        predicted = _parse_date(prediction.get("predicted_date"))
        days_until = prediction.get("days_until")

        if predicted and prediction.get("confidence_range_days") is not None:
            predicted_display = f"{_format_short_date(predicted)} ±{prediction['confidence_range_days']}日"
        else:
            predicted_display = ""

        countdown_value: str
        countdown_label = "次のリリースまで"
        countdown_unit = "日"
        if days_until is None:
            countdown_value = "—"
        elif days_until < 0:
            countdown_value = str(-days_until)
            countdown_label = "予測日からの経過"
        else:
            countdown_value = str(days_until)

        display_name = model.get("name", model_id)
        latest_version = latest.get("version") or prediction.get("last_version") or ""
        predicted_version = prediction.get("predicted_version")
        cards.append(
            {
                "id": model_id,
                "category": model.get("category", ""),
                "vendor": model.get("vendor", ""),
                "name": display_name,
                "countdown_value": countdown_value,
                "countdown_unit": countdown_unit,
                "countdown_label": countdown_label,
                "last_date": _format_dot_date(_parse_date(latest.get("date"))),
                "predicted_display": predicted_display,
                "predicted_version": predicted_version,
                "mean_interval_days": prediction.get("mean_interval_days"),
                "latest_version": latest_version,
                # Pre-rendered lines so the Jinja template stays dumb.
                "latest_full": display_version(display_name, latest_version) if latest_version else "",
                "predicted_full": display_version(display_name, predicted_version) if predicted_version else "",
            }
        )
    return cards


def _jst_display(iso_utc: str | None) -> str:
    """`2026-04-17T03:00:00Z` → `最終更新 2026-04-17 12:00 JST`."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return iso_utc
    local = dt.astimezone(JST)
    return f"最終更新 {local.strftime('%Y-%m-%d %H:%M')} JST"


def build_context(
    releases: dict[str, list[dict[str, Any]]],
    predictions: dict[str, Any],
    models_config: list[dict[str, Any]],
    *,
    today: date | None = None,
    refresh_interval: str = "6h",
) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    cells = build_month_window(today)
    return {
        "updated_at_display": _jst_display(predictions.get("updated_at")) or _jst_display(common.utc_now_iso()),
        "refresh_interval": refresh_interval,
        "months": cells,
        "total_months": len(cells),
        "now_percent": now_percent(today, cells),
        "now_month_index": now_month_index(today, cells),
        "timeline_data": build_timeline_rows(models_config, releases, predictions, cells),
        "models": build_cards(models_config, releases, predictions),
    }


def render_html(context: dict[str, Any], template_path: Path) -> str:
    env = Environment(
        loader=FileSystemLoader(template_path.parent),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    template = env.get_template(template_path.name)
    return template.render(**context)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render docs/index.html")
    parser.add_argument("--releases", default="data/releases.json")
    parser.add_argument("--predictions", default="data/predictions.json")
    parser.add_argument("--template", default="templates/index.html.j2")
    parser.add_argument("--out", default="docs/index.html")
    parser.add_argument("--models", default="data/models.yaml")
    args = parser.parse_args(argv)

    releases = common.load_json(args.releases, default={}) or {}
    predictions = common.load_json(args.predictions, default={}) or {}
    models_config = common.load_models(args.models)

    context = build_context(releases, predictions, models_config)
    template_path = Path(args.template)
    if not template_path.is_absolute():
        template_path = REPO_ROOT / template_path
    html = render_html(context, template_path)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {len(html)} bytes to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
