-- Staging model: parses the generic Bronze envelope's payload_json into
-- typed columns for the communications.emails dataset. One row per Bronze
-- event_id (Bronze is already deduplicated append-only, but dedupe here
-- too so this model is safe to point at any Bronze glob).
--
-- privacy_class stays a passthrough column rather than being dropped: any
-- consumer of this model (a Gold-level mart, a dashboard query) can filter
-- on it, but this model does not itself decide what's safe to expose.

with source as (
    select *
    from read_parquet(
        '{{ var("bronze_root") }}/domain=communications/dataset=emails/**/*.parquet'
    )
),

deduped as (
    select *
    from source
    qualify row_number() over (
        partition by event_id
        order by received_at desc
    ) = 1
)

select
    event_id,
    source as source_system,
    domain,
    dataset,
    schema_version,
    received_at,
    event_time,
    privacy_class,
    retention_class,
    ingest_date,
    json_extract_string(payload_json, '$.id') as message_id,
    json_extract_string(payload_json, '$.thread_id') as thread_id,
    json_extract_string(payload_json, '$.from_address') as from_address,
    cast(json_extract(payload_json, '$.is_read') as boolean) as is_read,
    cast(json_extract(payload_json, '$.is_important') as boolean) as is_important,
    cast(json_extract(payload_json, '$.has_attachment') as boolean) as has_attachment,
    json_array_length(json_extract(payload_json, '$.labels')) as label_count
from deduped
