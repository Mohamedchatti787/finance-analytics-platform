-- Days Sales Outstanding per entity-month: open AR / invoiced (gross) in the
-- trailing window x window days. The window is shortened for the first months
-- of history so early values are not artificially low.
-- EUR columns are included so group-level DSO can be computed as a weighted ratio
-- (summing local-currency amounts across entities would mix currencies).
with month_ends as (
    select period_end, period_start from {{ ref('dim_date') }} where is_month_end
),
ar as (
    select entity_id, period_end, sum(balance_lc) as ar_balance_lc
    from {{ ref('fct_ar_aging') }}
    group by 1, 2
),
sales as (
    select i.entity_id, m.period_end,
           sum(i.gross_lc) as invoiced_window_lc
    from {{ ref('stg_invoices') }} i
    join month_ends m
      on i.invoice_date between m.period_end - interval 89 day and m.period_end
    group by 1, 2
)
select
    s.entity_id,
    s.period_end,
    date_trunc('month', s.period_end)::date as period_start,
    coalesce(a.ar_balance_lc, 0) as ar_balance_lc,
    s.invoiced_window_lc,
    cast(coalesce(a.ar_balance_lc, 0) * fx.close_rate_to_eur as decimal(18, 2)) as ar_balance_eur,
    cast(s.invoiced_window_lc * fx.close_rate_to_eur as decimal(18, 2)) as invoiced_window_eur,
    least(90, date_diff('day', date '2023-01-01', s.period_end) + 1) as window_days,
    round(coalesce(a.ar_balance_lc, 0) / s.invoiced_window_lc
          * least(90, date_diff('day', date '2023-01-01', s.period_end) + 1), 1) as dso_days
from sales s
left join ar a using (entity_id, period_end)
join {{ ref('stg_entities') }} e using (entity_id)
join {{ ref('stg_fx_rates') }} fx
  on fx.currency = e.currency and fx.period_start = date_trunc('month', s.period_end)::date
