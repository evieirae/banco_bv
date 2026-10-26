with
  base_logs as (
      select
          log_file
          , project_name
          , task_name
          , min_file_line_number
          , max_file_line_number
      from {{ ref('int_log_grouped') }}
      where flag_block is not null
          and code_log is not null
          and trim(code_log) <> ''
          and project_name is not null
          and trim(project_name) <> ''
          and task_name is not null
          and trim(task_name) <> ''
  )

  , projects_file as (
      select
        log_file
        , project_name
        , task_name
        , min(min_file_line_number) as min_file_line_number
        , max(max_file_line_number) as max_file_line_number
      from base_logs
      group by 
        log_file
        , project_name
        , task_name
  )

  , conn as (
      select
        log_file
        , line_number
        , connection_type
        , alias
      from {{ ref('stg_connection') }}
  )

  , joined as (
      select 
        projects_file.log_file
        , projects_file.project_name
        , projects_file.task_name
        , projects_file.min_file_line_number
        , projects_file.max_file_line_number
        , conn.connection_type
        , conn.alias
      from projects_file
      left join conn 
        on conn.log_file = projects_file.log_file
        and conn.line_number 
            between min_file_line_number 
              and max_file_line_number
  )

  , final as (
      select distinct *
      from joined
  )

select * 
from final