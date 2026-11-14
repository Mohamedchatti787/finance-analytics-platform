-- Independent re-computation of the 31-Dec-2025 aging by entity and bucket,
-- using a different query shape (pre-aggregated payments, no month-end spine)
-- than fct_ar_aging. If the model's bucket logic or open-item logic is wrong,
-- these two will disagree.
with paid as (
    select invoice_id, sum(amount_lc) as paid_lc
    from {{ ref('stg_payments') }}
    where payment_date <= date '2025-12-31'
    group by 1
),
direct as (
    select
        i.entity_id,
        case
            when date_diff('day', i.due_date, date '2025-12-31') <= 0  then '0 Current'
            when date_diff('day', i.due_date, date '2025-12-31') <= 30 then '1 1-30'
            when date_diff('day', i.due_date, date '2025-12-31') <= 60 then '2 31-60'
            when date_diff('day', i.due_date, date '2025-12-31') <= 90 then '3 61-90'
            else '4 90+'
        end as aging_bucket,
        sum(i.gross_lc - coalesce(p.paid_lc, 0)) as balance_lc
    from {{ ref('stg_invoices') }} i
    left join paid p using (invoice_id)
    where i.invoice_date <= date '2025-12-31'
      and i.gross_lc - coalesce(p.paid_lc, 0) > 0.004
    group by 1, 2
),
model as (
    select entity_id, aging_bucket, sum(balance_lc) as balance_lc
    from {{ ref('fct_ar_aging') }}
    where period_end = date '2025-12-31'
    group by 1, 2
)
select coalesce(d.entity_id, m.entity_id) as entity_id,
       coalesce(d.aging_bucket, m.aging_bucket) as aging_bucket,
       d.balance_lc as direct_lc, m.balance_lc as model_lc
from direct d
full outer join model m using (entity_id, aging_bucket)
where abs(coalesce(d.balance_lc, 0) - coalesce(m.balance_lc, 0)) > 0.01
