# ✈️ YC's Outer-Port Flight Deal Dashboard

A Streamlit dashboard for evaluating Asia outer-port flight deals to Spain
using the Jev (TypeSafe SystemOne) decision API.

## What it shows

- **Top picks** — pre-evaluated `prime_deal` options, sorted by routing_verdict
  → fatigue → risk → price
- **Risk vs fatigue scatter** — visualisation of every option with quadrant
  thresholds
- **Price comparison** — bar chart of total cost against TPE-direct baseline
- **Radar chart** — multi-criteria comparison up to 4 options
- **All routings** — text view of every waypoint
- **Filterable table** — every option with sortable columns
- **Markdown summary** — auto-generated report

## Pipeline

```
flight_candidates.json
        ↓
eval_flight_yc.py  (Jev /v1/systemone batched 3-question call)
        ↓
flight_results.json  (includes all_evaluated, all_survivors, top3, dropped)
        ↓
flight_dashboard.py  (Streamlit reads data/)
```

## Local run

```bash
pip install -r requirements.txt
streamlit run flight_dashboard.py
```

## Data

- `data/flight_candidates.json` — manually curated candidate itineraries
- `data/flight_results.json` — output from `eval_flight_yc.py`
- `data/flight_summary.md` — auto-generated Markdown summary

## Re-evaluate

After editing candidates:

```bash
python3 /Users/aib/.hermes/tools/eval_flight_yc.py \
  /Users/aib/.hermes/cache/scratch/flight-dashboard/data/flight_candidates.json \
  -o /Users/aib/.hermes/cache/scratch/flight-dashboard/data/flight_results.json
```

The dashboard will auto-reload (Streamlit watches the working dir).
