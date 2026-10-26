with
  int_log_grouped as (
    select
      regexp_replace(project_name, '^\\''|\\''$', '') as project_name
      , regexp_replace(task_name, '^\\''|\\''$', '') as task_name
      , log_file
      , flag_block
      , regexp_replace(code_log, '\\r', '') as block_code_log
    from {{ ref('int_log_grouped') }}
    where flag_block is not null
      and code_log is not null
      and trim(code_log) <> ''
      and project_name is not null
      and task_name is not null
      and length(trim(regexp_replace(project_name, '^\\''|\\''$', ''))) > 0
      and length(trim(regexp_replace(task_name, '^\\''|\\''$', ''))) > 0
  )

  , let_block_lines as (
    select
      int_log_grouped.project_name
      , int_log_grouped.task_name
      , int_log_grouped.log_file
      , int_log_grouped.flag_block
      , pos + 1 as line_number_in_block
      , trim(raw_line) as raw_line
    from int_log_grouped 
    lateral view posexplode(split(int_log_grouped.block_code_log, '\\n')) x as pos, raw_line
    where raw_line is not null
      and trim(raw_line) <> ''
  )

  , let_code as (
    select
      project_name
      , task_name
      , log_file
      , flag_block
      , line_number_in_block
      , trim(regexp_replace(raw_line, '^\\s*(\\d+\\s+)?!?\\s*', '')) as code_line
    from let_block_lines
  )

  , let_flags as (
    select
      *
      , case
          when regexp_like(code_line, '(?i)^%\\s*let\\s+[a-z_][a-z0-9_]*\\s*=') then 1
          else 0
        end as is_let_start
      , case
          when regexp_like(code_line, ';\\s*$') then 1
          else 0
        end as is_let_end
    from let_code
  )

  , let_ids as (
    select
      *
      , sum(is_let_start) over (
          partition by project_name, task_name, log_file, flag_block
          order by line_number_in_block
          rows between unbounded preceding and current row
        ) as let_id
    from let_flags
  )

  , let_bounds as (
    select
      *
      , min(case when is_let_start = 1 then line_number_in_block end) over (
          partition by project_name, task_name, log_file, flag_block, let_id
        ) as start_line
      , min(case when is_let_end = 1 then line_number_in_block end) over (
          partition by project_name, task_name, log_file, flag_block, let_id
        ) as end_line
    from let_ids
  )

  , let_lines as (
    select
      *
    from let_bounds
    where let_id > 0
      and start_line is not null
      and end_line is not null
      and line_number_in_block between start_line and end_line
  )

  , let_agg as (
    select
      project_name
      , task_name
      , log_file
      , flag_block
      , let_id
      , max(upper(regexp_extract(code_line, '(?i)^%\\s*let\\s+([a-z_][a-z0-9_]*)\\s*=', 1))) as var_name
      , concat_ws(
          ' ',
          transform(
            sort_array(collect_list(named_struct('ln', line_number_in_block, 'txt', code_line))),
            x -> x.txt
          )
        ) as let_stmt
    from let_lines
    group by
      project_name
      , task_name
      , log_file
      , flag_block
      , let_id
  )

  , let_var_values as (
    select
      project_name
      , task_name
      , var_name
      , trim(regexp_extract(let_stmt, '(?i)=\\s*(.*?);\\s*$', 1)) as var_value_raw
      , let_stmt
    from let_agg
    where var_name is not null
      and var_name <> ''
  )

  , let_final as (
    select
      project_name
      , task_name
      , 'LET' as macro_type
      , var_name
      , case
          when regexp_like(var_value_raw, '^[\\''"].*[\\''"]$')
            then regexp_extract(var_value_raw, '^[\\''"](.*)[\\''"]$', 1)
          else var_value_raw
        end as var_value
      , let_stmt as var_stmt
    from let_var_values
    where project_name is not null
      and task_name is not null
      and length(trim(project_name)) > 0
      and length(trim(task_name)) > 0
  )

  , lib_base as (
    select
      regexp_replace(project_name, '^\\''|\\''$', '') as project_name
      , regexp_replace(task_name, '^\\''|\\''$', '') as task_name
      , log_file
      , regexp_replace(code_log, '\\r\\n|\\r', '\\n') as code_block
    from {{ ref('int_log_grouped') }}
    where flag_block is not null
      and code_log is not null
      and length(trim(code_log)) > 0
      and project_name is not null
      and task_name is not null
      and length(trim(regexp_replace(project_name, '^\\''|\\''$', ''))) > 0
      and length(trim(regexp_replace(task_name, '^\\''|\\''$', ''))) > 0
  )

  , lib_lines as (
    select
      project_name
      , task_name
      , log_file
      , trim(line) as line
    from lib_base
    lateral view explode(split(code_block, '\\n')) e as line
  )

  , libnames as (
    select
      project_name
      , task_name
      , log_file
      , upper(regexp_extract(line, '(?i)\\blibname\\s+([a-z_][a-z0-9_]*)', 1)) as libref
      , coalesce(
          nullif(regexp_extract(line, "(?i)\\blibname\\s+[a-z_][a-z0-9_]*\\s+(?:base\\s+)?'([^']+)'", 1), ''),
          nullif(regexp_extract(line, '(?i)\\blibname\\s+[a-z_][a-z0-9_]*\\s+(?:base\\s+)?\"([^\"]+)\"', 1), ''),
          nullif(regexp_extract(line, "(?i)\\blibname\\s+[a-z_][a-z0-9_]*\\s+(?:base\\s+)?([^\\s;]+)", 1), '')
        ) as lib_path
    from lib_lines
    where regexp_like(line, '(?i)\\blibname\\b')
      and not regexp_like(line, '(?i)\\blibname\\s+\\w+\\s+clear\\b')
  )

  , lib_final as (
    select distinct
      project_name
      , task_name
      , 'LIB' as macro_type
      , libref as var_name
      , lib_path as var_value
      , cast(null as string) as var_stmt
    from libnames
    where libref is not null
      and libref <> ''
      and lib_path is not null
      and lib_path <> ''
      and project_name is not null
      and task_name is not null
      and length(trim(project_name)) > 0
      and length(trim(task_name)) > 0
  )

  , final as (
    select
      project_name
      , task_name
      , macro_type
      , var_name
      , var_value
      , var_stmt
    from let_final

    union all

    select
      project_name
      , task_name
      , macro_type
      , var_name
      , var_value
      , var_stmt
    from lib_final
  )

select
  project_name
  , task_name
  , macro_type as var_type
  , var_name
  , var_value
  , var_stmt
from final
