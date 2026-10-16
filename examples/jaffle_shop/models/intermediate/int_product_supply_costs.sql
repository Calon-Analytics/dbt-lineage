-- The total cost of the supplies one unit of each product uses.

select
    product_id,
    sum(supply_cost) as supply_cost,
    count(*) as supply_count,
    bool_or(is_perishable_supply) as has_perishable_supply
from {{ ref('stg_supplies') }}
group by product_id
