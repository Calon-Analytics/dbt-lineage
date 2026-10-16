select
    orders.order_date,
    locations.location_name,
    locations.region,
    count(*) as order_count,
    sum(orders.order_total) as revenue,
    sum(orders.order_total - orders.tax_paid - orders.order_cost) as gross_margin,
    sum(orders.order_total) / nullif(count(*), 0) as average_order_value
from {{ ref('fct_orders') }} as orders
join {{ ref('dim_locations') }} as locations on orders.location_id = locations.location_id
where orders.status != 'returned'
group by 1, 2, 3
