# Smart Analysis Road

Decision support for JKR: which road to fix first, and which agency owns it.

| Folder | What |
|---|---|
| `Client/astral/` | React + Vite + Tailwind (TypeScript) |
| `server/` | FastAPI API, SQL migrations, ingestion jobs (`app/ingest/`), ML (`app/ml/`), tests |
| `scripts/` | One-off loaders: OSM extract, road network, weather backfill, run a job by hand |
| `data/` | Approximate karst and ex-mining polygons (`geology.geojson`); `data/raw/` is gitignored |
| `docker-compose.yml` | Local PostGIS, used by the tests |
| `render.yaml`, `netlify.toml` | Deploy settings for the API (Render) and the client (Netlify) |

## Run locally

One-time setup:

```powershell
docker compose up -d                                   # PostGIS on localhost:54322
Copy-Item server\.env.example server\.env              # then set DEV_AUTH_ROLE=officer
Copy-Item Client\astral\.env.example Client\astral\.env.local
.venv\Scripts\python -m pip install -r server\requirements-dev.txt
cd server; ..\.venv\Scripts\python migrate.py; cd ..
cd Client\astral; npm install; cd ..\..
```

Then one command each (T0.1):

```powershell
cd server; ..\.venv\Scripts\python -m uvicorn app.main:app --reload   # http://localhost:8000/docs
cd Client\astral; npm run dev                                         # http://localhost:5173
```

If the API doesn't pick up a backend change, stop it and start it again: `--reload` has been
unreliable on Windows here.

## Accounts

The app has its own Sign in, Register and Forgot password pages, built on Clerk (`src/pages/auth/`).
Registering always creates a public reporter; an admin grants staff roles on the Admin page.

- **With Clerk:** set `VITE_CLERK_PUBLISHABLE_KEY` in `Client/astral/.env.local`, and
  `CLERK_JWKS_URL` and `CLERK_SECRET_KEY` in `server/.env`. Then remove `DEV_AUTH_ROLE`.
- **Without Clerk** (local development only): the account pages say sign-in isn't connected,
  every page is reachable, and the API acts as `DEV_AUTH_ROLE`. The bypass only works when
  `APP_ENV=development`.

## Load data

Run from the repo root, in this order, the first time a database is set up. Install
`scripts/requirements.txt` and `server/requirements-ml.txt` first.

```powershell
.venv\Scripts\python scripts\extract_osm.py          # Geofabrik extract → data/raw/*.parquet
.venv\Scripts\python scriptsuild_network.py        # states, districts, agencies, road segments
.venv\Scripts\python scriptsackfill_weather.py     # 12 months of rain and wind for the pilots
cd server
..\.venv\Scripts\python -m app.ml.synthetic           # demo incidents, labelled DEMO DATA
..\.venv\Scripts\python -m app.ml.models              # train, predict, refresh priority
```

After that the jobs keep it current. GitHub Actions runs them on a schedule
(`.github/workflows/cron-jobs.yml`, and `ml-nightly.yml` at 02:00 MYT). To run one by hand:
`.venv\Scripts\python scriptsun_job.py weather` (or warnings, forecast, flood, news, traffic,
priority, cleanup).

## Design

UI work follows `Client/astral/DESIGN.md` (the "Road paint" system). Read it before adding a screen.

## Checks

```powershell
cd server; ..\.venv\Scripts\python -m ruff check .; ..\.venv\Scripts\python -m pytest -q
cd Client\astral; npm run lint; npm run build
```

## Status

Every P0 and P1 feature is built and runs on Supabase: road ownership for the Peninsula, live
priority ranking, public reporting with photo checks, zones, road analysis, the prediction
model, the ingestion jobs, the AI summary and assistant, Bahasa Melayu and the onboarding tour.
Incidents are demo data, labelled DEMO DATA, until real reports arrive.

Still to do, and needing a person rather than code: Clerk dashboard settings, pushing to GitHub,
the Render and Netlify deploys, and the evidence and user-testing tasks. The list lives in
`docs/implementation-plan.md`.
