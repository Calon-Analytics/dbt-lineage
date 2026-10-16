select
    date_trunc('month', first_ordered_at) as cohort_month,
    count(*) as customers,
    sum(lifetime_spend) / nullif(count(*), 0) as average_lifetime_spend,
    sum(case when customer_type = 'returning' then 1 else 0 end) * 1.0 / count(*) as repeat_rate
from {{ ref('dim_customers') }}
where first_ordered_at is not null
group by 1
