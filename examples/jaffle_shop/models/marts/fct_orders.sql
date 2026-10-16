{{ config(materialized='incremental', unique_key='order_id') }}

-- One row per order: totals from the shop, what was paid from Stripe, and the
-- supply cost of the items. Incremental on ordered_at.

with orders as (
    select * from {{ ref('stg_orders') }}
    {% if is_incremental() %}
    where ordered_at > (select max(ordered_at) from {{ this }})
    {% endif %}
),

payments as (
    select * from {{ ref('int_order_payments') }}
),

items as (
    select
        order_id,
        count(*) as item_count,
        sum(supply_cost) as order_cost,
        sum(case when is_food_item then 1 else 0 end) as food_item_count,
        sum(case when is_drink_item then 1 else 0 end) as drink_item_count
    from {{ ref('int_order_items_priced') }}
    group by order_id
)

select
    orders.order_id,
    orders.customer_id,
    orders.location_id,
    orders.status,
    orders.ordered_at,
    cast(orders.ordered_at as date) as order_date,
    orders.subtotal,
    orders.tax_paid,
    orders.order_total,
    coalesce(payments.amount_paid, 0) as amount_paid,
    orders.order_total - coalesce(payments.amount_paid, 0) as amount_outstanding,
    items.item_count,
    items.order_cost,
    items.food_item_count > 0 as is_food_order,
    items.drink_item_count > 0 as is_drink_order
from orders
left join payments on orders.order_id = payments.order_id
left join items on orders.order_id = items.order_id
