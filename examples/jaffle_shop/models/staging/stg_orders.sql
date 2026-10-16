-- Orders placed in store and online. Test orders, made by staff when a store
-- opens, are removed here so they never reach revenue.

with source as (
    select * from {{ source('ecom', 'raw_orders') }}
),

renamed as (
    select
        id as order_id,
        customer as customer_id,
        store_id as location_id,
        lower(status) as status,
        cast(ordered_at as timestamp) as ordered_at,
        subtotal / 100.0 as subtotal,
        tax_paid / 100.0 as tax_paid,
        order_total / 100.0 as order_total
    from source
    where coalesce(is_test, false) = false
)

select * from renamed
