select
    spend_id,
    channel,
    campaign_name,
    spend_date,
    spend
from {{ ref('stg_ad_spend') }}
where spend > 0
