with
  modernized as (
    select distinct
      upper(table_name) as table_name
    from {{ ref('int_table_modernized') }}
  )

  , modernized_origin as (
      select distinct
        upper(table_name_origin) as table_name_origin
        , upper(replace(source_dataset, '_')) as source_dataset
        , size(split(table_name_origin, '\\.')) - 1 as dot_count
        , get(split(table_name_origin, '\\.'), 0) as p1
        , get(split(table_name_origin, '\\.'), 1) as p2
        , get(split(table_name_origin, '\\.'), 2) as p3
      from {{ ref('int_table_modernized') }}
      where table_name_origin is not null
  )

  , logs_statements as (
      select
        log_file
        , project_name
        , task_name
        , type_statement
        , regexp_replace(statement, '(?s)/\\*.*?\\*/', '') as statement
      from {{ ref('int_log_statement') }}
  )

  , conn as (
    select
      log_file
      , project_name
      , task_name
      , connection_type
      , alias
    from {{ ref('int_project_connection') }}
  )

  , statements_with_connection as (
    select
      logs_statements.*
      , case
          when regexp_like(logs_statements.statement, '(?i)connect(?:ion)?\\s+to') then 1
          else 0
        end as has_external_connection
      , conn.connection_type as connection_type
    from logs_statements
    left join conn
      on conn.log_file = logs_statements.log_file
      and conn.project_name = logs_statements.project_name
      and conn.task_name = logs_statements.task_name
      and (
        regexp_like(logs_statements.statement, '(?i)connect?\\s+to')
        and upper(regexp_extract(logs_statements.statement, '(?i)connection?\\s+to\\s+(\\w+)', 1)) = upper(conn.alias)
        and (
          regexp_extract(logs_statements.statement, '(?i)connect?\\s+to\\s+(\\w+)\\*\\*masked_by_script', 1) != '' 
          and startswith(
              conn.connection_type
              , upper(regexp_extract(logs_statements.statement, '(?i)connect?\\s+to\\s+(\\w+)\\*\\*masked_by_script', 1))
          )
        )
        or  upper(regexp_extract(logs_statements.statement, '(?i)connection?\\s+to\\s+(\\w+)', 1)) = upper(conn.connection_type)
      )
    where type_statement not like 'PROC SORT'
  )

  , ln_tgt_sql as (
    select distinct
      project_name
      , task_name
      , log_file
      , upper(
          regexp_extract(statement, '(?i)\\b(create\\s+table|insert\\s+into)\\s+([A-Za-z0-9_\\.]+)', 2)
        ) as table_name
      , 'PROC SQL' as origin
      , 'TARGET' as role
    from statements_with_connection
    where regexp_like(statement, '(?i)\\b(create\\s+table|insert\\s+into)\\b')
  )

  , ln_tgt_data as (
    select distinct
      project_name
      , task_name
      , log_file
      , upper(
          regexp_extract(statement, '(?i)\\bdata\\s*(?:=)?\\s*([A-Za-z0-9_\\.]+)', 1)
        ) as table_name
      , 'DATA' as origin
      , 'TARGET' as role
    from statements_with_connection
    where regexp_like(statement, '(?i)^\\s*data\\s+')
      and upper(regexp_extract(statement, '(?i)\\bdata\\s*(?:=)?\\s*([A-Za-z0-9_\\.]+)', 1)) != '_NULL_'
  )

  , ln_tgt_proc_import as (
    select distinct
      project_name
      , task_name
      , log_file
      , upper(regexp_extract(statement, '(?i)\\bout\\s*=\\s*([A-Za-z0-9_\\.]+)', 1)) as table_name
      , 'PROC IMPORT' as origin
      , 'TARGET' as role
    from statements_with_connection
    where type_statement = 'PROC IMPORT'
  )

  , targets as (
    select * from ln_tgt_sql
    union all
    select * from ln_tgt_data
    union all
    select * from ln_tgt_proc_import
  )

  , no_connection as (
    select *
    from statements_with_connection
    where has_external_connection = 0
  )

  , ln_src_sql as (
    select distinct
      project_name
      , task_name
      , log_file
      , upper(exploded_src.src) as table_name
      , 'PROC SQL' as origin
      , 'SOURCE' as role
      , 0 as has_external_connection
      , null as connection_type
    from no_connection
    lateral view explode(
      array_distinct(
        array_union(
          regexp_extract_all(
            statement,
            '(?i)\\b(from|join)\\s+([A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?)',
            2
          ),
          regexp_extract_all(
            statement,
            '(?i)\\b(from|join)\\s+(&[A-Za-z0-9_]+\\.?)',
            2
          )
        )
      )
    ) exploded_src as src
    where exploded_src.src is not null
      and trim(exploded_src.src) <> ''
  )

  , ln_src_data as (
    select distinct
      project_name
      , task_name
      , log_file
      , upper(regexp_extract(statement, '(?i)\\bset\\s+([^;\\s]+)', 1)) as table_name
      , 'DATA' as origin
      , 'SOURCE' as role
      , has_external_connection
      , connection_type
    from no_connection
    where regexp_like(statement, '(?i)\\b(set|merge)\\b')
  )

  , with_connection as (
    select *
    from statements_with_connection
    where has_external_connection = 1
  )

  , with_connection_instr as (
    select
      *
      , regexp_extract(
          statement,
          '(?i)((?:connection to|connect to)\\s+[A-Za-z0-9_]+\\s*\\()',
          1
        ) as conn_phrase
    from with_connection
  )

  , with_connection_cut as (
    select
      *
      , case
          when conn_phrase is not null and length(conn_phrase) > 0
            then instr(upper(statement), upper(conn_phrase)) + length(conn_phrase) - 1
          else 0
        end as pos_open_paren
      , case
          when conn_phrase is not null and length(conn_phrase) > 0
            then instr(upper(statement), upper(conn_phrase)) + length(conn_phrase) - 1
              + instr(
                  substring(
                    statement,
                    instr(upper(statement), upper(conn_phrase)) + length(conn_phrase),
                    length(statement)
                  ),
                  ')'
                )
          else 0
        end as pos_close_paren
    from with_connection_instr
  )

  , with_connection_parts as (
    select
      project_name
      , task_name
      , log_file
      , connection_type
      , case
          when pos_open_paren > 0 and pos_close_paren > pos_open_paren
            then substring(statement, pos_open_paren + 1, pos_close_paren - pos_open_paren - 1)
          else ''
        end as part_inside
      , trim(concat(
          case when pos_open_paren > 1 then substring(statement, 1, pos_open_paren - 1) else '' end,
          ' ',
          case when pos_close_paren > 0 then substring(statement, pos_close_paren + 1, length(statement)) else statement end
        )) as part_outside
    from with_connection_cut
  )

  , ln_src_external_before as (
    select distinct
      project_name
      , task_name
      , log_file
      , upper(exploded_src.src) as table_name
      , 'PROC SQL' as origin
      , 'SOURCE' as role
      , 0 as has_external_connection
      , cast(null as string) as connection_type
    from with_connection_parts
    lateral view explode(
      array_distinct(
        regexp_extract_all(
          part_outside,
          '(?i)\\b(from|join)\\s+([A-Za-z0-9_\\-]{2,}\\.[A-Za-z0-9_\\-]+(?:\\.[A-Za-z0-9_\\-]+)?)',
          2
        )
      )
    ) exploded_src as src
    where exploded_src.src is not null
      and trim(exploded_src.src) <> ''
  )

  , ln_src_external_after as (
    select distinct
      project_name
      , task_name
      , log_file
      , upper(exploded_src.src) as table_name
      , 'PROC SQL' as origin
      , 'SOURCE' as role
      , 1 as has_external_connection
      , connection_type
    from with_connection_parts
    lateral view explode(
      array_distinct(
        regexp_extract_all(
          part_inside,
          '(?i)\\b(from|join)\\s+([A-Za-z0-9_\\-]{2,}\\.[A-Za-z0-9_\\-]+(?:\\.[A-Za-z0-9_\\-]+)?)',
          2
        )
      )
    ) exploded_src as src
    where exploded_src.src is not null
      and trim(exploded_src.src) <> ''
  )

  , sources as (
    select * from ln_src_sql
    union all
    select * from ln_src_data
    union all
    select * from ln_src_external_before
    union all
    select * from ln_src_external_after
  )

  , union_all_tables as (
    select
      *
      , 0 as has_external_connection
      , null as connection_type
    from targets
    union all
    select * from sources
  )

  , filter_all_tables as (
    select *
    from union_all_tables
    where table_name is not null
      and not endswith(table_name, '.')
      and table_name not like '_NULL_'
      and table_name not like ''
      and table_name not like '!'
      and not startswith(table_name, '/*')
      and table_name not like '%IF'
  )

  , normalized_tables as (
    select
      *
      , size(split(table_name, '\\.')) - 1 as dot_count
      , get(split(table_name, '\\.'), 0) as p1
      , get(split(table_name, '\\.'), 1) as p2
      , get(split(table_name, '\\.'), 2) as p3
    from filter_all_tables
  )

  , int_log_libname as (
      select
        log_file
        , project_name
        , task_name
        , libname_alias
        , libname_type
        , connection_engine
        , content
        , case 
            when connection_engine IN ('XML','XMLV2','EXCEL','JSON') then 'FILE'
            when connection_engine IN ('V9','BASE') then 'SAS'
            when libname_type = 'META' then connection_engine
            when libname_type = 'DATABASE' then connection_engine
        end as connection_type
      from {{ ref('int_log_libname') }}
      where libname_type not in ('CLEAR', 'LIST')
  )

  , join_normalized_table_log as (
    select 
        normalized_tables.project_name
        , normalized_tables.task_name
        , normalized_tables.log_file
        , normalized_tables.table_name
        , normalized_tables.origin
        , normalized_tables.role
        , case 
            when int_log_libname.connection_type in ('SAS', 'FILE')
                then 0
            when 
                int_log_libname.connection_type not in ('SAS', 'FILE')
                and int_log_libname.connection_type is not null
                then 1
            else normalized_tables.has_external_connection
        end as has_external_connection
        , normalized_tables.connection_type
        , normalized_tables.dot_count
        , normalized_tables.p1
        , normalized_tables.p2
        , normalized_tables.p3
        , int_log_libname.connection_type as connection_type_libname
    from normalized_tables
    left join int_log_libname
        on normalized_tables.log_file = int_log_libname.log_file
        and upper(normalized_tables.p1) = upper(int_log_libname.libname_alias)
        and normalized_tables.p2 is not null
  )

  , joined_tables_modernized as (
    select distinct
      join_normalized_table_log.project_name
      , join_normalized_table_log.task_name
      , join_normalized_table_log.log_file
      , join_normalized_table_log.table_name
      , join_normalized_table_log.role
      , join_normalized_table_log.origin
      , join_normalized_table_log.has_external_connection
      , case
          when join_normalized_table_log.p1 = 'WORK'
            or join_normalized_table_log.dot_count = 0
            then 'WORK'
          when connection_type_libname = 'FILE'
            then 'FILE'
          when startswith(join_normalized_table_log.table_name, 'BV-PDBD-')
            and join_normalized_table_log.dot_count = 2
            then 'BIGQUERY'
          when join_normalized_table_log.role = 'TARGET'
            or (
              join_normalized_table_log.role = 'SOURCE'
              and join_normalized_table_log.has_external_connection = 0
            )
            or connection_type_libname = 'SAS'
            then 'SAS'
          when join_normalized_table_log.has_external_connection = 1
            and connection_type_libname is not null
            then connection_type_libname
          when join_normalized_table_log.has_external_connection = 1
            and modernized_origin.table_name_origin is not null
            then modernized_origin.source_dataset
          when join_normalized_table_log.has_external_connection = 1
            and join_normalized_table_log.connection_type is null
            and join_normalized_table_log.table_name like '%..%'
            then 'SYBASE'
          when join_normalized_table_log.has_external_connection = 1
            then join_normalized_table_log.connection_type
          when join_normalized_table_log.table_name like '%.%'
            then 'SAS'
        end as connection_type
      , case
          when modernized.table_name is not null then 1
          else 0
        end as is_modernized
      , case
          when modernized_origin.table_name_origin is not null then 1
          else 0
        end as is_possible_modernized
    from join_normalized_table_log
    left join modernized
      on join_normalized_table_log.has_external_connection = 1
      and upper(trim(join_normalized_table_log.table_name)) = upper(trim(modernized.table_name))
      and join_normalized_table_log.role != 'TARGET'
    left join modernized_origin
      on join_normalized_table_log.has_external_connection = 1
      and modernized.table_name is null
      and join_normalized_table_log.role != 'TARGET'
      and join_normalized_table_log.dot_count >= 1
      and (
        upper(trim(join_normalized_table_log.table_name)) = upper(trim(modernized_origin.table_name_origin))
        or (
          join_normalized_table_log.dot_count = 2
          and join_normalized_table_log.p2 = ''
          and modernized_origin.dot_count = 2
          and join_normalized_table_log.p1 = modernized_origin.p1
          and join_normalized_table_log.p3 = modernized_origin.p3
        )
        or (
          join_normalized_table_log.dot_count = 1
          and modernized_origin.dot_count >= 1
          and join_normalized_table_log.p1 = modernized_origin.p2
          and join_normalized_table_log.p2 = modernized_origin.p3
        )
      )
  )

  , final as (
    select distinct
      project_name
      , task_name
      , table_name
      , role
      , coalesce(
          connection_type,
          max(connection_type) over (
            partition by project_name, table_name
          ),
          'SAS'
        ) as connection_type
      , is_modernized
    from joined_tables_modernized
  )

select
  project_name
  , task_name
  , table_name
  , role
  , connection_type
  , is_modernized
from final