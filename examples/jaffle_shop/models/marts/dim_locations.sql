with locations as (
    select * from {{ ref('stg_locations') }}
),

regions as (
    select * from {{ ref('store_regions') }}
)

select
    locations.location_id,
    locations.location_name,
    regions.region,
    locations.tax_rate,
    locations.opened_on
from locations
left join regions on locations.location_id = regions.store_id
