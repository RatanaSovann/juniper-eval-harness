-- HEADLINE 1. Of the answers labelled a hard fail, what share did the router let through without a
-- person seeing it? One row per route run per label kind: 'hand' (my blind labels) and 'ai' (AI
-- reference labels, never human gold) are kept apart, never pooled.
-- "Let through" = auto-passed by the rules, counted BEFORE the random audit: an audit catch
-- is luck, not policy.
-- Range: 95% Wilson score interval. A bootstrap resamples the misses you saw, so with 0 misses
-- it reports 0%-0%, falsely claiming certainty; Wilson stays honest at 0 (0 of 4 -> 0% to 49%).
with labelled as (
    select
        r.route_run_id, r.rules_version, r.answer_run_id, r.judge_runs,
        r.case_id, r.variant, r.was_auto_passed, l.is_hard_fail, l.label_kind
    from {{ ref('stg_routes') }} r
    join {{ ref('stg_labels') }} l
        on  l.answer_run_id = r.answer_run_id
        and l.case_id = r.case_id
        and l.variant = r.variant
),

counts as (
    select
        route_run_id, rules_version, answer_run_id, judge_runs, label_kind,
        count(*)                                   as n_labelled,
        countif(is_hard_fail)                      as n_hard_fail,
        countif(is_hard_fail and was_auto_passed)  as n_missed,
        string_agg(if(is_hard_fail and was_auto_passed, concat(case_id, ' ', variant), null), ', ')
                                                   as missed_answers
    from labelled
    group by 1, 2, 3, 4, 5
),

wilson as (
    select
        *,
        safe_divide(n_missed, n_hard_fail) as p,
        1.96 * 1.96                        as z2
    from counts
)

select
    route_run_id, rules_version, answer_run_id, judge_runs, label_kind,
    n_labelled, n_hard_fail, n_missed, missed_answers,
    p as severe_miss_rate,
    greatest(0, (p + z2 / (2 * n_hard_fail) - 1.96 * sqrt(p * (1 - p) / n_hard_fail + z2 / (4 * n_hard_fail * n_hard_fail)))
                / (1 + z2 / n_hard_fail)) as miss_rate_low_95,
    least(1, (p + z2 / (2 * n_hard_fail) + 1.96 * sqrt(p * (1 - p) / n_hard_fail + z2 / (4 * n_hard_fail * n_hard_fail)))
             / (1 + z2 / n_hard_fail)) as miss_rate_high_95
from wilson
