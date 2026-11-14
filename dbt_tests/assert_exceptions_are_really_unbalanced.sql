-- The quarantine must only contain journals that genuinely fail the check.
select journal_id from {{ ref('fct_journal_exceptions') }} where difference_lc = 0
