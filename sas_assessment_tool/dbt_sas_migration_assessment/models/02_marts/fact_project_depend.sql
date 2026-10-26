with
  int_log_statement as (
    select
      regexp_replace(trim(project_name), '^\\''|\\''$', '') as project_name
      , regexp_replace(trim(task_name), '^\\''|\\''$', '') as task_name
      , trim(type_statement) as type_statement
      , statement
    from {{ ref('int_log_statement') }}
    where project_name is not null
      and length(trim(project_name)) > 0
      and task_name is not null
      and length(trim(task_name)) > 0
      and statement is not null
      and length(trim(statement)) > 0
  )

  , base as (
    select
      project_name
      , task_name
      , statement
      , abs(
          xxhash64(
            concat_ws(
              '||',
              coalesce(project_name, ''),
              coalesce(task_name, ''),
              coalesce(type_statement, ''),
              coalesce(statement, '')
            )
          )
        ) as statement_key
      , coalesce(
          upper(nullif(type_statement, '')),
          case
            when regexp_like(statement, '(?i)^\\s*(?:\\d+\\s+)?proc\\s+([a-z0-9_]+)')
              then concat('PROC ', upper(regexp_extract(statement, '(?i)^\\s*(?:\\d+\\s+)?proc\\s+([a-z0-9_]+)', 1)))
            when regexp_like(statement, '(?i)^\\s*(?:\\d+\\s+)?data\\s+')
              then 'DATA'
            else null
          end
        ) as step_type
    from int_log_statement
  )

  , normalized4 as (
    select
      project_name
      , task_name
      , statement_key
      , step_type
      , trim(
          regexp_replace(
            regexp_replace(statement, '[\\r\\n]+', ' '),
            '\\s+',
            ' '
          )
        ) as stmt_norm
    from base
  )

  , connect_info as (
    select
      project_name
      , task_name
      , statement_key
      , step_type
      , stmt_norm
      , case
          when regexp_like(stmt_norm, '(?i)\\b(proc\\s+connect\\s+to|connect\\s+to|from\\s+connection\\s+to)\\b') then 1
          else 0
        end as connect_flag
      , case
          when regexp_extract(stmt_norm, '(?i)\\bconnect\\s+to\\s+([A-Za-z_][A-Za-z0-9_]*)', 1) <> ''
            then upper(regexp_extract(stmt_norm, '(?i)\\bconnect\\s+to\\s+([A-Za-z_][A-Za-z0-9_]*)', 1))
          else null
        end as connect_type
    from normalized4
  )

  , sql_clauses as (
    select
      project_name
      , task_name
      , statement_key
      , step_type
      , stmt_norm
      , split(stmt_norm, ';') as clauses
    from connect_info
    where step_type like 'PROC SQL%'
  )

  , sql_clauses_exploded as (
    select
      project_name
      , task_name
      , statement_key
      , clause_pos
      , trim(clause) as clause
    from sql_clauses
    lateral view posexplode(clauses) as clause_pos, clause
  )

  , sql_targets_raw as (
    select
      project_name
      , task_name
      , statement_key
      , upper(regexp_extract(clause, '(?i)\\bcreate\\s+table\\s+([A-Za-z0-9_\\.]+)', 1)) as target_table
    from sql_clauses_exploded
    where regexp_like(clause, '(?i)\\bcreate\\s+table\\b')

    union all

    select
      project_name
      , task_name
      , statement_key
      , upper(regexp_extract(clause, '(?i)\\binsert\\s+into\\s+([A-Za-z0-9_\\.]+)', 1)) as target_table
    from sql_clauses_exploded
    where regexp_like(clause, '(?i)\\binsert\\s+into\\b')
  )

  , sql_targets as (
    select distinct
      project_name
      , task_name
      , statement_key
      , target_table
    from sql_targets_raw
    where target_table is not null
      and target_table <> ''
  )

  , data_targets_raw as (
    select
      project_name
      , task_name
      , statement_key
      , upper(regexp_extract(stmt_norm, '(?i)\\bdata\\s+([A-Za-z0-9_\\.]+)', 1)) as target_table
    from connect_info
    where step_type like 'DATA%'
  )

  , data_targets as (
    select distinct
      project_name
      , task_name
      , statement_key
      , target_table
    from data_targets_raw
    where target_table is not null
      and target_table <> ''
  )

  , import_targets_raw as (
    select
      project_name
      , task_name
      , statement_key
      , upper(regexp_extract(stmt_norm, '(?i)\\bout\\s*=\\s*([A-Za-z0-9_\\.]+)', 1)) as target_table
    from connect_info
    where step_type like 'PROC IMPORT%'
  )

  , import_targets as (
    select distinct
      project_name
      , task_name
      , statement_key
      , target_table
    from import_targets_raw
    where target_table is not null
      and target_table <> ''
  )

  , export_targets_raw as (
    select
      project_name
      , task_name
      , statement_key
      , case
          when regexp_extract(stmt_norm, '(?i)\\boutfile\\s*=\\s*\"([^\"]+)\"', 1) <> '' then regexp_extract(stmt_norm, '(?i)\\boutfile\\s*=\\s*\"([^\"]+)\"', 1)
          when regexp_extract(stmt_norm, '(?i)\\boutfile\\s*=\\s*\\\'([^\\\']+)\\\'', 1) <> '' then regexp_extract(stmt_norm, '(?i)\\boutfile\\s*=\\s*\\\'([^\\\']+)\\\'', 1)
          else regexp_extract(stmt_norm, '(?i)\\boutfile\\s*=\\s*([^\\s;]+)', 1)
        end as target_table
    from connect_info
    where step_type like 'PROC EXPORT%'
  )

  , export_targets as (
    select distinct
      project_name
      , task_name
      , statement_key
      , target_table
    from export_targets_raw
    where target_table is not null
      and target_table <> ''
  )

  , all_targets as (
    select 'PROC SQL' as target_origin, project_name, task_name, statement_key, target_table from sql_targets
    union all
    select 'DATA' as target_origin, project_name, task_name, statement_key, target_table from data_targets
    union all
    select 'PROC IMPORT' as target_origin, project_name, task_name, statement_key, target_table from import_targets
    union all
    select 'PROC EXPORT' as target_origin, project_name, task_name, statement_key, target_table from export_targets
  )

  , sql_sources_raw as (
    select
      connect_info.project_name
      , connect_info.task_name
      , connect_info.statement_key
      , pos
      , trim(chunk) as chunk
    from all_targets
    join connect_info
      on all_targets.statement_key <=> connect_info.statement_key
    lateral view posexplode(
      split(
        regexp_replace(
          regexp_replace(connect_info.stmt_norm, '(?i)\\b(from\\s+connection\\s+to)\\b', ' FROM_CONNECTION_TO '),
          '(?i)\\b(from|join)\\s+',
          ' §'
        ),
        '§'
      )
    ) as pos, chunk
    where all_targets.target_origin = 'PROC SQL'
      and connect_info.step_type like 'PROC SQL%'
      and pos > 0
  )

  , cte_with_names as (
    select
      project_name
      , task_name
      , statement_key
      , upper(regexp_extract(stmt_norm, '(?i)\\bwith\\s+([A-Za-z_][A-Za-z0-9_]*)\\s+as\\s*\\(', 1)) as cte_name
    from connect_info
    where step_type like 'PROC SQL%'
      and regexp_extract(stmt_norm, '(?i)\\bwith\\s+([A-Za-z_][A-Za-z0-9_]*)\\s+as\\s*\\(', 1) <> ''
  )

  , sql_sources as (
    with extracted as (
      select
        sql_sources_raw.project_name
        , sql_sources_raw.task_name
        , sql_sources_raw.statement_key
        , upper(
            regexp_replace(
              regexp_extract(
                sql_sources_raw.chunk,
                '^(\\s*`?[A-Za-z_][A-Za-z0-9_\\-]*(?:\\.`?[A-Za-z_][A-Za-z0-9_\\-]*){0,2})',
                1
              ),
              '`',
              ''
            )
          ) as source_table
      from sql_sources_raw
      where regexp_extract(
          sql_sources_raw.chunk,
          '^(\\s*`?[A-Za-z_][A-Za-z0-9_\\-]*(?:\\.`?[A-Za-z_][A-Za-z0-9_\\-]*){0,2})',
          1
        ) <> ''
    )
    select distinct
      extracted.project_name
      , extracted.task_name
      , extracted.statement_key
      , extracted.source_table
    from extracted
    left join cte_with_names
      on extracted.statement_key <=> cte_with_names.statement_key
    where cte_with_names.cte_name is null
      or extracted.source_table <> cte_with_names.cte_name
  )

  , import_sources_raw as (
    select
      connect_info.project_name
      , connect_info.task_name
      , connect_info.statement_key
      , case
          when regexp_extract(connect_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*\"([^\"]+)\"', 1) <> '' then regexp_extract(connect_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*\"([^\"]+)\"', 1)
          when regexp_extract(connect_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*\\\'([^\\\']+)\\\'', 1) <> '' then regexp_extract(connect_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*\\\'([^\\\']+)\\\'', 1)
          else regexp_extract(connect_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*([^\\s;]+)', 1)
        end as source_raw
    from all_targets
    join connect_info
      on all_targets.statement_key <=> connect_info.statement_key
    where all_targets.target_origin = 'PROC IMPORT'
      and connect_info.step_type like 'PROC IMPORT%'
  )

  , import_sources as (
    select
      project_name
      , task_name
      , statement_key
      , trim(regexp_replace(source_raw, '\\s+!\\s+', ' ')) as source_table
    from import_sources_raw
    where source_raw is not null
      and source_raw <> ''
  )

  , export_sources_raw as (
    select
      connect_info.project_name
      , connect_info.task_name
      , connect_info.statement_key
      , upper(regexp_extract(connect_info.stmt_norm, '(?i)\\bdata\\s*=\\s*([A-Za-z0-9_\\.]+)', 1)) as source_table
    from all_targets
    join connect_info
      on all_targets.statement_key <=> connect_info.statement_key
    where all_targets.target_origin = 'PROC EXPORT'
      and connect_info.step_type like 'PROC EXPORT%'
  )

  , export_sources as (
    select distinct
      project_name
      , task_name
      , statement_key
      , source_table
    from export_sources_raw
    where source_table is not null
      and source_table <> ''
  )

  , data_sources_chunks as (
    select
      connect_info.project_name
      , connect_info.task_name
      , connect_info.statement_key
      , pos
      , chunk
    from all_targets
    join connect_info
      on all_targets.statement_key <=> connect_info.statement_key
    lateral view posexplode(
      split(
        regexp_replace(connect_info.stmt_norm, '(?i)\\bset\\b', '§set'),
        '§'
      )
    ) as pos, chunk
    where all_targets.target_origin = 'DATA'
      and connect_info.step_type like 'DATA%'
      and pos > 0
  )

  , data_sources_raw as (
    select
      project_name
      , task_name
      , statement_key
      , upper(regexp_extract(chunk, '(?i)\\bset\\s+([A-Za-z0-9_\\.]+)', 1)) as source_table
    from data_sources_chunks
  )

  , data_sources as (
    select distinct
      project_name
      , task_name
      , statement_key
      , source_table
    from data_sources_raw
    where source_table is not null
      and source_table <> ''
  )

  , infile_sources_raw as (
    select
      connect_info.project_name
      , connect_info.task_name
      , connect_info.statement_key
      , case
          when regexp_extract(connect_info.stmt_norm, '(?i)\\binfile\\s+\"([^\"]+)\"', 1) <> '' then regexp_extract(connect_info.stmt_norm, '(?i)\\binfile\\s+\"([^\"]+)\"', 1)
          when regexp_extract(connect_info.stmt_norm, '(?i)\\binfile\\s+\\\'([^\\\']+)\\\'', 1) <> '' then regexp_extract(connect_info.stmt_norm, '(?i)\\binfile\\s+\\\'([^\\\']+)\\\'', 1)
          else regexp_extract(connect_info.stmt_norm, '(?i)\\binfile\\s+([^\\s;]+)', 1)
        end as source_raw
    from all_targets
    join connect_info
      on all_targets.statement_key <=> connect_info.statement_key
    where all_targets.target_origin = 'DATA'
      and connect_info.step_type like 'DATA%'
      and regexp_like(connect_info.stmt_norm, '(?i)\\binfile\\b')
  )

  , infile_sources as (
    select
      project_name
      , task_name
      , statement_key
      , source_raw as source_table
    from infile_sources_raw
    where source_raw is not null
      and source_raw <> ''
  )

  , all_sources_raw as (
    select 
        project_name
        , task_name
        , statement_key
        , source_table 
    from sql_sources

    union all

    select 
        project_name
        , task_name
        , statement_key
        , source_table 
    from data_sources
    
    union all
    
    select 
        project_name
        , task_name
        , statement_key
        , source_table 
    from import_sources

    union all

    select 
        project_name
        , task_name
        , statement_key
        , source_table 
    from infile_sources

    union all

    select 
        project_name
        , task_name
        , statement_key
        , source_table 
    from export_sources
  )

  , sources_agg as (
    select
      project_name
      , task_name
      , statement_key
      , concat_ws(', ', sort_array(collect_set(source_table))) as source_table
    from all_sources_raw
    group by
      project_name
      , task_name
      , statement_key
  )

  , final_lineage as (
    select
      all_targets.project_name
      , all_targets.task_name
      , all_targets.target_table
      , sources_agg.source_table
      , coalesce(
          case when regexp_like(connect_info.stmt_norm, '(?i)\\binfile\\b') then 'INFILE' end,
          connect_info.step_type,
          all_targets.target_origin
        ) as type_statement
    from all_targets
    left join sources_agg
      on all_targets.statement_key <=> sources_agg.statement_key
    left join connect_info
      on all_targets.statement_key <=> connect_info.statement_key
  )

  , lineage_keyed as (
    select
      regexp_replace(trim(project_name), '^\\''|\\''$', '') as project_name
      , upper(
          coalesce(
            nullif(regexp_extract(project_name, '([^/\\\\]+\\.egp)', 1), ''),
            regexp_replace(trim(project_name), '^\\''|\\''$', '')
          )
        ) as project_key
      , task_name
      , target_table
      , source_table
      , type_statement
    from final_lineage
  )

  , lib_map as (
    select
      upper(
        coalesce(
          nullif(regexp_extract(project_name, '([^/\\\\]+\\.egp)', 1), ''),
          regexp_replace(trim(project_name), '^\\''|\\''$', '')
        )
      ) as project_key
      , upper(trim(var_name)) as libref
      , max(trim(var_value)) as lib_path
    from {{ ref('dim_variables') }}
    where var_type = 'LIB'
      and var_name is not null
      and var_value is not null
      and length(trim(var_name)) > 0
      and length(trim(var_value)) > 0
    group by
      upper(
        coalesce(
          nullif(regexp_extract(project_name, '([^/\\\\]+\\.egp)', 1), ''),
          regexp_replace(trim(project_name), '^\\''|\\''$', '')
        )
      )
      , upper(trim(var_name))
  )

  , edges_raw as (
    select
      lineage_keyed.project_key
      , lineage_keyed.project_name
      , coalesce(nullif(regexp_extract(lineage_keyed.project_name, '([^/\\\\]+\\.egp)', 1), ''), lineage_keyed.project_name) as parent_name
      , 'projeto SAS' as parent_type
      , 'le' as relationship_type
      , trim(exploded_chunk) as child_raw
      , lineage_keyed.type_statement
      , 'READ' as io
    from lineage_keyed
    lateral view explode(split(lineage_keyed.source_table, '\\s*,\\s*')) exploded_table as exploded_chunk
    where lineage_keyed.source_table is not null
      and length(trim(lineage_keyed.source_table)) > 0

    union all

    select
      lineage_keyed.project_key
      , lineage_keyed.project_name
      , coalesce(nullif(regexp_extract(lineage_keyed.project_name, '([^/\\\\]+\\.egp)', 1), ''), lineage_keyed.project_name) as parent_name
      , 'projeto SAS' as parent_type
      , 'escreve' as relationship_type
      , trim(lineage_keyed.target_table) as child_raw
      , lineage_keyed.type_statement
      , 'WRITE' as io
    from lineage_keyed
    where lineage_keyed.target_table is not null
      and length(trim(lineage_keyed.target_table)) > 0
  )

  , edges_clean as (
    select distinct
      project_key
      , parent_name
      , parent_type
      , relationship_type
      , trim(
          regexp_replace(
            regexp_replace(child_raw, '^\\\"|\\\"$', ''),
            '^\\''|\\''$',
            ''
          )
        ) as child_obj
      , type_statement
      , io
    from edges_raw
    where child_raw is not null
      and length(trim(child_raw)) > 0
  )

  , edges_parsed as (
    select
      edges_clean.*
      , case
          when regexp_like(edges_clean.child_obj, '[/\\\\]')
            or regexp_like(lower(edges_clean.child_obj), '\\.(csv|txt|dat|tsv|xlsx?|parquet|json|xml|gz)(\\b|$)')
            or regexp_like(lower(edges_clean.child_obj), '^https?://')
            then 1
          else 0
        end as is_file
      , upper(edges_clean.child_obj) as child_obj_u
      , split(upper(edges_clean.child_obj), '\\.') as parts
      , case
          when regexp_like(edges_clean.child_obj, '\\.') then size(split(upper(edges_clean.child_obj), '\\.')) - 1
          else 0
        end as dot_count
    from edges_clean
  )

  , edges_resolved as (
    select
      edges_parsed.parent_name
      , edges_parsed.parent_type
      , edges_parsed.relationship_type
      , case
          when edges_parsed.is_file = 1 then edges_parsed.child_obj
          when edges_parsed.dot_count = 0 then concat('WORK.', edges_parsed.child_obj_u)
          when edges_parsed.dot_count >= 2 then edges_parsed.child_obj_u
          when edges_parsed.dot_count = 1 and lib_map.lib_path is not null then
            concat(
              regexp_replace(lib_map.lib_path, '[\\\\/]+$', ''),
              case when regexp_like(lib_map.lib_path, '[\\\\/]') then '/' else '.' end,
              element_at(edges_parsed.parts, 2)
            )
          when edges_parsed.dot_count = 1 then edges_parsed.child_obj_u
          else edges_parsed.child_obj_u
        end as children_name
      , case
          when edges_parsed.is_file = 1 and edges_parsed.type_statement like 'PROC IMPORT%' and edges_parsed.io = 'READ' then 'Arquivo importado'
          when edges_parsed.is_file = 1 and edges_parsed.type_statement like 'PROC EXPORT%' and edges_parsed.io = 'WRITE' then 'Arquivo exportado'
          when edges_parsed.is_file = 1 then 'Arquivo externo'
          when edges_parsed.type_statement like 'PROC IMPORT%' and edges_parsed.io = 'WRITE' then 'Tabela importada'
          when edges_parsed.type_statement like 'PROC EXPORT%' and edges_parsed.io = 'READ' then 'Tabela exportada'
          when edges_parsed.dot_count = 0 then 'WORK'
          when edges_parsed.dot_count = 1 and element_at(edges_parsed.parts, 1) = 'WORK' then 'WORK'
          when edges_parsed.dot_count >= 2 then 'Tabela externa'
          when lib_map.lib_path is not null and regexp_like(lib_map.lib_path, '[\\\\/]') then 'Tabela SAS'
          when lib_map.lib_path is not null and not regexp_like(lib_map.lib_path, '[\\\\/]') then 'Tabela externa'
          else 'Tabela SAS'
        end as children_type
    from edges_parsed
    left join lib_map
      on edges_parsed.project_key = lib_map.project_key
      and edges_parsed.dot_count = 1
      and element_at(edges_parsed.parts, 1) = lib_map.libref
  )

  , final as (
    select distinct
      abs(xxhash64(concat_ws('|', parent_name, parent_type, relationship_type, children_name, children_type))) as relationship_id
      , parent_name
      , parent_type
      , relationship_type
      , children_name
      , children_type
    from edges_resolved
    order by parent_name, relationship_type, children_name
  )

select *
from final