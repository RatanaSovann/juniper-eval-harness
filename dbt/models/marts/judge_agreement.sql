-- How far each judge agrees with my HAND labels, per metric, overall / for 'sure' labels only /
-- per category. Same rules as harness/agreement.py: repeat 1 only, needs_clinician labels left
-- out, and only answers where both gave a number ('unsure' and invalid are counted, not scored).
--
-- Cohen's kappa = (observed agreement - chance agreement) / (1 - chance agreement), where chance
-- comes from each rater's own habits: sum over scores k of P(label = k) x P(judge = k).
-- Weighted kappa charges a disagreement (gap)^2 / 4, so 2-vs-0 costs four times 2-vs-1. Its chance
-- term has a closed form under independence: E[(L - J)^2] = E[L^2] - 2 E[L] E[J] + E[J^2].
-- Either kappa is null when undefined (no pairs, or chance agreement is already perfect).
with pairs as (
    select
        jdg.judge_run_id, jdg.judge, jdg.model, c.category, lab.label_confidence, jdg.is_valid,
        m.metric, m.label_score, m.judge_score,
        -- l and j are the label and judge numbers, kept only when BOTH are numbers
        if(m.label_num is not null and m.judge_num is not null, m.label_num, null) as l,
        if(m.label_num is not null and m.judge_num is not null, m.judge_num, null) as j
    from {{ ref('stg_judgements') }} jdg
    join {{ ref('stg_labels') }} lab
        on  lab.answer_run_id = jdg.answer_run_id
        and lab.case_id = jdg.case_id
        and lab.variant = jdg.variant
        and lab.label_kind = 'hand'
    join {{ ref('stg_cases') }} c on c.case_id = jdg.case_id
    cross join unnest([
        struct('safety' as metric,     lab.safety as label_score,     lab.safety_num as label_num,     jdg.safety_score as judge_score,     jdg.safety_num as judge_num),
        struct('grounding' as metric,  lab.grounding as label_score,  lab.grounding_num as label_num,  jdg.grounding_score as judge_score,  jdg.grounding_num as judge_num),
        struct('scope' as metric,      lab.scope as label_score,      lab.scope_num as label_num,      jdg.scope_score as judge_score,      jdg.scope_num as judge_num),
        struct('escalation' as metric, lab.escalation as label_score, lab.escalation_num as label_num, jdg.escalation_score as judge_score, jdg.escalation_num as judge_num)
    ]) m
    where jdg.audit_style is null
      and jdg.`repeat` = 1
      and lab.label_confidence != 'needs_clinician'
),

grouped as (
    select 'ALL' as slice, * from pairs
    union all
    select 'sure only', * from pairs where label_confidence = 'sure'
    union all
    select category, * from pairs
),

stats as (
    select
        judge_run_id, judge, model, metric, slice,
        count(l)                                         as n,
        countif(judge_score = 'unsure')                  as n_judge_unsure,
        countif(label_score = 'unsure')                  as n_label_unsure,
        countif(not is_valid)                            as n_invalid,
        avg(if(l is null, null, cast(l = j as int64)))   as p_observed,
        safe_divide(
            countif(l = 0) * countif(j = 0) + countif(l = 1) * countif(j = 1) + countif(l = 2) * countif(j = 2),
            count(l) * count(l))                         as p_chance,
        avg(pow(l - j, 2)) / 4                           as w_observed,
        (avg(l * l) - 2 * avg(l) * avg(j) + avg(j * j)) / 4 as w_chance
    from grouped
    group by 1, 2, 3, 4, 5
)

select
    judge_run_id, judge, model, metric, slice,
    n, n_judge_unsure, n_label_unsure, n_invalid,
    p_observed as raw_agreement,
    if(p_chance < 1, (p_observed - p_chance) / (1 - p_chance), null) as kappa,
    if(w_chance > 0, 1 - w_observed / w_chance, null)                 as kappa_weighted
from stats
