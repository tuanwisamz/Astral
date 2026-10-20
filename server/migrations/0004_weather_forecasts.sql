-- MET Malaysia's 7-day forecast (data.gov.my /weather/forecast), one row per location and day.
-- Used for the "thunderstorm forecast" feature and the dashboard. Matched to a district by name.
create table weather_forecasts (
  location_id text,
  date date,
  location_name text,
  district_id uuid references districts(id),
  morning text, afternoon text, night text, summary text, summary_when text,
  min_temp numeric, max_temp numeric,
  fetched_at timestamptz default now(),
  primary key (location_id, date)
);
create index on weather_forecasts (district_id, date);

-- 0002's rule: every new table gets row-level security (no policies = closed to the REST API).
alter table weather_forecasts enable row level security;
