-- Debits equal credits for every entity and month across all accounts.
select entity_id, period_end, sum(activity_debit_lc) - sum(activity_credit_lc) as difference_lc
from {{ ref('fct_trial_balance') }}
group by 1, 2
having sum(activity_debit_lc) <> sum(activity_credit_lc)
