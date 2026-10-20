-- A tiny road network around Ipoh and in KL for the API tests. Coordinates are real places;
-- polygons are boxes, not true boundaries.
update states set geom = ST_Multi(ST_MakeEnvelope(100.9, 4.3, 101.3, 4.9, 4326)) where code = 'A';
update states set geom = ST_Multi(ST_MakeEnvelope(101.6, 3.0, 101.8, 3.3, 4326)) where code = 'KUL';

insert into agencies (id, type, name, state_code) values
  ('10000000-0000-4000-8000-000000000001', 'JKR_STATE', 'JKR Negeri Perak', 'A'),
  ('10000000-0000-4000-8000-000000000002', 'JKR_DISTRICT', 'JKR Daerah Kinta', 'A'),
  ('10000000-0000-4000-8000-000000000003', 'FED_MAINT_CONCESSIONAIRE', 'Belati Wangsa (M) Sdn Bhd', null),
  ('10000000-0000-4000-8000-000000000004', 'PBT', 'Majlis Bandaraya Ipoh', 'A'),
  ('10000000-0000-4000-8000-000000000005', 'PBT', 'Dewan Bandaraya Kuala Lumpur', 'KUL'),
  ('10000000-0000-4000-8000-000000000006', 'JMG', 'Jabatan Mineral dan Geosains Malaysia', null),
  ('10000000-0000-4000-8000-000000000007', 'LLM', 'Lembaga Lebuhraya Malaysia', null);

insert into districts (id, state_code, name, jkr_district_agency_id, geom) values
  ('20000000-0000-4000-8000-000000000001', 'A', 'Kinta', '10000000-0000-4000-8000-000000000002',
   ST_Multi(ST_MakeEnvelope(100.9, 4.3, 101.3, 4.9, 4326))),
  ('20000000-0000-4000-8000-000000000002', 'KUL', 'Kuala Lumpur', null,
   ST_Multi(ST_MakeEnvelope(101.6, 3.0, 101.8, 3.3, 4326)));

insert into road_segments (id, name, ref, road_class, federal_category, osm_highway, state_code, district_id,
                           owner_agency_id, maintainer_agency_id, jurisdiction_source, length_m, adt, heavy_pct,
                           adt_source, karst, ex_mining, tree_cover, criticality, cell_id, geom) values
  (1, 'Jalan Sultan Azlan Shah', '1', 'FEDERAL', 'MAIN', 'trunk', 'A', '20000000-0000-4000-8000-000000000001',
   '10000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000003', 'REF_TAG', 1000, 24800, 0.31,
   'RTVM 2024', true, false, 0.1, 0.8, '4.5_101.0',
   ST_GeomFromText('LINESTRING(101.0800 4.5900, 101.0900 4.6000)', 4326)),
  (2, 'Jalan Tambun', 'A13', 'STATE', null, 'primary', 'A', '20000000-0000-4000-8000-000000000001',
   '10000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000002', 'REF_TAG', 800, 8000, 0.12,
   'CLASS_DEFAULT', true, false, 0.4, 0.5, '4.6_101.1',
   ST_GeomFromText('LINESTRING(101.1200 4.6100, 101.1300 4.6150)', 4326)),
  (3, 'Jalan Bandar Baru', null, 'MUNICIPAL', null, 'residential', 'A', '20000000-0000-4000-8000-000000000001',
   '10000000-0000-4000-8000-000000000004', '10000000-0000-4000-8000-000000000004', 'RULE', 600, 3000, 0.05,
   'CLASS_DEFAULT', false, true, 0.6, 0.3, '4.5_101.1',
   ST_GeomFromText('LINESTRING(101.1000 4.5800, 101.1050 4.5850)', 4326)),
  (4, 'Jalan Ampang', null, 'MUNICIPAL', null, 'secondary', 'KUL', '20000000-0000-4000-8000-000000000002',
   '10000000-0000-4000-8000-000000000005', '10000000-0000-4000-8000-000000000005', 'RULE', 900, 3000, 0.05,
   'CLASS_DEFAULT', true, false, 0.7, 0.4, '3.1_101.7',
   ST_GeomFromText('LINESTRING(101.7000 3.1600, 101.7100 3.1610)', 4326));

refresh materialized view segment_components;
