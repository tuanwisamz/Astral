-- Pilot area of each segment (plan D13): UTP (15 km around UTP Seri Iskandar, the focus area),
-- KINTA, KL, or null outside the pilots. The UTP area crosses the Perak Tengah–Kinta border, so
-- training, the synthetic generator and the traffic job select on this rather than district names.

alter table road_segments add column if not exists pilot text
  check (pilot in ('UTP', 'KINTA', 'KL'));
create index if not exists road_segments_pilot_idx on road_segments (pilot) where pilot is not null;
