select
    items.order_item_id,
    items.order_id,
    items.product_id,
    orders.ordered_at,
    items.product_price,
    items.supply_cost,
    items.item_margin
from {{ ref('int_order_items_priced') }} as items
join {{ ref('stg_orders') }} as orders on items.order_id = orders.order_id
