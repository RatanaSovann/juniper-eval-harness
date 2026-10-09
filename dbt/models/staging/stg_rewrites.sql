-- One row per audit rewrite. kept = false means it lost safety content and was never judged.
select audit_run_id, answer_run_id, case_id, variant, style, rewriter_model, kept,
       array_to_string(problems, '; ') as problems, cost_aud
from {{ source('raw', 'rewrites') }}
