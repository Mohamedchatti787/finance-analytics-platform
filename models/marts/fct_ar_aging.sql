-- Receivables aging snapshot at EVERY month-end (so the trend is available, not
-- just today's picture). Built from the AR subledger: an invoice is open at a
-- month-end if gross amount exceeds payments received on or before that date.
with month_ends as (
    select period_end, period_start from {{ ref('dim_date') }} where is_month_end
),
open_items as (
    select
        i.invoice_id, i.entity_id, i.customer_id, i.due_date,
        m.period_start, m.period_end,
        i.gross_lc - coalesce(sum(p.amount_lc) filter (where p.payment_date <= m.period_end), 0) as balance_lc
    from {{ ref('stg_invoices') }} i
    join month_ends m on m.period_end >= i.invoice_date
    left join {{ ref('stg_payments') }} p on p.invoice_id = i.invoice_id
    group by i.invoice_id, i.entity_id, i.customer_id, i.due_date, i.gross_lc, m.period_start, m.period_end
),
bucketed as (
    select *,
        date_diff('day', due_date, period_end) as days_past_due,
        case
            when date_diff('day', due_date, period_end) <= 0  then '0 Current'
            when date_diff('day', due_date, period_end) <= 30 then '1 1-30'
            when date_diff('day', due_date, period_end) <= 60 then '2 31-60'
            when date_diff('day', due_date, period_end) <= 90 then '3 61-90'
            else '4 90+'
        end as aging_bucket
    from open_items
    where balance_lc > 0.004
)
select
    b.entity_id,
    b.customer_id,
    b.period_start,
    b.period_end,
    b.aging_bucket,
    count(*)           as open_invoices,
    sum(b.balance_lc)  as balance_lc,
    cast(sum(b.balance_lc) * fx.close_rate_to_eur as decimal(18, 2)) as balance_eur
from bucketed b
join {{ ref('stg_entities') }} e using (entity_id)
join {{ ref('stg_fx_rates') }} fx
  on fx.currency = e.currency and fx.period_start = b.period_start
group by b.entity_id, b.customer_id, b.period_start, b.period_end, b.aging_bucket, fx.close_rate_to_eur
