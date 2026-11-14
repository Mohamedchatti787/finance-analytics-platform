select cost_center_id, cost_center_name
from {{ source('raw', 'cost_centers') }}
