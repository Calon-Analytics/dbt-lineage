-- Each customer's first and latest order, how many orders they have placed and
-- what they have spent. Returned orders do not count.

with orders as (
    select * from {{ ref('stg_orders') }}
    where status != 'returned'
)

select
    customer_id,
    min(ordered_at) as first_ordered_at,
    max(ordered_at) as last_ordered_at,
    count(*) as order_count,
    sum(order_total) as lifetime_spend,
    count(*) > 1 as is_repeat_buyer
from orders
group by customer_id
