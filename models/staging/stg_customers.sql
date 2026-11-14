select customer_id, entity_id, segment, payment_terms_days, country
from {{ source('raw', 'customers') }}
