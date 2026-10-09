-- One row per rule per answer: the latest check only (a rule can be re-checked later).
select run_id as answer_run_id, case_id, variant, rule, passed, matched_text, checked_at
from {{ source('raw', 'rule_hits') }}
qualify row_number() over (partition by run_id, case_id, variant, rule order by checked_at desc) = 1
