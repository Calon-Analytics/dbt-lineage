with source as (
    select * from {{ source('ecom', 'raw_items') }}
)

select
    id as order_item_id,
    order_id,
    sku as product_id
from source
