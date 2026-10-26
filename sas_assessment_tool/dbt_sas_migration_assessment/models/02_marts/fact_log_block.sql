with
  int_log_grouped as (
    select
      log_file as log_filename
      , regexp_replace(project_name, '^\\''|\\''$', '') as project_name_clean
      , log_date as execution_timestamp
      , to_date(log_date) as execution_date
      , user_id as execution_user
      , regexp_replace(task_name, '^\\''|\\''$', '') as task_name
      , flag_block
      , min_file_line_number as file_line_number
      , real_time
      , memory
      , os_memory
    from {{ ref('int_log_grouped') }}
    where project_name is not null
      and length(trim(project_name)) > 0
      and min_file_line_number is not null
  )

  , base as (
    select
      log_filename
      , project_name_clean as project_name
      , lower(trim(regexp_replace(project_name_clean, '\\s+', ' '))) as project_name_canonical
      , xxhash64(lower(trim(regexp_replace(project_name_clean, '\\s+', ' ')))) as project_id
      , execution_timestamp
      , execution_date
      , execution_user
      , task_name
      , flag_block
      , cast(file_line_number as bigint) as file_line_number
      , real_time
      , memory
      , os_memory
    from int_log_grouped
  )

  , agg as (
    select
      log_filename
      , project_id
      , project_name
      , min(execution_timestamp) as execution_timestamp
      , to_date(min(execution_timestamp)) as execution_date
      , max(execution_user) as execution_user
      , min(file_line_number) as file_line_number
      , count(distinct task_name) as tasks_executed_number
      , array_sort(collect_set(task_name)) as tasks_executed_list
      , count(*) as code_blocks_executed_number
      , cast(0 as int) as statements_executed_number
      , sum(coalesce(real_time, 0)) as execution_process_time
    from base
    group by
      log_filename
      , project_id
      , project_name
  )

  , keys as (
    select
      log_filename
      , project_id
      , project_name
      , execution_timestamp
      , execution_date
      , execution_user
      , tasks_executed_number
      , tasks_executed_list
      , code_blocks_executed_number
      , statements_executed_number
      , execution_process_time
      , xxhash64(
          log_filename,
          project_id,
          cast(execution_timestamp as string)
        ) as log_block_fk
    from agg
  )

select
  log_block_fk
  , log_filename
  , project_id
  , project_name
  , execution_timestamp
  , execution_date
  , execution_user
  , tasks_executed_number
  , tasks_executed_list
  , code_blocks_executed_number
  , statements_executed_number
  , execution_process_time
from keys
