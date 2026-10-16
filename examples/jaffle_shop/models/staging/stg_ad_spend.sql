with source as (
    select * from {{ source('marketing', 'ad_spend') }}
)

select
    id as spend_id,
    lower(channel) as channel,
    campaign_name,
    cast(spend_date as date) as spend_date,
    spend_cents / 100.0 as spend
from source
