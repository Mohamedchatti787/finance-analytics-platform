-- Every raw ledger line ends up either in fct_gl or in quarantine - none vanish.
with raw as (select count(*) as n from {{ ref('stg_gl_entries') }}),
     good as (select count(*) as n from {{ ref('fct_gl') }}),
     bad as (select coalesce(sum(line_count), 0) as n from {{ ref('fct_journal_exceptions') }})
select raw.n as raw_lines, good.n as reported_lines, bad.n as quarantined_lines
from raw, good, bad
where raw.n <> good.n + bad.n
