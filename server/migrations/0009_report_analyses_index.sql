-- Reporters of merged duplicates can track them (FR-REP-04): /reports/mine and /reports/{ref}
-- look up a person's photo checks that were merged into an incident.
create index if not exists report_analyses_clerk_incident_idx
  on report_analyses (clerk_id, incident_id) where incident_id is not null;
