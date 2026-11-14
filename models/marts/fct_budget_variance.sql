-- Budget vs actual for every P&L line (entity x month x account x cost centre),
-- in EUR, with the variance split into two parts that add up EXACTLY:
--   operational = (actual_lc - budget_lc) * budget_rate     "did we spend/earn more?"
--   fx          = actual_lc * (actual_rate - budget_rate)   "did currency moves change the EUR value?"
-- operational + fx = actual_eur - budget_eur  (asserted by a dbt test).
with actual as (
    select g.entity_id, g.period_start, g.account_id, g.cost_center_id, sum(g.natural_lc) as actual_lc
    from {{ ref('fct_gl') }} g
    join {{ ref('stg_accounts') }} a using (account_id)
    where a.statement = 'PL'
    group by 1, 2, 3, 4
),
budget as (
    select entity_id, period_start, account_id, cost_center_id, sum(budget_lc) as budget_lc
    from {{ ref('stg_budgets') }}
    group by 1, 2, 3, 4
),
joined as (
    select entity_id, period_start, account_id, cost_center_id,
           coalesce(a.actual_lc, 0) as actual_lc, coalesce(b.budget_lc, 0) as budget_lc
    from actual a
    full outer join budget b using (entity_id, period_start, account_id, cost_center_id)
)
select
    j.entity_id,
    j.period_start,
    last_day(j.period_start) as period_end,
    year(j.period_start)     as fiscal_year,
    j.account_id,
    j.cost_center_id,
    e.currency,
    j.actual_lc,
    j.budget_lc,
    fx.avg_rate_to_eur        as actual_rate,
    bfx.budget_rate_to_eur    as budget_rate,
    cast(j.actual_lc * fx.avg_rate_to_eur     as decimal(18, 2)) as actual_eur,
    cast(j.budget_lc * bfx.budget_rate_to_eur as decimal(18, 2)) as budget_eur,
    cast(j.actual_lc * fx.avg_rate_to_eur - j.budget_lc * bfx.budget_rate_to_eur as decimal(18, 2)) as variance_total_eur,
    cast((j.actual_lc - j.budget_lc) * bfx.budget_rate_to_eur as decimal(18, 2)) as variance_operational_eur,
    cast(j.actual_lc * (fx.avg_rate_to_eur - bfx.budget_rate_to_eur) as decimal(18, 2)) as variance_fx_eur,
    case when j.budget_lc <> 0
         then (j.actual_lc - j.budget_lc) / j.budget_lc end as variance_pct,
    -- positive = good for profit: revenue above budget, or costs below budget
    cast((j.actual_lc * fx.avg_rate_to_eur - j.budget_lc * bfx.budget_rate_to_eur)
         * case when a.account_type = 'REVENUE' then 1 else -1 end as decimal(18, 2)) as favourable_variance_eur,
    cast((j.actual_lc - j.budget_lc) * bfx.budget_rate_to_eur
         * case when a.account_type = 'REVENUE' then 1 else -1 end as decimal(18, 2)) as favourable_operational_eur,
    cast(j.actual_lc * (fx.avg_rate_to_eur - bfx.budget_rate_to_eur)
         * case when a.account_type = 'REVENUE' then 1 else -1 end as decimal(18, 2)) as favourable_fx_eur
from joined j
join {{ ref('stg_entities') }} e using (entity_id)
join {{ ref('stg_accounts') }} a using (account_id)
join {{ ref('stg_fx_rates') }} fx
  on fx.currency = e.currency and fx.period_start = j.period_start
join {{ ref('stg_budget_fx_rates') }} bfx
  on bfx.currency = e.currency and bfx.fiscal_year = year(j.period_start)
