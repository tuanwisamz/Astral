-- Smart Analysis Road — initial schema.
-- architechture.md §6 with the additions from implementation-plan.md §6 folded in.
create extension if not exists postgis;
create extension if not exists pgcrypto;

create table states (
  code text primary key,              -- 'A','B',...,'KUL','PJY'
  name text not null,
  federal_zone text not null,         -- NORTH | CENTRAL_EAST | SOUTH | FT
  geom geometry(MultiPolygon,4326)
);
create index on states using gist (geom);

create table agencies (
  id uuid primary key default gen_random_uuid(),
  type text not null,  -- JKR_HQ | JKR_STATE | JKR_DISTRICT | PBT | FED_MAINT_CONCESSIONAIRE
                       -- | EXPRESSWAY_CONCESSIONAIRE | LLM | JMG
  name text not null,
  state_code text references states(code),
  parent_id uuid references agencies(id),
  contact jsonb,
  contract_valid_to date,
  last_verified date,
  geom geometry(MultiPolygon,4326)    -- PBT areas, for municipal owners (plan §6)
);
create index on agencies using gist (geom);

create table districts (
  id uuid primary key default gen_random_uuid(),
  state_code text references states(code),
  name text not null,
  jkr_district_agency_id uuid references agencies(id),
  geom geometry(MultiPolygon,4326)
);
create index on districts using gist (geom);

create table road_segments (
  id bigserial primary key,
  osm_way_ids bigint[],
  name text,
  ref text,
  road_class text not null,           -- FEDERAL | STATE | MUNICIPAL | EXPRESSWAY | UNKNOWN
  federal_category text,              -- MAIN | INSTITUTIONAL | FELDA_FELCRA | INDUSTRIAL
  osm_highway text, surface text, lanes int,
  state_code text references states(code),
  district_id uuid references districts(id),
  owner_agency_id uuid references agencies(id),
  maintainer_agency_id uuid references agencies(id),
  jurisdiction_source text,           -- REF_TAG | RULE | OVERRIDE
  length_m numeric,
  adt int, heavy_pct numeric, adt_source text,  -- RTVM | CLASS_DEFAULT
  karst boolean default false,
  ex_mining boolean default false,
  tree_cover numeric,                 -- 0..1 within 30 m buffer
  criticality numeric,                -- 0..1
  cell_id text,                       -- 0.1° weather cell of the midpoint (plan §6)
  geom geometry(LineString,4326) not null
);
create index on road_segments using gist (geom);
create index on road_segments (district_id);

create sequence incident_ref_seq;     -- SAR-2026-000123

create table incidents (
  id uuid primary key default gen_random_uuid(),
  ref_no text unique,
  hazard_type text not null,          -- POTHOLE | FALLEN_TREE | SINKHOLE
  severity smallint check (severity between 1 and 5),
  status text not null default 'REPORTED',
  source text not null,               -- PUBLIC | OFFICER | NEWS | SOCIAL | SYNTHETIC
  source_url text,
  confidence numeric,
  ai_result jsonb,
  description text,
  photo_path text,
  confirmations int default 1,
  duplicate_of uuid references incidents(id),
  segment_id bigint references road_segments(id),
  reported_by text,                   -- Clerk user id (never public)
  reported_at timestamptz default now(),
  verified_at timestamptz, assigned_at timestamptz, mitigated_at timestamptz, resolved_at timestamptz,
  assigned_agency_id uuid references agencies(id),
  sla_temp_due_at timestamptz,        -- temporary patch; met at MITIGATED
  sla_perm_due_at timestamptz,        -- permanent repair; met at RESOLVED
  is_synthetic boolean default false,
  geom geometry(Point,4326) not null
);
create index on incidents using gist (geom);
create index on incidents (status, hazard_type);
create index on incidents (segment_id, hazard_type, reported_at);

create table incident_events (
  id bigserial primary key,
  incident_id uuid references incidents(id),
  actor text, action text, from_status text, to_status text, note text,
  created_at timestamptz default now()
);
create index on incident_events (incident_id, created_at);

create table accidents (
  id uuid primary key default gen_random_uuid(),
  segment_id bigint references road_segments(id),
  occurred_on date, deaths int default 0, injuries int default 0,
  source text, source_url text, is_synthetic boolean default false,
  geom geometry(Point,4326)
);
create index on accidents (segment_id, occurred_on);

create table weather_daily (          -- 0.1° grid cells
  cell_id text, date date,
  rain_mm numeric, rain_max_hr numeric, gust_max_kmh numeric,
  is_forecast boolean,
  primary key (cell_id, date)
);

create table weather_warnings (
  id uuid primary key default gen_random_uuid(),
  source_id text unique, kind text, severity text, area_text text,
  valid_from timestamptz, valid_to timestamptz, raw jsonb,
  geom geometry(MultiPolygon,4326)
);

create table traffic_snapshots (
  segment_id bigint references road_segments(id), ts timestamptz,
  current_speed numeric, freeflow_speed numeric, confidence numeric,
  primary key (segment_id, ts)
);

