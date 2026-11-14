select
    account_id,
    account_name,
    account_type,
    statement,
    normal_balance,
    account_group,
    case account_type
        when 'REVENUE' then 'Revenue'
        when 'COGS'    then 'Cost of goods sold'
        when 'OPEX'    then 'Operating expenses'
        else 'Balance sheet'
    end as statement_line,
    (statement = 'PL') as is_pl
from {{ ref('stg_accounts') }}
