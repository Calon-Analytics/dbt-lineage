-- An order is never paid more than its total. Rows returned are overpaid orders.
select order_id, order_total, amount_paid
from {{ ref('fct_orders') }}
where amount_paid > order_total + 0.01
