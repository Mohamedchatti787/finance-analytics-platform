select
    bank_line_id,
    entity_id,
    bank_account,
    value_date::date as value_date,
    cast(round(amount_cents / 100.0, 2) as decimal(18, 2)) as amount_lc,
    bank_reference,
    description,
    currency
from {{ source('raw', 'bank_statements') }}
