with
  base_logs as (
    select
      cast(log_file as string) as log_file
      , cast(coalesce(log_date, to_timestamp(NULLIF(regexp_extract(content,'^(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2},\\d{3})',1),''),"yyyy-MM-dd'T'HH:mm:ss,SSS")) as timestamp) as log_date
      , cast(line_number as int) as file_line_number
      , cast(coalesce(user_id, NULLIF(regexp_extract(content,'(?<=:)[A-Za-z0-9._-]+(?=\\s+-)',0),'')) as string) as user_id
      , case
          when log_date is null 
            then nullif(cast(trim(regexp_extract(content,'-\\s+(.*)',1)) as string),'')
          else
              cast(content as string)
      end as content
      , cast(connection_type as string) as connection_type
    from {{ source('bv_migration_sas', 'log_base') }}
  )

  , stg_log_base as (
    select
        log_file
        , log_date
        , file_line_number
        , user_id
        , content
        , case
            when regexp_extract(content, '^(\\d+)', 1) = '' then null
            else cast(regexp_extract(content, '^(\\d+)', 1) as int)
          end as code_line_number
        , case
              when regexp_extract(content, '^(\\d+)', 1) like '' then content
              when regexp_extract(content, '^\\d+\\s+(.*)', 1) like '' then null
              else regexp_extract(content, '^\\d+\\s+(.*)', 1)
          end as clean_text
        , connection_type
    from base_logs
    where
      (
        regexp_like(content, '(?i)^\\s*\\d+')                             
        or regexp_like(content, '(?i)^\\s*real\\s+time\\b')                  
        or regexp_like(content, '(?i)^\\s*memory\\b')                        
        or regexp_like(content, '(?i)^\\s*OS\\s+Memory\\b')                  
        or regexp_like(content, '(?i)OPTIONS\\s+PAGENO=MIN;')        
        or regexp_like(content, '(?i)GOPTIONS\\s+NOACCESSIBLE;')        
      )  
      and content not like '%The SAS System%'
      and (
        case 
          when regexp_extract(content, '^(\\d+)', 1) like '' then content
          when regexp_extract(content, '^\\d+\\s+(.*)', 1) like '' then null
          else regexp_extract(content, '^\\d+\\s+(.*)', 1) 
        end
      ) is not null 
  )

  , stg_log_with_groups as (
    select
        *
        , sum(
            case
                when trim(clean_text) like '!%' then 0
                else 1
              end
          ) over (
            partition by log_file
            order by file_line_number
            rows between unbounded preceding and current row
          ) as stmt_group
    from stg_log_base
  )

  , stg_log_process as (
      select
          log_file
          , log_date
          , stmt_group
          , min(file_line_number) as file_line_number
          , first(user_id, true) as user_id
          , first(code_line_number, true) as code_line_number
          , concat_ws(
              ' ',
              sort_array(
                  collect_list(
                      regexp_replace(clean_text, '^!\\s*', '')
                  )
              )
            ) as clean_text
          , first(connection_type, true) as connection_type
      from stg_log_with_groups
      group by 
        log_file
        , log_date
        , stmt_group
  )

select
  log_file
  , log_date
  , file_line_number
  , user_id
  , code_line_number
  , clean_text
  , connection_type
from stg_log_process