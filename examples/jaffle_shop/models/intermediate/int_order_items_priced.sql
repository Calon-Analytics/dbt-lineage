-- Each order item with its product's price and the cost of the supplies that
-- go into it, so margin can be worked out per item.

with order_items as (
    select * from {{ ref('stg_order_items') }}
),

products as (
    select * from {{ ref('stg_products') }}
),

supply_costs as (
    select * from {{ ref('int_product_supply_costs') }}
)

select
    order_items.order_item_id,
    order_items.order_id,
    order_items.product_id,
    products.product_price,
    supply_costs.supply_cost,
    products.product_price - supply_costs.supply_cost as item_margin,
    products.is_food_item,
    products.is_drink_item
from order_items
left join products on order_items.product_id = products.product_id
left join supply_costs on order_items.product_id = supply_costs.product_id
