select b.account_id
from {{ ref('stg_budgets') }} b
join {{ ref('dim_account') }} a using (account_id)
where not a.is_pl
