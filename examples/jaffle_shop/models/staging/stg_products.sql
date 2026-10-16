-- Products on the menu, with the price in dollars and flags for food and drink.

with source as (
    select * from {{ source('ecom', 'raw_products') }}
)

select
    sku as product_id,
    name as product_name,
    type as product_type,
    description as product_description,
    price / 100.0 as product_price,
    type = 'jaffle' as is_food_item,
    type = 'beverage' as is_drink_item
from source
