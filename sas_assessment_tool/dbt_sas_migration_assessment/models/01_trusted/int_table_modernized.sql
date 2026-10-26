with
  stg_table_modernized as (
    select
      table_name
      , table_name_work
      , table_name_origin
      , source_dataset
      , source_name_data
      , data_end_ingestion
    from {{ ref('stg_table_modernized') }}
  )

select
  table_name
  , table_name_work
  , table_name_origin
  , source_dataset
  , source_name_data
  , data_end_ingestion
from stg_table_modernized
