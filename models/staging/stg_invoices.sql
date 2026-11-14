select
    invoice_id,
    entity_id,
    customer_id,
    invoice_date::date as invoice_date,
    due_date::date     as due_date,
    revenue_account_id,
    cast(round(net_cents   / 100.0, 2) as decimal(18, 2)) as net_lc,
    cast(round(vat_cents   / 100.0, 2) as decimal(18, 2)) as vat_lc,
    cast(round(gross_cents / 100.0, 2) as decimal(18, 2)) as gross_lc
from {{ source('raw', 'invoices') }}
