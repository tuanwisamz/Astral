-- 0002 turned on row-level security for every table, but materialized views can't have RLS,
-- so segment_components is still readable through Supabase's REST API. Revoke the API roles'
-- access. The roles only exist on Supabase, so this is skipped on plain Postgres (local, CI).
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on segment_components from anon, authenticated';
  end if;
end $$;
