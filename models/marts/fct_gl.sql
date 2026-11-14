-- General ledger lines from BALANCED journals only, with local-currency and
-- EUR (average-rate) amounts in "natural sign": revenue/liability/equity lines
-- are credit-minus-debit, asset/expense lines are debit-minus-credit, so a
-- plain SUM() gives the number a finance person expects to see.
with lines as (
    select l.*
    from {{ ref('stg_gl_entries') }} l
    join {{ ref('int_journal_balance') }} j using (journal_id)
    where j.is_balanced
)
select
    l.gl_line_id,
    l.journal_id,
    l.line_no,
    l.entity_id,
    l.posting_date,
    l.period_start,
    l.period_end,
    l.account_id,
    l.cost_center_id,
    l.debit_lc,
    l.credit_lc,
    l.debit_lc - l.credit_lc as net_lc,
    case when a.normal_balance = 'C' then l.credit_lc - l.debit_lc
         else l.debit_lc - l.credit_lc end as natural_lc,
    e.currency,
    fx.avg_rate_to_eur,
    cast((case when a.normal_balance = 'C' then l.credit_lc - l.debit_lc
               else l.debit_lc - l.credit_lc end) * fx.avg_rate_to_eur as decimal(18, 4)) as natural_eur,
    l.source_system,
    l.reference,
    l.description
from lines l
join {{ ref('stg_accounts') }} a using (account_id)
join {{ ref('stg_entities') }} e using (entity_id)
join {{ ref('stg_fx_rates') }} fx
  on fx.currency = e.currency and fx.period_start = l.period_start
