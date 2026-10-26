with
  base_blocks as (
    select
        log_file
        , project_name
        , task_name
        , trim(regexp_replace(
            regexp_replace(trim(statement), '^\"|\"$', '')
            , '(?s)/\\*.*?\\*/', ''
          )) as statement
    from {{ ref('int_log_statement') }}
    where 
      statement is not null
      and trim(statement) <> ''
  )


  -- ============== FLUXO 1: PROC IMPORT ==============
  , proc_import_blocks as (
      select
          log_file
          , project_name
          , task_name
          , 'PROC_IMPORT' as import_method
          , upper(statement) as content
          , upper(regexp_extract(statement, '(?i)OUT\\s*=\\s*([a-zA-Z0-9_\\.\\&]+)', 1)) as target_table
          , upper(regexp_extract(statement, '(?i)DBMS\\s*=\\s*([a-zA-Z0-9_]+)', 1)) as file_type
          
          -- A VACINA: 
          -- 1. Tenta o padrão correto (DATAFILE=) ou o Alias legado (FILE=)
          -- 2. Se o programador engoliu a palavra (passou posicional), captura a partir da primeira aspa (' ou ")
          , coalesce(
              nullif(trim(regexp_extract(statement, '(?i)(?:DATAFILE|FILE)\\s*=\\s*(?s)(.*)', 1)), '')
              , trim(regexp_extract(statement, '(?s)([''"].*)', 1))
          ) as remainder_path
          
      from base_blocks
      where regexp_like(statement, '(?i)PROC\\s+IMPORT')
  )

  -- ============== FLUXO 2: INFILE (DATA STEP) ==============
  , infile_blocks as (
      select
          log_file
          , project_name
          , task_name
          , 'INFILE' as import_method
          , upper(statement) as content
          , upper(regexp_extract(statement, '(?i)DATA\\s+([a-zA-Z0-9_\\.\\&]+)', 1)) as target_table
          , 'TEXT/CSV' as file_type
          
          -- O Pulo do Gato: Pega TUDO (até quebra de linha) que vem depois do INFILE
          , trim(regexp_extract(statement, '(?i)INFILE\\s+(?s)(.*)', 1)) as remainder_path
          
      from base_blocks
      where regexp_like(statement, '(?i)INFILE\\s+')
  )

  -- ============== UNIFICAÇÃO DOS FLUXOS ==============
  , unified_imports as (
      select * from proc_import_blocks
      union all
      select * from infile_blocks
  )

  -- ============== EXTRAÇÃO BLINDADA DO CAMINHO ==============
-- ============== EXTRAÇÃO BLINDADA DO CAMINHO ==============
  , extract_path as (
      select
          *
          , case
              when substring(remainder_path, 1, 1) = chr(39) 
                   then concat(chr(39), substring_index(substring(remainder_path, 2), chr(39), 1), chr(39))
              when substring(remainder_path, 1, 1) = chr(34) 
                   then concat(chr(34), substring_index(substring(remainder_path, 2), chr(34), 1), chr(34))
              when substring(remainder_path, 1, 1) in ('/', '\\', '.', '&') 
                   then regexp_extract(remainder_path, '^([^\\s;]+)', 1)
              when regexp_like(remainder_path, '^[a-zA-Z0-9_]') 
                   then regexp_extract(remainder_path, '^([a-zA-Z0-9_]+)', 1)
              else null
            end as raw_file_path
      from unified_imports
  )

  -- ============== RESOLUÇÃO DO CAMINHO ==============
  , path_resolved as (
      select
          *
          -- Remove as aspas para entregar o caminho limpo 
          , case
              when substring(raw_file_path, 1, 1) = chr(39) 
                   then substring_index(substring(raw_file_path, 2), chr(39), 1)
              when substring(raw_file_path, 1, 1) = chr(34) 
                   then substring_index(substring(raw_file_path, 2), chr(34), 1)
              else raw_file_path
            end as file_path
      from extract_path
      where raw_file_path is not null
        and trim(raw_file_path) <> ''
  )

  -- ============== TRATAMENTO FINAL (COM INFERÊNCIA DE TIPO) ==============
  , treated as (
      select
          log_file
          , project_name
          , task_name
          , import_method
          , target_table
          
          -- O Pulo do Gato: Se DBMS não existir, pega a extensão do arquivo!
          , case
              when file_type is not null and trim(file_type) <> '' then file_type
              else upper(regexp_extract(file_path, '\\.([a-zA-Z0-9]+)$', 1))
            end as file_type
            
          , file_path
          , raw_file_path
          , content
      from path_resolved
  )

select
    log_file
    , project_name
    , task_name
    , content
    , import_method
    , target_table
    , file_type
    , file_path
    , raw_file_path
from treated;