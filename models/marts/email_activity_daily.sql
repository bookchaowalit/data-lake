-- Gold-level mart: daily email activity counts. Aggregate-only — no
-- message content or sender identity leaves stg_emails into this model,
-- so this table is safe to query for dashboards without touching
-- privacy_class-restricted fields directly.

select
    cast(received_at as date) as activity_date,
    count(*) as email_count,
    count(*) filter (where has_attachment) as with_attachment_count,
    count(*) filter (where is_important) as important_count,
    count(*) filter (where not is_read) as unread_count,
    count(distinct thread_id) as distinct_thread_count
from {{ ref('stg_emails') }}
group by 1
order by 1
