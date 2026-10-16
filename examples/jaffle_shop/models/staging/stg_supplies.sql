with source as (
    select * from {{ source('ecom', 'raw_supplies') }}
)

select
    {{ dbt.concat(['id', "'-'", 'sku']) }} as supply_uuid,
    id as supply_id,
    sku as product_id,
    name as supply_name,
    cost / 100.0 as supply_cost,
    perishable as is_perishable_supply
from source
