-- Orders credited to the marketing channel of the customer's last web session
-- in the 7 days before the order.

with sessions as (
    select * from {{ ref('stg_web_sessions') }}
),

orders as (
    select * from {{ ref('stg_orders') }}
),

joined as (
    select
        orders.order_id,
        orders.order_total,
        sessions.channel,
        row_number() over (partition by orders.order_id order by sessions.started_at desc) as recency_rank
    from orders
    join sessions on orders.customer_id = sessions.customer_id
        and sessions.started_at between orders.ordered_at - interval 7 day and orders.ordered_at
)

select order_id, order_total, channel
from joined
where recency_rank = 1
