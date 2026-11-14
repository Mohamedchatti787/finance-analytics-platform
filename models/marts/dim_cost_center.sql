select cost_center_id, cost_center_name
from {{ ref('stg_cost_centers') }}
