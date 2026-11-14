select entity_id, entity_name, country, currency, reporting_currency
from {{ source('raw', 'entities') }}
