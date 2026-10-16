-- Customers as the shop records them: one row per customer.

with source as (
    select * from {{ source('ecom', 'raw_customers') }}
),

renamed as (
    select
        id as customer_id,
        name as customer_name,
        lower(trim(email)) as email,
        cast(created_at as timestamp) as created_at
    from source
)

select * from renamed
