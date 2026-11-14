-- Every journal that reaches the reporting layer must balance to the cent.
select journal_id, sum(debit_lc) - sum(credit_lc) as difference_lc
from {{ ref('fct_gl') }}
group by journal_id
having sum(debit_lc) <> sum(credit_lc)
