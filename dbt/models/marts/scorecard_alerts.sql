-- ALERTS. One row per alert check per route run, so the history is kept; the two dbt tests in
-- tests/ only look at the LATEST route run (an old, already-reviewed failure shouldn't fail every
-- build forever).
--   error    hard_fail_auto_passed : a labelled hard fail (hand or AI reference label) was auto-passed. Fails `dbt build`,
--                                    which fails the Dagster run.
--   warning  review_load_jump      : review load rose more than 10 points since the previous route
--                                    run. Printed as a warning; the build still succeeds.
with runs as (
    select
        r.route_run_id,
        r.rules_version,
        r.routed_at,
        r.review_load,
        lag(r.review_load) over (order by r.routed_at) as previous_review_load,
        r.routed_at = max(r.routed_at) over ()         as is_latest,
        m.n_hard_fail,
        coalesce(m.n_missed, 0)                        as n_missed,
        m.missed_answers
    from {{ ref('review_load') }} r
    left join (
        select route_run_id, sum(n_hard_fail) as n_hard_fail, sum(n_missed) as n_missed,
               string_agg(concat(missed_answers, ' (', label_kind, ' label)'), '; ') as missed_answers
        from {{ ref('severe_miss_rate') }}
        group by 1
    ) m using (route_run_id)
)

select
    route_run_id, rules_version, routed_at, is_latest,
    'error' as level,
    'hard_fail_auto_passed' as check_name,
    n_missed > 0 as fired,
    if(n_missed > 0,
       format('%d labelled hard fail(s) auto-passed: %s', n_missed, missed_answers),
       format('0 of %d labelled hard fails auto-passed', coalesce(n_hard_fail, 0))) as message
from runs

union all

select
    route_run_id, rules_version, routed_at, is_latest,
    'warning',
    'review_load_jump',
    coalesce(review_load - previous_review_load > 0.10, false),
    if(previous_review_load is null,
       format('Review load %.1f%% (no previous run to compare)', review_load * 100),
       format('Review load %.1f%%, previous run %.1f%%', review_load * 100, previous_review_load * 100))
from runs
