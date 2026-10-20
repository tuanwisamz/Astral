-- Indexes for the dashboard and map queries, found by timing them on the real network
-- (551k predictions, 92k segments): both scanned whole tables without these.
create index if not exists predictions_risk_idx on predictions (horizon_days, risk_level) where risk_level <> 'LOW';
create index if not exists incidents_reported_at_idx on incidents (reported_at desc);
create index if not exists incidents_reported_by_idx on incidents (reported_by, reported_at desc);
create index if not exists accidents_segment_idx on accidents (segment_id) where not is_synthetic;
create index if not exists weather_warnings_valid_idx on weather_warnings (valid_to);
create index if not exists road_segments_state_class_idx on road_segments (state_code, road_class);
analyze predictions;
analyze incidents;
