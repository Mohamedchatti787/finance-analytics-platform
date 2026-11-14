-- Every entity needs an FX rate for every month, or EUR reporting silently drops rows.
select e.entity_id, p.period_start
from {{ ref('dim_entity') }} e
cross join (select period_start from {{ ref('dim_date') }} where is_month_end) p
left join {{ ref('stg_fx_rates') }} fx
  on fx.currency = e.currency and fx.period_start = p.period_start
where fx.avg_rate_to_eur is null or fx.close_rate_to_eur is null
