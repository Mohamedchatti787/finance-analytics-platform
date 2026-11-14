select
    gl_line_id,
    journal_id,
    line_no,
    entity_id,
    posting_date::date                         as posting_date,
    date_trunc('month', posting_date)::date    as period_start,
    last_day(posting_date::date)               as period_end,
    account_id,
    cost_center_id,
    cast(round(debit_cents  / 100.0, 2) as decimal(18, 2)) as debit_lc,
    cast(round(credit_cents / 100.0, 2) as decimal(18, 2)) as credit_lc,
    source_system,
    reference,
    description
from {{ source('raw', 'gl_entries') }}
