-- The variance mart's actuals must agree with the trial balance activity.
with v as (
    select entity_id, period_start, account_id, sum(actual_lc) as actual_lc
    from {{ ref('fct_budget_variance') }}
    group by 1, 2, 3
),
t as (
    select entity_id, period_start, account_id, activity_natural_lc
    from {{ ref('fct_trial_balance') }} tb
    join {{ ref('dim_account') }} a using (account_id)
    where a.is_pl
)
select t.entity_id, t.period_start, t.account_id, t.activity_natural_lc, coalesce(v.actual_lc, 0) as variance_actual_lc
from t
left join v using (entity_id, period_start, account_id)
where abs(t.activity_natural_lc - coalesce(v.actual_lc, 0)) > 0.01
