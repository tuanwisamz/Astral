-- U3 (docs/usability-implementation-plan.md): camera-only reports carry who reported, where,
-- and the phone's GPS fix when the photo was taken.

alter table incidents
  add column reporter_name text,              -- never public (spec-api §4.3); cleared when the account is deleted
  add column address text,                    -- street address from Nominatim, as the reporter confirmed it
  add column landmark text,
  add column gps_lat double precision,        -- the phone's fix when the photo was taken
  add column gps_lng double precision,
  add column gps_accuracy_m double precision,
  add column captured_at timestamptz;

alter table report_analyses
  add column capture_token text unique,
  add column gps_lat double precision,
  add column gps_lng double precision,
  add column gps_accuracy_m double precision;

-- Single-use tokens issued when the in-app camera takes a photo; /reports/analyze spends one.
create table capture_tokens (
  token text primary key,
  clerk_id text not null,
  issued_at timestamptz not null default now(),
  used_at timestamptz
);
create index on capture_tokens (issued_at);
alter table capture_tokens enable row level security;  -- 0002: every table has RLS on
