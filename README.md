# Pump.fun Top-5 Forecast

Deterministic Python 3.13 forecaster for the make.fun `pumpfun-top5-forecast-01` competition. It estimates a momentum-adjusted ranking from the observed market-cap chart and emits probabilities for place and market-cap bins.

## Run

The competition sandbox runs the root `main.py` with only the Python standard library. It reads `/input/task.json` and `/input/history.ndjson` and writes `/output/forecast.json`.

For local replay:

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The bundled `input/` directory is the public development rehearsal dataset from the official competition kit; `input/NOTICE.txt` describes its provenance. A passing rehearsal run does not establish that this entry beats either house forecast. The official scoring window is separate.

## Forecast outline

- Collect valid successful marks and rank the latest observed chart.
- Estimate per-coin short-term log-market-cap velocity from available marks, cap and shrink the trend, and add a small persistence adjustment.
- Build per-place probabilities across the observed chart while reserving some probability mass for coins not named in the chart.
- Mix broad log-cap distributions for each place and write probabilities for every provided size bin.
- Use stable sorting and no randomness, so identical input yields identical output.

## Competition constraints

No network access, third-party packages, installed dependencies, or nondeterministic operations are used by `main.py`.
