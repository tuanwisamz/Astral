-- Turn on row-level security for every table in public, with no policies.
-- Supabase publishes the public schema through its REST API to anyone holding the anon key;
-- with RLS on and no policies, that API sees nothing. The FastAPI backend connects as the
-- table owner, which bypasses RLS, so it is unaffected (architechture.md: the frontend never
-- talks to Supabase directly). Tables owned by extensions (PostGIS's spatial_ref_sys) are skipped.
-- Later migrations that create tables must enable RLS on them too.
do $$
declare t record;
begin
  for t in
    select c.relname
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r'
      and not exists (select 1 from pg_depend d where d.objid = c.oid and d.deptype = 'e')
  loop
    execute format('alter table public.%I enable row level security', t.relname);
  end loop;
end $$;
