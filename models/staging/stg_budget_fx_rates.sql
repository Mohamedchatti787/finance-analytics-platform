select fiscal_year, currency, budget_rate_to_eur::decimal(12, 6) as budget_rate_to_eur
from {{ source('raw', 'budget_fx_rates') }}
