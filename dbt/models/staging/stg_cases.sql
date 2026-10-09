-- One row per test case.
select
    case_id,
    category,
    medicine,
    risk_level,
    expected_behaviour,
    `partition`,
    severity_weight,
    assistant_scope
from {{ source('raw', 'cases') }}
