with source as (
    select * from {{ source('marketing', 'web_sessions') }}
)

select
    session_id,
    customer_id,
    lower(utm_source) as channel,
    cast(started_at as timestamp) as started_at
from source
where customer_id is not null
