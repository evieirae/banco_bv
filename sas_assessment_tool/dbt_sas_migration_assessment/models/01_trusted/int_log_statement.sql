with
  base_blocks as (
      select
          sha2(
              concat_ws(
                  '||'
                  , coalesce(cast(log_file as string), '')
                  , coalesce(cast(min_file_line_number as string), '')
              )
              , 256
          ) as block_id
          , log_file
          , log_date
          , user_id
          , min_file_line_number as file_line_number
          , project_name
          , task_name
          , flag_block
          , real_time
          , memory
          , os_memory
          , regexp_replace(
              regexp_replace(trim(code_log), '^\"|\"$', '')
              , '\\r\\n|\\r'
              , '\\n'
          ) as code_norm
      from {{ ref('int_log_grouped') }}
      where flag_block is not null
          and code_log is not null
          and trim(code_log) <> ''
          and project_name is not null
          and trim(project_name) <> ''
          and task_name is not null
          and trim(task_name) <> ''
  )

  , exploded as (
      select
          base_blocks.log_file
          , base_blocks.block_id
          , base_blocks.project_name
          , base_blocks.task_name
          , base_blocks.file_line_number
          , pe.pos + 1 as line_number_in_block
          , base_blocks.file_line_number + pe.pos as line_number_in_file
          , regexp_replace(pe.line, '\\r$', '') as content
      from base_blocks base_blocks
      lateral view posexplode(split(base_blocks.code_norm, '\\n')) pe as pos, line
      where pe.line is not null
          and trim(pe.line) <> ''
  )

  , logs_with_flags as (
      select
          *
          , case
              when regexp_like(
                  content
                  , '(?i)^\\s*(?:\\d+\\s+)?data\\s+[a-z_&][a-z0-9_.&]*(?:\\s*\\(|\\s+|;|$)'
              ) then 1
              else 0
          end as is_data_start
          , case
              when regexp_like(content, '(?i)^\\s*(?:\\d+\\s+)?proc\\s+sql\\b') then 1
              when regexp_like(content, '(?i)^\\s*(?:\\d+\\s+)?proc\\s+sort\\b') then 1
              when regexp_like(content, '(?i)^\\s*(?:\\d+\\s+)?proc\\s+means\\b') then 1
              when regexp_like(content, '(?i)^\\s*(?:\\d+\\s+)?proc\\s+export\\b') then 1
              when regexp_like(content, '(?i)^\\s*(?:\\d+\\s+)?proc\\s+[a-z0-9_]+') then 1
              when is_data_start = 1 then 1
              else 0
          end as is_start
          , case
              when regexp_like(content, '(?i)^\\s*(?:\\d+\\s+)?proc\\s+([a-z0-9_]+)')
                  then concat(
                      'PROC '
                      , upper(regexp_extract(content, '(?i)^\\s*(?:\\d+\\s+)?proc\\s+([a-z0-9_]+)', 1))
                  )
              when is_data_start = 1 then 'DATA'
              else null
          end as type_statement
          , case
              when regexp_like(content, '(?i)\\bquit\\b') then 1
              when regexp_like(content, '(?i)\\brun\\b') then 1
              else 0
          end as is_end
      from exploded
  )

  , logs_with_cumsum as (
      select
          *
          , sum(is_start) over (
              partition by log_file,block_id
              order by line_number_in_block
              rows between unbounded preceding and current row
          ) as cum_start
          , sum(is_end) over (
              partition by log_file,block_id
              order by line_number_in_block
              rows between unbounded preceding and 1 preceding
          ) as cum_end_prev
      from logs_with_flags
  )

  , logs_with_statement_id as (
      select
          *
          , case
              when cum_start > coalesce(cum_end_prev, 0)
                  and cum_start > 0
                  then cum_start
              else null
          end as statement_id
      from logs_with_cumsum
  )

  , lines_in_statements as (
      select
          *
      from logs_with_statement_id
      where statement_id is not null
  )

  , statements_pre as (
      select
          log_file
          , block_id
          , project_name
          , task_name
          , statement_id
          , min(line_number_in_file) as min_line_number
          , max(line_number_in_file) as max_line_number
          , max(type_statement) as type_statement
          , concat_ws(
              '\n'
              , transform(
                  sort_array(
                      collect_list(named_struct('ln', line_number_in_block, 'txt', content))
                  )
                  , x -> x.txt
              )
          ) as statement
      from lines_in_statements
      group by
          log_file
          , block_id
          , project_name
          , task_name
          , statement_id
  )

  , final as (
    select
        log_file
        , project_name
        , task_name
        , type_statement
        , statement
    from statements_pre
    where project_name is not null
        and project_name <> ''
        and task_name is not null
        and task_name <> ''
  )

select *
from final