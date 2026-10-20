-- Keep the database under Supabase's 500 MB free cap (plan §6). predictions holds one row per
-- segment × hazard × horizon (~550k), and top_factors was most of each row because jsonb repeats
-- the keys in every object. Store it as [feature, value, direction] triples instead, direction
-- 1 = pushes risk up, -1 = down. expand_factors() turns either form back into the documented
-- [{feature, value, direction}] shape, so the API contract doesn't change.

create or replace function expand_factors(f jsonb) returns jsonb
language sql immutable parallel safe
set search_path = pg_catalog
as $$
  select coalesce(jsonb_agg(
           case when jsonb_typeof(e) = 'array'
                then jsonb_build_object('feature', e ->> 0, 'value', e -> 1,
                                        'direction', case when (e ->> 2)::int >= 0 then 'up' else 'down' end)
                else e end
           order by ord), '[]'::jsonb)
  from jsonb_array_elements(f) with ordinality as t(e, ord)
$$;

-- One-off rewrite of the existing rows. Truncate and re-insert rather than update, because an
-- update leaves the old row versions behind and would roughly double the table on disk first.
create temp table predictions_compact on commit drop as
select segment_id, hazard_type, horizon_days, probability, risk_level,
       (select jsonb_agg(case when jsonb_typeof(e) = 'object'
                              then jsonb_build_array(e ->> 'feature', e -> 'value',
                                                     case when e ->> 'direction' = 'down' then -1 else 1 end)
                              else e end
                         order by ord)
        from jsonb_array_elements(top_factors) with ordinality as t(e, ord)) as top_factors,
       model_version, generated_at
from predictions;

truncate predictions;

insert into predictions (segment_id, hazard_type, horizon_days, probability, risk_level, top_factors,
                         model_version, generated_at)
select segment_id, hazard_type, horizon_days, probability, risk_level, top_factors, model_version, generated_at
from predictions_compact;
