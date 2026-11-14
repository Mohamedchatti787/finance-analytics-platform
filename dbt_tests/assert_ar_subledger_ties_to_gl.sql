-- Control-account check: AR subledger (open invoices) must equal GL account 1100
-- for every entity at every month-end.
with sub as (
    select entity_id, period_end, sum(balance_lc) as subledger_lc
    from {{ ref('fct_ar_aging') }}
    group by 1, 2
),
gl as (
    select entity_id, period_end, cumulative_natural_lc as gl_lc
    from {{ ref('fct_trial_balance') }}
    where account_id = 1100
)
select gl.entity_id, gl.period_end, gl.gl_lc, coalesce(sub.subledger_lc, 0) as subledger_lc
from gl
left join sub using (entity_id, period_end)
where abs(gl.gl_lc - coalesce(sub.subledger_lc, 0)) > 0.01
