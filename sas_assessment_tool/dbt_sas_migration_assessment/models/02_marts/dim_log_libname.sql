with 
  source_libnames as (
      select * from {{ ref('int_log_libname') }}
  )

  , filtered_and_deduplicated as (
    select distinct
        project_name
        , task_name
        , libname_alias
        , libname_type
        , libname_path
        , connection_engine
        , connection_options
        , path_options
    from source_libnames
    where 
        libname_type not in ('CLEAR', 'LIST')
        and upper(libname_alias) not in ('WORK', 'SASUSER', 'SASHELP')
  )

select *
from filtered_and_deduplicated