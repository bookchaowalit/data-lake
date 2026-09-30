-- Aggregate counts must be internally consistent.

select activity_date
from {{ ref('email_activity_daily') }}
where email_count < 1
   or with_attachment_count > email_count
   or important_count > email_count
   or unread_count > email_count
   or distinct_thread_count > email_count
