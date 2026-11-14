select entity_id, entity_name, country, currency, reporting_currency
from {{ ref('stg_entities') }}