create table news_items (
  id uuid primary key default gen_random_uuid(),
  url text unique, title text, source text, published_at timestamptz,
  extracted jsonb, status text,       -- NEW | IRRELEVANT | LINKED | NEEDS_REVIEW
  incident_id uuid references incidents(id),
  accident_id uuid references accidents(id)
);

create table predictions (
  segment_id bigint references road_segments(id),
  hazard_type text, horizon_days smallint,   -- 7 | 30
  probability numeric, risk_level text,      -- LOW | MEDIUM | HIGH | VERY_HIGH
  top_factors jsonb,                         -- [{feature, value, direction}], labels via i18n
  model_version text, generated_at timestamptz,
  primary key (segment_id, hazard_type, horizon_days)
);

create table priority_profiles (
  id uuid primary key default gen_random_uuid(),
  name text, weights jsonb, is_default boolean default false, created_by text
);

create table zones (                  -- STATE/DISTRICT zones are served from states/districts
  id uuid primary key default gen_random_uuid(),
  type text,                          -- KARST | FLOOD | CUSTOM
  name text, state_code text, district_id uuid,
  geom geometry(MultiPolygon,4326), created_by text
);
create index on zones using gist (geom);

create table app_users (
  clerk_id text primary key, role text,  -- public | officer | viewer | admin
  state_code text, district_id uuid, agency_id uuid,
  credibility numeric default 0.5
);

create table jurisdiction_overrides (
  segment_id bigint primary key references road_segments(id),
  owner_agency_id uuid, maintainer_agency_id uuid,
  reason text, created_by text, created_at timestamptz default now()
);

create table job_runs (
  id bigserial primary key, job text,
  started_at timestamptz, finished_at timestamptz,
  status text, items int, quota_used int, error text
);

create table report_analyses (        -- holds analysis_id between /reports/analyze and /reports
  id text primary key,                -- an_…
  clerk_id text not null,
  photo_path text not null,
  lat numeric, lng numeric,
  ai_result jsonb,
  incident_id uuid references incidents(id),  -- still null after 24 h → delete the photo
  created_at timestamptz default now()
);

create table usage_daily (            -- external quotas (clerk_id = '') and per-user limits (plan D5)
  day date,
  counter text,                       -- gemini, tomtom, nominatim, open_meteo | report, analyze, assistant
  clerk_id text default '',
  used int default 0,
  primary key (day, counter, clerk_id)
);

create table model_versions (         -- backs /predictions/model-card
  version text primary key, hazard_type text, algorithm text, trained_at timestamptz,
  training_rows int, synthetic_share numeric, metrics jsonb, features text[],
  limitations text, is_active boolean default false
);

create table geocode_cache (          -- Nominatim asks clients to cache results
  query text primary key, lat numeric, lng numeric, raw jsonb,
  created_at timestamptz default now()
);

create table ai_explanations (        -- P1: /ai/explain cache, per segment × model version × day
  segment_id bigint references road_segments(id), language text, model_version text, day date,
  body text, numbers_used text[],
  primary key (segment_id, language, model_version, day)
);

-- Slow-changing raw priority components (plan D1). Refreshed after the nightly ML run.
-- Percentiles, weights and the incident-driven components are computed per request.
create materialized view segment_components as
select
  s.id as segment_id,
  s.state_code,
  s.district_id,
  s.road_class,
  s.owner_agency_id,
  s.adt * (1 + coalesce(s.heavy_pct, 0)) as usage,
  s.adt_source = 'CLASS_DEFAULT' as usage_estimated,
  (select (coalesce(sum(a.deaths), 0) * 3 + coalesce(sum(a.injuries), 0))
          / greatest(s.length_m / 1000.0, 0.1)
     from accidents a
    where a.segment_id = s.id and a.occurred_on >= current_date - interval '3 years') as safety,
  (select max(p.probability) from predictions p
    where p.segment_id = s.id and p.horizon_days = 30) as predicted,
  s.criticality
from road_segments s;
create unique index on segment_components (segment_id);
create index on segment_components (state_code, district_id);

insert into states (code, name, federal_zone) values
  ('R', 'Perlis', 'NORTH'), ('K', 'Kedah', 'NORTH'), ('P', 'Pulau Pinang', 'NORTH'), ('A', 'Perak', 'NORTH'),
  ('B', 'Selangor', 'CENTRAL_EAST'), ('C', 'Pahang', 'CENTRAL_EAST'), ('T', 'Terengganu', 'CENTRAL_EAST'),
  ('D', 'Kelantan', 'CENTRAL_EAST'), ('J', 'Johor', 'SOUTH'), ('M', 'Melaka', 'SOUTH'),
  ('N', 'Negeri Sembilan', 'SOUTH'), ('KUL', 'WP Kuala Lumpur', 'FT'), ('PJY', 'WP Putrajaya', 'FT');

insert into priority_profiles (name, weights, is_default) values
  ('Default', '{"safety":0.25,"usage":0.2,"severity":0.2,"predicted":0.15,"recurrence":0.1,
               "criticality":0.05,"sla":0.05}', true);
