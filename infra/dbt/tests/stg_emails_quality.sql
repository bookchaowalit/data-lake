-- Every committed email row must retain the dataset identity and a payload id.

select event_id
from {{ ref('stg_emails') }}
where domain <> 'communications'
   or dataset <> 'emails'
   or schema_version <> '1'
   or message_id is null
