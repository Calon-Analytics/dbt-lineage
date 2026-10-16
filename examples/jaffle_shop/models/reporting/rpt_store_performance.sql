with orders as (
    select * from {{ ref('fct_orders') }}
),

customers as (
    select * from {{ ref('dim_customers') }}
),

locations as (
    select * from {{ ref('dim_locations') }}
)

select
    locations.location_name,
    locations.region,
    date_trunc('month', orders.ordered_at) as month,
    sum(orders.order_total) as revenue,
    sum(orders.order_total - orders.tax_paid - orders.order_cost) as gross_margin,
    avg(case when customers.customer_type = 'returning' then 1.0 else 0.0 end) as repeat_customer_share
from orders
join locations on orders.location_id = locations.location_id
join customers on orders.customer_id = customers.customer_id
group by 1, 2, 3
