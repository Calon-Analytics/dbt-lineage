-- Successful payments summed per order and split by method. Failed attempts
-- are left out.

with payments as (
    select * from {{ ref('stg_payments') }}
    where payment_status = 'success'
)

select
    order_id,
    sum(amount) as amount_paid,
    sum(case when payment_method = 'credit_card' then amount else 0 end) as credit_card_amount,
    sum(case when payment_method = 'coupon' then amount else 0 end) as coupon_amount,
    sum(case when payment_method = 'gift_card' then amount else 0 end) as gift_card_amount,
    max(paid_at) as last_paid_at
from payments
group by order_id
