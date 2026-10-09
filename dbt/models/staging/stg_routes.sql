-- One row per routing decision. A randomly audited answer has route 'human_review' and
-- rule 'random_audit', but the rules had auto-passed it: was_auto_passed keeps that fact,
-- because misses are counted before the audit (an audit catch is luck, not policy).
select
    route_run_id,
    rules_version,
    answer_run_id,
    judge_runs,
    case_id,
    variant,
    risk_level,
    route,
    rule,
    random_audit,
    route = 'auto_pass' or random_audit as was_auto_passed,
    priority,
    `timestamp` as routed_at
from {{ source('raw', 'routes') }}
