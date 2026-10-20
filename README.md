# SafeRoute: weather-aware truck routing

A React + Django app that helps a truck driver pick the safest route. You enter an origin, a destination, a departure time and a load weight. It builds three route options and samples the forecast along each one *at the time the truck will be there*. It then scores each checkpoint against the risk and load rules and recommends a route, balancing weather risk against travel time.

**Live app:** _add your Render URL here_ · **Walkthrough:** _add Loom link here_

![stack](https://img.shields.io/badge/stack-React%2019%20·%20Leaflet%20·%20Django%205.2%20·%20DRF-17324d)

## Features

- **3 route options.** OSRM alternatives, topped up with via-point detours when OSRM returns fewer than three. Near-duplicates, U-turn spurs and routes over 1.6× the fastest time are rejected.
- **Checkpoints every 10 / 25 / 50 mi**, each with its own ETA. ETAs use truck speeds and can include hours-of-service breaks.
- **Risk at every checkpoint** from wind, rain and snow, with load rules applied. The UI shows which rule fired.
- **Recommendation with reasons**, e.g. *"Beats Route A on No Travel miles: 0 vs 75."*
- **Map:** the selected route is coloured by risk; other routes are dashed and clickable. Checkpoint popups, route chips and a truck marker that follows the time slider.
- **Corridor heatmap** (Risk / Wind / Rain / Snow) with a 0–48 h slider and playback. Slider positions between hours blend the neighbouring forecast hours.
- **Storm demo toggle.** When the real weather is calm, this overlays a synthetic storm on the fastest route so you can see the logic work. The UI labels the weather as simulated.

## How the logic works

All the logic lives in small, pure, tested modules under [`backend/planner/`](backend/planner).

### 1. Routes ([`services/routing.py`](backend/planner/services/routing.py))
- OSRM's `/route` with `alternatives=3`, full geometry and per-segment durations.
- If fewer than 3 distinct routes come back, the app tries via points offset perpendicular to the origin→destination line (±15%, ±30%, …). A candidate is kept only if:
  - under 75% of its length overlaps an existing route (1 mi radius);
  - it has no U-turn spur at the via point;
  - its drive time is at most 1.6× the fastest.
- **Truck speed:** the public OSRM server only has a car profile, so each segment is capped at 65 mph (`TRUCK_MAX_SPEED_MPH`).

### 2. Checkpoints and ETAs ([`planning.py`](backend/planner/planning.py), [`geo.py`](backend/planner/geo.py))
- Checkpoints are the origin, every *N* miles, and the destination. Positions and driving times are interpolated along the polyline.
- **Hours of service** (toggle, on by default): a 30-min break after 8 h of driving and a 10-h rest after 11 h. This is the simplified FMCSA rule; the 14-h on-duty window is not modelled. ETA = departure + driving time + breaks.
- Each checkpoint **represents the road halfway to its neighbours**. Its risk covers those miles, so "miles by level" add up to the route length exactly.

### 3. Weather ([`services/weather.py`](backend/planner/services/weather.py))
- Open-Meteo hourly `wind_speed_10m` (mph), `wind_gusts_10m`, `rain` and `snowfall` (in/hr).
- Points are snapped to 0.1° cells (finer than the models' grids), deduplicated and batched 100 locations per request. Results go in a shared file cache for 30 min.
- **Reading a value at an ETA:** wind is interpolated linearly between hours. Rain and snow are hourly totals, so the app reads the bucket for the hour the truck is driving through.
- Wind risk uses **sustained** speed, as the table specifies. Gusts are displayed but not scored.

### 4. Risk ([`risk.py`](backend/planner/risk.py))

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph) | <25 | 25–34 | 35–44 | 45–54 | ≥55 |
| Rain (in/hr) | <0.10 | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00 |
| Snow (in/hr) | <0.5 | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | >3.0 |

- Band edges belong to the **higher** band (25 mph is Moderate; 0.25 in/hr is High). The exception is the strict `>` in the top rain and snow bands: exactly 1.00 in/hr of rain is Severe.
- The overall level is the **worst** of the three conditions.
- Load rules only ever raise the wind level:
  - ≥55 mph → No Travel for any load;
  - 45–54 mph with >30,000 lb → No Travel;
  - 35–44 mph with >40,000 lb → Severe.

### 5. Recommendation ([`recommend.py`](backend/planner/recommend.py))
Routes are compared lexicographically, in this order:

1. **No Travel miles.** No Travel is strictly worse than Severe, so it is compared first.
2. Severe miles
3. High miles
4. Average risk, distance-weighted (Low = 0 … No Travel = 4)
5. Travel time, including breaks

Differences within a tolerance count as ties: 1 mi for mileage, 0.05 for average risk, 1 min for time. Without this, checkpoint-spacing noise of a fraction of a mile could outweigh an hour of driving.

If the best route still has No Travel miles, the app flags that **no route is safe** and advises delaying. If it has Severe miles, it suggests a later departure.

### 6. Heatmap ([`heatmap.py`](backend/planner/heatmap.py), [`frontend/src/heatmap.ts`](frontend/src/heatmap.ts))
- The server builds a roughly square grid over the routes, keeps only cells within ~40 mi of a route (≤450 cells), and returns 49 hourly frames. Risk is computed server-side with the same `assess()` used for checkpoints.
- The client paints one pixel per cell into a tiny canvas. Leaflet stretches it over the map and the browser's bilinear scaling smooths it. Moving the slider is one pass over a few hundred cells plus `putImageData`, about 3 ms per update measured in the dev build, so scrubbing and playback stay at 60 fps.
- Heavy React subtrees (route layers, results table) are memoised, so slider updates only touch the heatmap and the truck marker.

## Project layout

```
backend/                    Django 5.2 + DRF
  config/                   settings, urls (also serves the built SPA)
  planner/
    risk.py                 thresholds + load rules (pure)
    recommend.py            ranking + reasons (pure)
    geo.py                  polyline math, HOS clock, simplification
    planning.py             orchestrates routes → checkpoints → weather → risk
    heatmap.py              corridor grid + 49 hourly frames
    services/               OSRM, Open-Meteo, Photon clients; storm demo
    tests/                  64 tests (rules, ranking, ETAs, API validation)
frontend/                   Vite + React 19 + TypeScript + react-leaflet
  src/components/           MapView, PlanForm, PlaceInput, Results, TimeBar
  src/heatmap.ts            canvas heatmap renderer
scripts/e2e_check.py        black-box check against the brief
Dockerfile, render.yaml     single-service deploy
```

## API

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/geocode?q=` | text | `[{label, lat, lon}]` |
| POST | `/api/plan` | `{origin, destination, departure, load_lb, interval_mi, hos, simulate_storm}` | routes, checkpoints, recommendation, corridor |
| POST | `/api/heatmap` | `{corridor, departure, load_lb, storm?}` | grid + hourly wind/gust/rain/snow/risk |
| GET | `/api/health` | | `{ok: true}` |

## Running locally

```bash
# API (Python 3.12+)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py runserver 8000
```

```bash
# Web (Node 20+), proxies /api to :8000
cd frontend && npm install && npm run dev
```

Then open http://localhost:5173. No API keys are needed.

```bash
cd backend && .venv/bin/pytest          # 64 unit tests: rules, ranking, ETAs, HOS, API validation
python3 scripts/e2e_check.py http://localhost:8000   # black-box check of a running app against the brief
```

`scripts/e2e_check.py` reimplements the risk table and the ranking independently, then runs 4 real trips (all three intervals, loads from 29k to 80k lb, HOS on and off). It checks the following, ~257 checks in all:
- 3 distinct routes per trip;
- checkpoint spacing;
- ETAs, truck speed and HOS breaks;
- that each sampled checkpoint's weather equals Open-Meteo queried directly at that ETA;
- that every checkpoint's and heatmap cell's level matches the brief's rules;
- that miles by level add up to the route length;
- that the recommended route is not beaten on any criterion;
- the heatmap's 0–48 h frames;
- input validation.

## Deploying

The `Dockerfile` builds the React app, then serves it and the API from one gunicorn process (WhiteNoise serves the static assets, gzipped). On **Render**, choose New → Blueprint → this repo; `render.yaml` sets everything up. Any Docker host works the same way. Optional environment variables:

| Var | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | dev key | set in production |
| `DJANGO_ALLOWED_HOSTS` | `*` | comma-separated |
| `TRUCK_MAX_SPEED_MPH` | 65 | truck speed cap |
| `OSRM_URL` | public demo server | self-hosted OSRM for heavier use |
| `OPEN_METEO_API_KEY` | none | commercial Open-Meteo tier |

## Limitations and next steps

- **Routing is car-profile.** The public OSRM server has no truck restrictions (height, weight, hazmat). Swapping in OpenRouteService `driving-hgv` or HERE Truck behind `get_route_options()` would fix that without touching anything downstream.
- **Free-tier quotas.** Open-Meteo's free tier allows ~600 location-calls per minute (and 10k/day). One trip costs roughly 300–600 (checkpoints plus the ≤260-cell heatmap), so planning several trips within a minute can hit the cap. The app then waits for the next minute window, retries once, and shows a clear message if the limit is still hit. Results are cached for 30 min. Set `OPEN_METEO_API_KEY` for real traffic. The public OSRM and Photon servers are also demo-grade; geocoding retries and falls back to Nominatim.
- Times are shown in the browser's time zone.
- Forecast resolution is that of the underlying models (≈3–13 km), so very local effects such as mountain passes and lake-effect bands may be underestimated.

## Loom walkthrough outline (5–10 min)

1. **Problem and inputs (1 min).** Fill in Chicago → Denver, 42,000 lb, 25 mi checkpoints, HOS on.
2. **Routes and recommendation (2 min).** Three cards, miles-by-risk bars, the "why" bullets. Click a route on the map to select it.
3. **Checkpoints (1 min).** Click a table row; the map flies to it and the popup shows the weather, the ETA and any load rule.
4. **Storm demo (2 min).** Turn on *Simulate a storm* and replan. Route A gets No Travel miles from the 45–54 mph + >30k lb rule, and the recommendation switches. Drop the load to 25,000 lb, replan, and watch it become Severe instead.
5. **Heatmap (1.5 min).** Scrub and play the slider, switch Risk/Wind/Snow, watch the truck marker move with time, and note the arrival flag on the slider.
6. **Code tour (1.5 min).** `risk.py`, `recommend.py`, `planning.py`, the tests, and `heatmap.ts`.
