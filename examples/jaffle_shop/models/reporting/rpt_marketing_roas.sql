with spend as (
    select
        channel,
        date_trunc('month', spend_date) as month,
        sum(spend) as spend
    from {{ ref('fct_marketing_spend') }}
    group by 1, 2
),

revenue as (
    select
        attributed.channel,
        date_trunc('month', orders.ordered_at) as month,
        sum(attributed.order_total) as attributed_revenue
    from {{ ref('int_sessions_attributed') }} as attributed
    join {{ ref('fct_orders') }} as orders on attributed.order_id = orders.order_id
    group by 1, 2
)

select
    spend.channel,
    spend.month,
    spend.spend,
    coalesce(revenue.attributed_revenue, 0) as attributed_revenue,
    coalesce(revenue.attributed_revenue, 0) / nullif(spend.spend, 0) as roas
from spend
left join revenue on spend.channel = revenue.channel and spend.month = revenue.month
