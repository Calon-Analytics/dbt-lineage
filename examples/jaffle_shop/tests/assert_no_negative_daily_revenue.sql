-- Daily revenue per store is never negative, even after returns.
select *
from {{ ref('rpt_daily_revenue') }}
where revenue < 0
