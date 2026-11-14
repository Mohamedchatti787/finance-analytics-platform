-- operational + FX variance must equal the total EUR variance on every line.
select entity_id, period_start, account_id, cost_center_id,
       variance_total_eur, variance_operational_eur + variance_fx_eur as parts
from {{ ref('fct_budget_variance') }}
where abs(variance_total_eur - (variance_operational_eur + variance_fx_eur)) > 0.03
