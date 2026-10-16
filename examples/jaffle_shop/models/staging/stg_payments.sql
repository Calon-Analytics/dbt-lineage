-- Stripe payment attempts. Amounts arrive in cents; failed attempts are kept
-- here and removed downstream.

with source as (
    select * from {{ source('stripe', 'payments') }}
)

select
    id as payment_id,
    orderid as order_id,
    paymentmethod as payment_method,
    status as payment_status,
    amount / 100.0 as amount,
    cast(created as timestamp) as paid_at
from source
