with source as (
    select * from {{ source('ecom', 'raw_stores') }}
)

select
    id as location_id,
    name as location_name,
    tax_rate,
    cast(opened_at as date) as opened_on
from source
