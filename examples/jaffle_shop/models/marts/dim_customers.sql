with customers as (
    select * from {{ ref('stg_customers') }}
),

history as (
    select * from {{ ref('int_customer_order_history') }}
)

select
    customers.customer_id,
    customers.customer_name,
    customers.email,
    history.first_ordered_at,
    history.last_ordered_at,
    coalesce(history.order_count, 0) as order_count,
    coalesce(history.lifetime_spend, 0) as lifetime_spend,
    case when history.is_repeat_buyer then 'returning' else 'new' end as customer_type
from customers
left join history on customers.customer_id = history.customer_id
