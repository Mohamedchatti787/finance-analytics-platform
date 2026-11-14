-- Surfaces SUSTAINED, statistically unusual budget variances instead of leaving
-- finance to eyeball a sorted list (where big, noisy revenue lines always win).
--
-- Method, per entity x account, at two horizons (3-month and 6-month rolling):
--   1. rolling variance % = (sum actual - sum budget) / sum budget, in local currency
--   2. compare it with how noisy that ACCOUNT normally is across the whole panel of
--      entities and months, using the median and the median absolute deviation (MAD):
--          robust_z = (variance% - median) / (1.4826 * MAD)
--      Median/MAD (not mean/stdev) so the anomalies we want to find do not inflate
--      the yardstick used to detect them.
--   3. alert if |robust_z| >= 3.5 AND the rolling EUR impact is material
--      (>= 0.5% of the entity's rolling budgeted revenue over the same window).
-- Two horizons because they catch different things: 3 months reacts quickly to a
-- sharp overspend; 6 months averages out noise so small, persistent shifts (a
-- supplier price rise) become visible. (A 3-month-only first version missed one.)
{% set horizons = [3, 6] %}
with monthly as (
    select entity_id, account_id, period_start, period_end,
           sum(actual_lc) as actual_lc, sum(budget_lc) as budget_lc,
           sum(budget_eur) as budget_eur, sum(favourable_variance_eur) as fav_eur
    from {{ ref('fct_budget_variance') }}
    group by 1, 2, 3, 4
),
scored as (
{% for h in horizons %}
    select {{ h }} as horizon_months, entity_id, account_id, period_start, period_end,
           (r_actual_lc - r_budget_lc) / nullif(r_budget_lc, 0) as r_var_pct,
           r_budget_eur, r_fav_eur
    from (
        select *,
            sum(actual_lc)  over w as r_actual_lc,
            sum(budget_lc)  over w as r_budget_lc,
            sum(budget_eur) over w as r_budget_eur,
            sum(fav_eur)    over w as r_fav_eur,
            count(*)        over w as n_months
        from monthly
        window w as (partition by entity_id, account_id order by period_end rows between {{ h - 1 }} preceding and current row)
    ) x
    where n_months = {{ h }}
    {% if not loop.last %}union all{% endif %}
{% endfor %}
),
centre as (
    select horizon_months, account_id, median(r_var_pct) as med from scored group by 1, 2
),
spread as (
    select s.horizon_months, s.account_id, median(abs(s.r_var_pct - c.med)) as mad
    from scored s join centre c using (horizon_months, account_id)
    group by 1, 2
),
entity_revenue as (
    select s.horizon_months, s.entity_id, s.period_end, sum(s.r_budget_eur) as revenue_budget_eur
    from scored s
    join {{ ref('dim_account') }} a using (account_id)
    where a.account_type = 'REVENUE'
    group by 1, 2, 3
)
select
    s.entity_id,
    s.account_id,
    s.horizon_months,
    s.period_start,
    s.period_end,
    cast(s.r_var_pct as decimal(12, 4)) as rolling_variance_pct,
    cast((s.r_var_pct - c.med) / nullif(1.4826 * sp.mad, 0) as decimal(12, 2)) as robust_z,
    cast(s.r_fav_eur as decimal(18, 2)) as rolling_favourable_variance_eur,
    (abs((s.r_var_pct - c.med) / nullif(1.4826 * sp.mad, 0)) >= 3.5
        and abs(s.r_fav_eur) >= 0.005 * er.revenue_budget_eur) as is_alert,
    case when s.r_fav_eur < 0 then 'Unfavourable' else 'Favourable' end as direction
from scored s
join centre c using (horizon_months, account_id)
join spread sp using (horizon_months, account_id)
join entity_revenue er using (horizon_months, entity_id, period_end)
