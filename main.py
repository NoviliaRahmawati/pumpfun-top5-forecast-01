#!/usr/bin/env python3
"""Deterministic momentum-aware forecast for pumpfun-top5-forecast-01.

Reads task.json and history.ndjson from /input and writes forecast.json to
/output. For local replay, MAKEFUN_INPUT_DIR and MAKEFUN_OUTPUT_DIR override
those paths. Uses Python 3.13 standard library only.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
# Reserve some probability for coins created after the last observed mark.
NAMED_MASS = 0.82
MICRO = 1_000_000


def read_history(path: Path) -> list[dict[str, Any]]:
    marks: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                mark = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid history JSON on line {line_no}") from exc
            if mark.get("ok") is True and isinstance(mark.get("rows"), list):
                marks.append(mark)
    if not marks or not marks[-1]["rows"]:
        raise ValueError("history has no successful mark with ranked rows")
    return marks


def log_cap(row: dict[str, Any]) -> float:
    value = int(row["market_cap_lamports"])
    if value <= 0:
        raise ValueError("market_cap_lamports must be positive")
    # Scorer's size unit: log10(cap in SOL).
    return math.log10(value) - 9.0


def build_forecast(task: dict[str, Any], marks: list[dict[str, Any]]) -> dict[str, Any]:
    places = int(task["places"])
    edges = [float(x) for x in task["size"]["edges"]]
    if places < 1 or not edges:
        raise ValueError("task must define places and size edges")

    # Keep only rows from successful marks; the latest mark is the ranking cut.
    latest = marks[-1]
    current_rows = sorted(latest["rows"], key=lambda row: int(row["rank"]))
    if len(current_rows) < places:
        raise ValueError("latest successful mark has fewer rows than scored places")

    # Estimate short-term log-cap velocity over available observations. Shrink
    # it toward zero: a brief launchpad pump is not a reliable multi-hour trend.
    by_mint: dict[str, list[tuple[int, float, dict[str, Any]]]] = {}
    for mark_idx, mark in enumerate(marks):
        for row in mark["rows"]:
            mint = row.get("mint")
            if isinstance(mint, str):
                by_mint.setdefault(mint, []).append((mark_idx, log_cap(row), row))

    last_idx = len(marks) - 1
    # Forecast center is the middle of the 7-13 hour answer window (10 hours).
    # One history mark is one 10-minute interval for this competition.
    horizon_steps = 60
    candidates: list[dict[str, Any]] = []
    for row in current_rows:
        mint = row["mint"]
        observations = by_mint.get(mint, [])
        # Use the latest two observed changes, capped to avoid extrapolating
        # pathological one-tick jumps; missing marks do not count as zero.
        deltas: list[float] = []
        for (_, old_cap, _), (_, new_cap, _) in zip(observations, observations[1:]):
            deltas.append(new_cap - old_cap)
        recent = deltas[-3:]
        velocity = sum(recent) / len(recent) if recent else 0.0
        # Strong shrinkage is intentional for a long horizon and noisy asset.
        projected = log_cap(row) + max(-0.035, min(0.035, velocity)) * horizon_steps * 0.12
        # Modest persistence advantage for a coin repeatedly visible in marks.
        persistence = min(0.10, 0.025 * max(0, len(observations) - 1))
        projected += persistence
        candidates.append({"mint": mint, "row": row, "center": projected,
                           "observations": observations, "velocity": velocity})

    candidates.sort(key=lambda item: (-item["center"], int(item["row"]["rank"]), item["mint"]))
    ranked = candidates[:max(places, min(len(candidates), int(task.get("chart_size", 100))))]
    if len(ranked) < places:
        raise ValueError("not enough candidates to forecast all places")
    top5 = [item["mint"] for item in ranked[:places]]

    # Name a smoothed probability distribution over the observed chart for
    # each place. A small residual is deliberately left unnamed for new coins.
    probabilities: list[dict[str, Any]] = []
    rank_temp = 0.34
    for place in range(places):
        target = ranked[place]["center"]
        weights = [math.exp(-abs(item["center"] - target) / rank_temp) for item in ranked]
        total = sum(weights)
        raw = [NAMED_MASS * weight / total for weight in weights]
        # Round down like the harness starter; residual mass remains unnamed.
        probs = [math.floor(p * MICRO) / MICRO for p in raw]
        for item, p in zip(ranked, probs):
            if p > 0:
                probabilities.append({"mint": item["mint"], "place": place + 1, "p": p})

    # Market-cap size distribution: mix candidate forecast centers according to
    # the place probabilities, then spread each center over log-cap bins with a
    # broad normal kernel. The CDF is integrated with erfc; tails are explicit.
    sizes: list[dict[str, Any]] = []
    size_sd = 0.62
    bin_count = len(edges) + 1
    for place in range(places):
        target = ranked[place]["center"]
        weights = [math.exp(-abs(item["center"] - target) / rank_temp) for item in ranked]
        weight_total = sum(weights)
        mix = [weight / weight_total for weight in weights]

        def cdf(x: float, mean: float) -> float:
            if x == -math.inf:
                return 0.0
            if x == math.inf:
                return 1.0
            return 0.5 * math.erfc(-(x - mean) / (size_sd * math.sqrt(2.0)))

        bin_ps: list[float] = []
        for bin_idx in range(bin_count):
            lo = -math.inf if bin_idx == 0 else edges[bin_idx - 1]
            hi = math.inf if bin_idx == len(edges) else edges[bin_idx]
            mass = sum(w * (cdf(hi, item["center"]) - cdf(lo, item["center"]))
                       for w, item in zip(mix, ranked))
            bin_ps.append(max(0.0, mass))
        norm = sum(bin_ps)
        for bin_idx, mass in enumerate(bin_ps):
            p = math.floor((mass / norm) * MICRO) / MICRO if norm else 0.0
            if p > 0:
                sizes.append({"place": place + 1, "bin": bin_idx, "p": p})

    return {"probabilities": probabilities, "top5": top5, "sizes": sizes}


def main() -> None:
    task = json.loads((INPUT_DIR / "task.json").read_text(encoding="utf-8"))
    marks = read_history(INPUT_DIR / "history.ndjson")
    forecast = build_forecast(task, marks)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / task.get("output", "forecast.json")
    out.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
