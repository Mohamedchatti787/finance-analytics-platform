select
    period_start::date            as period_start,
    last_day(period_start::date)  as period_end,
    currency,
    avg_rate_to_eur::decimal(12, 6)   as avg_rate_to_eur,
    close_rate_to_eur::decimal(12, 6) as close_rate_to_eur
from {{ source('raw', 'fx_rates') }}
