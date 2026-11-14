-- One row per journal with its debit/credit totals. A journal that does not
-- balance is a control failure: it is quarantined (see fct_journal_exceptions)
-- and kept OUT of every financial report (fct_gl and everything built on it).
select
    journal_id,
    min(entity_id)     as entity_id,
    min(posting_date)  as posting_date,
    min(source_system) as source_system,
    min(reference)     as reference,
    count(*)           as line_count,
    sum(debit_lc)      as total_debit_lc,
    sum(credit_lc)     as total_credit_lc,
    sum(debit_lc) - sum(credit_lc) as difference_lc,
    (sum(debit_lc) = sum(credit_lc)) as is_balanced
from {{ ref('stg_gl_entries') }}
group by journal_id
