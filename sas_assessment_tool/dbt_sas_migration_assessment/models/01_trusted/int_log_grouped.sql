with
  relevant_logs as (
    select
      log_file
      , log_date
      , file_line_number as line_number
      , user_id
      , clean_text as content
      , connection_type
    from {{ ref('stg_log_process') }}
  )

  , blocks as (
    select
      log_file
      , log_date
      , line_number
      , user_id
      , content
      , case
          when regexp_like(content, '(?i)OPTIONS\\s+PAGENO=MIN;') then 1
          else 0
        end as is_block_start
      , case
          when regexp_like(content, '(?i)GOPTIONS\\s+NOACCESSIBLE;') then 1
          else 0
        end as is_block_end
      , connection_type
    from relevant_logs
  )

  , blocks_with_id as (
    select
      *
      , sum(is_block_start) over (
          partition by log_file
          order by line_number
          rows between unbounded preceding and current row
        ) as block_seq
      , (
          sum(is_block_start) over (
            partition by log_file
            order by line_number
            rows between unbounded preceding and current row
          )
          - coalesce(
              sum(is_block_end) over (
                partition by log_file
                order by line_number
                rows between unbounded preceding and 1 preceding
              ),
              0
            )
        ) as open_blocks_before
    from blocks
  )

  , blocks_with_flag as (
    select
      log_file
      , log_date
      , line_number
      , user_id
      , content
      , case
          when open_blocks_before > 0 then block_seq
          else null
        end as flag_block
      , connection_type
    from blocks_with_id
  )

  , extracted as (
    select
      log_file
      , log_date
      , line_number
      , user_id
      , content
      , connection_type
      , flag_block
      , replace(
          nullif(regexp_extract(content, '(?i)_CLIENTPROJECTNAME\\s*=\\s*([^;]*)', 1), ''),
          "'",
          ''
        ) as project_name_raw
      , replace(
          nullif(regexp_extract(content, '(?i)_CLIENTTASKLABEL\\s*=\\s*([^;]*)', 1), ''),
          "'",
          ''
        ) as task_name_raw
      , nullif(regexp_extract(content, '(?i)^\\s*real\\s+time\\s+([0-9]+(?:\\.[0-9]+)?)', 1), '') as real_time_raw
      , nullif(regexp_extract(content, '(?i)^\\s*memory\\s+([0-9]+(?:\\.[0-9]+)?[kK]?)', 1), '') as memory_raw
      , nullif(regexp_extract(content, '(?i)^\\s*OS\\s+Memory\\s+([0-9]+(?:\\.[0-9]+)?[kK]?)', 1), '') as os_memory_raw
    from blocks_with_flag
  )

  , propagated as (
    select
      log_file
      , log_date
      , line_number
      , user_id
      , content
      , connection_type
      , flag_block
      , case
          when flag_block is not null then last_value(project_name_raw, true) over (
            partition by log_file, flag_block
            order by line_number
            rows between unbounded preceding and current row
          )
          else null
        end as project_name
      , case
          when flag_block is not null then last_value(task_name_raw, true) over (
            partition by log_file, flag_block
            order by line_number
            rows between unbounded preceding and current row
          )
          else null
        end as task_name
      , real_time_raw as real_time
      , memory_raw as memory
      , os_memory_raw as os_memory
    from extracted
  )

  , base as (
    select
      log_file
      , log_date
      , line_number as file_line_number
      , user_id
      , project_name
      , task_name
      , content as code_log
      , connection_type
      , flag_block
      , real_time
      , memory
      , os_memory
    from propagated
    where flag_block is not null
  )

  , aggregated as (
    select
      log_file
      , min(log_date) as log_date
      , flag_block
      , max(user_id) as user_id
      , min(file_line_number) as min_file_line_number
      , max(file_line_number) as max_file_line_number
      , max(project_name) as project_name
      , max(task_name) as task_name
      , concat_ws(
          '\n',
          transform(
            array_sort(
              collect_list(named_struct('ln', file_line_number, 'txt', code_log))
            ),
            x -> x.txt
          )
        ) as code_log
      , concat_ws(
          ', ',
          collect_set(connection_type)
        ) as connection_type
      , sum(
          case
            when real_time is not null and real_time <> ''
              then cast(real_time as double)
            else 0.0
          end
        ) as real_time
      , sum(
          case
            when memory is not null and memory <> ''
              then cast(regexp_extract(memory, '([0-9]+(?:\\.[0-9]+)?)', 1) as double)
            else 0.0
          end
        ) as memory
      , sum(
          case
            when os_memory is not null and os_memory <> ''
              then cast(regexp_extract(os_memory, '([0-9]+(?:\\.[0-9]+)?)', 1) as double)
            else 0.0
          end
        ) as os_memory
    from base
    group by
      log_file
      , flag_block
  )

  , log_process_block as (
    select
      log_file
      , log_date
      , user_id
      , min_file_line_number
      , max_file_line_number
      , project_name
      , task_name
      , code_log
      , case
          when connection_type like '' then null
          else connection_type
        end as connection_type
      , flag_block
      , real_time
      , memory
      , os_memory
    from aggregated
  )

  , base_blocks as (
    select
      sha2(
        concat_ws(
          '||',
          coalesce(cast(log_file as string), ''),
          coalesce(cast(min_file_line_number as string), '')
        ),
        256
      ) as block_id
      , *
      , regexp_replace(code_log, '\\r\\n', '\\n') as code_norm
    from log_process_block
    where code_log is not null
      and trim(code_log) <> ''
  )

select
  base_blocks.* except (code_norm)
from base_blocks
