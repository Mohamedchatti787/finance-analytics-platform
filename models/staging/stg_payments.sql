select
    payment_id,
    invoice_id,
    entity_id,
    payment_date::date as payment_date,
    cast(round(amount_cents / 100.0, 2) as decimal(18, 2)) as amount_lc
from {{ source('raw', 'payments') }}
