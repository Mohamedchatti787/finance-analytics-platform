-- Quarantined journals: debits <> credits. Finance would chase these before
-- close; they are excluded from fct_gl so they cannot distort any report.
select
    j.journal_id,
    j.entity_id,
    j.posting_date,
    j.source_system,
    j.reference,
    j.line_count,
    j.total_debit_lc,
    j.total_credit_lc,
    j.difference_lc,
    abs(j.difference_lc) as abs_difference_lc,
    cast(abs(j.difference_lc) * fx.avg_rate_to_eur as decimal(18, 2)) as abs_difference_eur
from {{ ref('int_journal_balance') }} j
join {{ ref('stg_entities') }} e using (entity_id)
join {{ ref('stg_fx_rates') }} fx
  on fx.currency = e.currency and fx.period_start = date_trunc('month', j.posting_date)::date
where not j.is_balanced
