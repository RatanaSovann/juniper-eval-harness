-- WARNING: printed by `dbt build`, does not fail it, if review load rose > 10 points since the previous route run.
{{ config(severity='warn') }}
select * from {{ ref('scorecard_alerts') }}
where is_latest and check_name = 'review_load_jump' and fired
