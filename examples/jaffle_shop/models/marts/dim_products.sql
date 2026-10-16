with products as (
    select * from {{ ref('stg_products') }}
),

supply_costs as (
    select * from {{ ref('int_product_supply_costs') }}
)

select
    products.product_id,
    products.product_name,
    products.product_type,
    products.product_price,
    coalesce(supply_costs.supply_cost, 0) as unit_supply_cost,
    products.product_price - coalesce(supply_costs.supply_cost, 0) as unit_margin,
    coalesce(supply_costs.has_perishable_supply, false) as has_perishable_supply
from products
left join supply_costs on products.product_id = supply_costs.product_id
