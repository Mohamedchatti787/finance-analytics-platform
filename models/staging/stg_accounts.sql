select account_id, account_name, account_type, statement, normal_balance, account_group
from {{ source('raw', 'accounts') }}
