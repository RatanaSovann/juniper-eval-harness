-- One row per judge verdict (one judge, one answer, one repeat).
-- Audit verdicts carry a variant like 'grounded~shorter'; it is split into the bot variant
-- and the audit style, so normal verdicts have audit_style = null.
select
    judge_run_id,
    answer_run_id,
    case_id,
    split(variant, '~')[offset(0)]      as variant,
    split(variant, '~')[safe_offset(1)] as audit_style,
    judge,
    model,
    prompt_version,
    `repeat`,
    status = 'valid'                    as is_valid,
    safety_score, grounding_score, scope_score, escalation_score,
    safe_cast(safety_score as int64)     as safety_num,
    safe_cast(grounding_score as int64)  as grounding_num,
    safe_cast(scope_score as int64)      as scope_num,
    safe_cast(escalation_score as int64) as escalation_num,
    cost_aud,
    `timestamp` as judged_at
from {{ source('raw', 'judgements') }}
