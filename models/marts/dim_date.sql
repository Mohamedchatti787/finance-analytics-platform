select
    d::date                                   as date_key,
    year(d)                                   as year,
    quarter(d)                                as quarter,
    month(d)                                  as month,
    strftime(d, '%b')                         as month_short,
    strftime(d, '%Y-%m')                      as year_month,
    date_trunc('month', d)::date              as period_start,
    last_day(d::date)                         as period_end,
    (d::date = last_day(d::date))             as is_month_end,
    year(d)                                   as fiscal_year,
    isodow(d)                                 as iso_weekday
from generate_series(date '2023-01-01', date '2025-12-31', interval 1 day) as t(d)
