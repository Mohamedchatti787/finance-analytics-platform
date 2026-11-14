-- Payments applied to an invoice must never exceed the invoice amount.
select i.invoice_id, i.gross_lc, sum(p.amount_lc) as paid_lc
from {{ ref('stg_invoices') }} i
join {{ ref('stg_payments') }} p using (invoice_id)
group by i.invoice_id, i.gross_lc
having sum(p.amount_lc) > i.gross_lc
