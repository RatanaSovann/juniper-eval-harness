-- How well do the cheap Stage 3 text rules predict a hard fail in my hand labels?
-- One row per answer run. An answer "fails the rules" if any of its rules failed. Only answers that
-- have rules AND a hand label count. Rules check facts, not overall safety, so low recall is
-- expected; this shows how much the judges add on top of the rules.
with per_answer as (
    select answer_run_id, case_id, variant, logical_or(not passed) as rules_failed
    from {{ ref('stg_rule_hits') }}
    group by 1, 2, 3
),

labelled as (
    select p.answer_run_id, p.rules_failed, l.is_hard_fail
    from per_answer p
    join {{ ref('stg_labels') }} l
        on  l.answer_run_id = p.answer_run_id
        and l.case_id = p.case_id
        and l.variant = p.variant
        and l.label_kind = 'hand'
)

select
    answer_run_id,
    count(*)                                        as n_answers,
    countif(is_hard_fail)                           as n_hard_fail,
    countif(rules_failed and is_hard_fail)          as caught,          -- rules flagged a real hard fail
    countif(rules_failed and not is_hard_fail)      as false_alarms,
    countif(not rules_failed and is_hard_fail)      as missed,
    safe_divide(countif(rules_failed and is_hard_fail), countif(rules_failed)) as precision,
    safe_divide(countif(rules_failed and is_hard_fail), countif(is_hard_fail))  as recall
from labelled
group by 1
