with
  base_connections as (
    select
      log_file
      , line_number
      , complete_line
      , connection_type
      , alias
    from {{ source('bv_migration_sas', 'connections') }}
  )

select
  log_file
  , line_number
  , complete_line
  , connection_type
  , alias
from base_connections