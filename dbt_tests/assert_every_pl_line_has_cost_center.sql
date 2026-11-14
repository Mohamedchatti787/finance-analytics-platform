-- P&L postings must carry a cost centre or departmental reporting breaks.
select g.gl_line_id
from {{ ref('fct_gl') }} g
join {{ ref('dim_account') }} a using (account_id)
where a.is_pl and g.cost_center_id is null
