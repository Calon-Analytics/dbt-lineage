select
    payment_id,
    order_id,
    payment_method,
    amount,
    paid_at,
    cast(paid_at as date) as paid_date
from {{ ref('stg_payments') }}
where payment_status = 'success'
