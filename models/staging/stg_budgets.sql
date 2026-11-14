select
    entity_id,
    period_start::date as period_start,
    account_id,
    cost_center_id,
    cast(round(budget_cents / 100.0, 2) as decimal(18, 2)) as budget_lc
from {{ source('raw', 'budgets') }}
