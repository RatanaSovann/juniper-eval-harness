-- HEADLINE 2. How many answers does a person have to read? One row per route run.
-- review_load counts everything routed to a person, random audit included: that is the real
-- workload. The columns split it into "the rules asked" and "picked for the random audit".
select
    route_run_id,
    rules_version,
    answer_run_id,
    judge_runs,
    count(*)                                                as n_answers,
    countif(route = 'auto_pass')                            as n_auto_pass,
    countif(route = 'human_review' and not random_audit)    as n_review_by_rules,
    countif(random_audit)                                   as n_random_audit,
    countif(route = 'auto_fail')                            as n_auto_fail,
    countif(route = 'human_review' and risk_level = 'critical') as n_critical_reviewed,
    safe_divide(countif(route = 'human_review'), count(*))  as review_load,
    min(routed_at)                                          as routed_at
from {{ ref('stg_routes') }}
group by 1, 2, 3, 4
