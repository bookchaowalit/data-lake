-- Staging model: parses the generic Bronze envelope's payload_json into
-- typed columns for the communications.emails dataset. Only manifest-committed
-- Bronze parts are eligible; the bounded partition glob is an input locator,
-- not the commit protocol.
--
-- privacy_class stays a passthrough column rather than being dropped: any
-- consumer of this model (a Gold-level mart, a dashboard query) can filter
-- on it, but this model does not itself decide what's safe to expose.

with committed_manifests as (
    select distinct
        cast(bronze.key as varchar) as bronze_key
    from read_json_auto(
        '{{ var("bronze_manifest_root") }}/source=*/batch_id=*.json',
        union_by_name = true
    )
    where domain = 'communications'
      and dataset = 'emails'
      and cast(schema_version as varchar) = '1'
),

source as (
    select *
    from read_parquet(
        '{{ var("bronze_root") }}/domain=communications/dataset=emails/schema_version=*/ingest_date=*/source=*/part-*.parquet',
        filename = true
    ) as parts
    inner join committed_manifests as manifests
        on ends_with(
            replace(parts.filename, '\\', '/'),
            manifests.bronze_key
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
