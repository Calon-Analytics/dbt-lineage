{% snapshot products_snapshot %}
{{ config(target_schema='snapshots', unique_key='sku', strategy='check', check_cols=['price', 'name']) }}

-- Keeps every price and name change to a product.
select * from {{ source('ecom', 'raw_products') }}

{% endsnapshot %}
