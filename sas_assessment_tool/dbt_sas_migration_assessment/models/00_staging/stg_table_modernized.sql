with
  base as (
    select
      cast(NmTabela as string) as table_name
      , cast(NmTabelaWork as string) as table_name_work
      , cast(NmTabelaOrigem as string) as table_name_origin
      , cast(DsOrigem as string) as source_dataset
      , cast(NmFonteDados as string) as source_name_data
      , cast(DtFimIngestao as timestamp) as data_end_ingestion
    from {{ source('bv_migration_sas', 'modernized_tables_list') }}
  )

  , stg_table_modernized as (
    select distinct 
      table_name
      , table_name_work
      , table_name_origin
      , source_dataset
      , source_name_data
      , data_end_ingestion
    from base
  )

select *
from stg_table_modernized
