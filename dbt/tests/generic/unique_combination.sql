-- Fails (returns rows) if any combination of the given columns appears more than once.
{% test unique_combination(model, columns) %}
select {% for c in columns %}{{ adapter.quote(c) }}{{ ", " if not loop.last }}{% endfor %}, count(*) as n
from {{ model }}
group by {% for c in columns %}{{ adapter.quote(c) }}{{ ", " if not loop.last }}{% endfor %}
having count(*) > 1
{% endtest %}
