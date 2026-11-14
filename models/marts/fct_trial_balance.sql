-- Entity x month x account trial balance (dense grid, so balances carry
-- forward through months with no postings).
-- P&L accounts: activity translated at the month's AVERAGE rate.
-- Balance-sheet accounts: closing balance translated at the month-end rate.
-- NOTE: no cumulative-translation-adjustment (CTA) is booked, so the EUR balance
-- sheet is a presentation view and will not foot in EUR; it foots in local currency.
with periods as (
    select period_start, period_end from {{ ref('dim_date') }} where is_month_end
),
used_accounts as (
    select distinct account_id from {{ ref('fct_gl') }}
),
grid as (
    select e.entity_id, e.currency, p.period_start, p.period_end, a.account_id
    from {{ ref('stg_entities') }} e
    cross join periods p
    cross join used_accounts a
),
activity as (
    select entity_id, period_start, account_id,
           sum(debit_lc) as debit_lc, sum(credit_lc) as credit_lc, sum(natural_lc) as natural_lc
    from {{ ref('fct_gl') }}
    group by 1, 2, 3
),
joined as (
    select g.*, a.statement,
           coalesce(x.debit_lc, 0)   as activity_debit_lc,
           coalesce(x.credit_lc, 0)  as activity_credit_lc,
           coalesce(x.natural_lc, 0) as activity_natural_lc
    from grid g
    join {{ ref('stg_accounts') }} a using (account_id)
    left join activity x using (entity_id, period_start, account_id)
)
select
    j.entity_id,
    j.account_id,
    j.period_start,
    j.period_end,
    j.currency,
    j.activity_debit_lc,
    j.activity_credit_lc,
    j.activity_natural_lc,
    sum(j.activity_natural_lc) over (partition by j.entity_id, j.account_id order by j.period_end) as cumulative_natural_lc,
    sum(j.activity_natural_lc) over (partition by j.entity_id, j.account_id, year(j.period_end) order by j.period_end) as ytd_natural_lc,
    fx.avg_rate_to_eur,
    fx.close_rate_to_eur,
    cast(j.activity_natural_lc * fx.avg_rate_to_eur as decimal(18, 2)) as activity_natural_eur,
    case when j.statement = 'BS'
         then cast(sum(j.activity_natural_lc) over (partition by j.entity_id, j.account_id order by j.period_end)
                   * fx.close_rate_to_eur as decimal(18, 2)) end as closing_balance_eur
from joined j
join {{ ref('stg_fx_rates') }} fx
  on fx.currency = j.currency and fx.period_start = j.period_start
