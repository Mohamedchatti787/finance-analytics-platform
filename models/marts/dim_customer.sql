select
    c.customer_id,
    c.entity_id,
    c.segment,
    c.payment_terms_days,
    c.country,
    min(i.invoice_date) as first_invoice_date,
    count(i.invoice_id) as lifetime_invoices,
    sum(i.gross_lc)     as lifetime_invoiced_lc
from {{ ref('stg_customers') }} c
left join {{ ref('stg_invoices') }} i using (customer_id)
group by c.customer_id, c.entity_id, c.segment, c.payment_terms_days, c.country
