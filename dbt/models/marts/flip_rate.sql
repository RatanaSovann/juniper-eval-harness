-- Experiment E2 (judge audit). Does a judge change its safety or escalation verdict when only the
-- wording of an answer changes? One row per audit run x judge x rewrite style.
-- A "flip" = the (safety, escalation) pair on the rewrite differs from the original (repeat 1).
-- The noise floor = the same comparison between repeat 1 and repeat 2 of the ORIGINAL text: a
-- style only matters if it flips clearly more often than the judge does on identical text.
-- Route flips (would the router decide differently?) need the routing rules, so they live in
-- `python -m harness.audit --report`, not here.
with audit as (
    select judge_run_id as audit_run_id, case_id, variant, judge, audit_style, `repeat`,
           if(is_valid, concat(safety_score, '|', escalation_score), null) as verdict
    from {{ ref('stg_judgements') }}
    where audit_style is not null
),

original as (
    select audit_run_id, case_id, variant, judge,
           max(if(`repeat` = 1, verdict, null)) as r1,
           max(if(`repeat` = 2, verdict, null)) as r2
    from audit
    where audit_style = 'original'
    group by 1, 2, 3, 4
),

noise as (
    select audit_run_id, judge,
           countif(r1 is not null and r2 is not null) as n_noise_compared,
           countif(r1 != r2)                          as n_noise_flipped
    from original
    group by 1, 2
),

rewrites as (
    select a.audit_run_id, a.judge, a.audit_style,
           countif(a.verdict is not null and o.r1 is not null) as n_compared,
           countif(a.verdict != o.r1)                          as n_flipped
    from audit a
    join original o using (audit_run_id, case_id, variant, judge)
    where a.audit_style != 'original' and a.`repeat` = 1
    group by 1, 2, 3
)

select
    r.audit_run_id, r.judge, r.audit_style,
    r.n_compared, r.n_flipped, safe_divide(r.n_flipped, r.n_compared) as flip_rate,
    n.n_noise_compared, n.n_noise_flipped, safe_divide(n.n_noise_flipped, n.n_noise_compared) as noise_flip_rate
from rewrites r
join noise n using (audit_run_id, judge)
