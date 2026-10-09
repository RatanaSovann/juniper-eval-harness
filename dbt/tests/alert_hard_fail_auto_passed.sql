-- ERROR: fails `dbt build` (and so the Dagster run) if the latest route run auto-passed a hand-labelled hard fail.
{{ config(severity='error') }}
select * from {{ ref('scorecard_alerts') }}
where is_latest and check_name = 'hard_fail_auto_passed' and fired
