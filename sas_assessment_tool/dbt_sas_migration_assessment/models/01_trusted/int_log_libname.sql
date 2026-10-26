with
  base_blocks as (
    select
        log_file
        , project_name
        , task_name
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
          , base_blocks.project_name
          , base_blocks.task_name
          , trim(regexp_replace(regexp_replace(trim(pe.line), '\\r$', ''), '(?s)/\\*.*?\\*/', '')) as content
      from base_blocks
      lateral view posexplode(split(base_blocks.code_norm, '\\n')) pe as pos, line
      where pe.line is not null
          and trim(pe.line) <> ''
  )

  , filter_exploded as (
      select
        log_file
        , project_name
        , task_name
        , content
        , trim(upper(regexp_replace(content, '(?i)^libname\\s+', ''))) as sem_libname
      from exploded
      where 
        regexp_like(content, '(?i)^libname\\s+') 
        and trim(content) <> ''
        and substring(trim(upper(regexp_replace(content, '(?i)^libname\\s+', ''))), 1, 1) <> '%'
        and substring(trim(upper(regexp_replace(content, '(?i)^libname\\s+', ''))), 1, 1) <> '='
  )

  , parts as (
      select
        *
        , upper(regexp_extract(sem_libname, '^([a-zA-Z0-9_\\*\\&\\.]+)', 1)) as libname_alias
        , trim(regexp_replace(sem_libname, '^[a-zA-Z0-9_\\*\\&\\.]+\\s*', '')) as remainder
      from filter_exploded
  )

  , parsed_remainder as (
      select 
        *
        , case
            when substring(remainder, 1, 1) = chr(39) 
                 then concat(chr(39), substring_index(substring(remainder, 2), chr(39), 1), chr(39))
            when substring(remainder, 1, 1) = chr(34) 
                 then concat(chr(34), substring_index(substring(remainder, 2), chr(34), 1), chr(34))
            when substring(remainder, 1, 1) in ('/', '\\', '.') then regexp_extract(remainder, '^([^\\s;]+)', 1)
            when regexp_like(remainder, '^[a-zA-Z0-9_]') then regexp_extract(remainder, '^([a-zA-Z0-9_]+)', 1)
            else regexp_extract(remainder, '^([^\\s;]+)', 1)
          end as token1
      from parts
  )

  , final_logic as (
      select 
        *
        , regexp_replace(substring(remainder, length(token1) + 1), '^\\s+|\\s+$', '') as remainder2
    from parsed_remainder
  )

  , evaluated as (
      select 
        *
        , case
            when upper(token1) in ('CLEAR', 'LIST') then upper(token1)
            when trim(token1) = '' then 'LIST'
            when substring(token1, 1, 1) in (chr(39), chr(34), '/', '\\', '.') then 'PATH'          
            when substring(remainder2, 1, 1) in (chr(39), chr(34), '/', '\\', '.') then 'PATH' 
            when upper(token1) in ('XML', 'XMLV2', 'JSON', 'EXCEL') then 'PATH'
            else 'DATABASE'                                                 
          end as calc_libname_type
        , case
            when substring(token1, 1, 1) in (chr(39), chr(34), '/', '\\', '.') then token1
            when substring(remainder2, 1, 1) = chr(39) 
                 then concat(chr(39), substring_index(substring(remainder2, 2), chr(39), 1), chr(39))
            when substring(remainder2, 1, 1) = chr(34) 
                 then concat(chr(34), substring_index(substring(remainder2, 2), chr(34), 1), chr(34))
            when substring(remainder2, 1, 1) in ('/', '\\', '.') then regexp_extract(remainder2, '^([^\\s;]+)', 1)
            else null
          end as calc_libname_path
      from final_logic
  )

  , pos_evaluated as (
      select
        log_file
        , project_name
        , task_name
        , content
        , libname_alias
        , calc_libname_type as libname_type
        , calc_libname_path as libname_path
        , case
            when calc_libname_type in ('CLEAR', 'LIST') then null 
            when token1 in ('-', '%INCLUDE') then null
            when trim(token1) = '' then null
            when upper(token1) in ('XML', 'XMLV2', 'JSON', 'EXCEL') then upper(token1) -- Mantém o motor se for XML/JSON
            when substring(token1, 1, 1) in (chr(39), chr(34), '/', '\\', '.') then 'BASE'
            else upper(token1)                                      
        end as connection_engine
        , case
            when calc_libname_type = 'DATABASE' 
            then regexp_replace(
                    nullif(trim(substring_index(remainder2, ';', 1)), '')
                    , '\\s+', ' '
                )
            else null
        end as connection_options
        , case
            when calc_libname_type = 'PATH' then 
                case 
                    when calc_libname_path = token1 
                    then regexp_replace(
                            nullif(trim(substring_index(remainder2, ';', 1)), '')
                            , '\\s+', ' '
                        )
                    
                    else regexp_replace(
                            nullif(trim(substring_index(substring(remainder2, length(calc_libname_path) + 1), ';', 1)), '')
                            , '\\s+', ' '
                        )
                end
            else null
        end as path_options
      from evaluated

  )

  , final as (
      select
        log_file
        , project_name
        , task_name
        , content
        , case 
            when trim(libname_alias) <> '' then libname_alias
            else null
        end as libname_alias
        , case 
            when trim(libname_type) <> '' then libname_type
            else null
        end as libname_type
        , case 
            when trim(libname_path) <> '' then libname_path
            else null
        end as libname_path
        , case 
            when trim(connection_engine) <> '' then connection_engine
            else null
        end as connection_engine
        , case 
            when trim(connection_options) <> '' then connection_options
            else null
        end as connection_options
        , case 
            when trim(path_options) <> '' then path_options
            else null
        end as path_options
      from pos_evaluated
  )

select *
from final
