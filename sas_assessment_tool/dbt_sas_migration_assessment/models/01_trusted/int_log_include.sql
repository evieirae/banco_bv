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

  -- ============== EXPLOSÃO POR PONTO E VÍRGULA (;) ==============
  , exploded as (
      select
          base_blocks.log_file
          , base_blocks.project_name
          , base_blocks.task_name
          , trim(regexp_replace(pe.chunk, '(?s)/\\*.*?\\*/', '')) as content
      from base_blocks
      lateral view posexplode(split(regexp_replace(base_blocks.code_norm, '\\n|\\r', ' '), ';')) pe as pos, chunk
      where pe.chunk is not null
          and trim(pe.chunk) <> ''
  )

  -- ============== FILTRO %INCLUDE ==============
  , filter_include as (
      select
        log_file
        , project_name
        , task_name
        , content
        , trim(regexp_replace(content, '(?i)^%INCLUDE\\s+', '')) as remainder
      from exploded
      where regexp_like(content, '(?i)^%INCLUDE\\s+')
  )

  -- ============== EXTRAÇÃO DO CAMINHO OU FILEREF ==============
  , parsed_include as (
      select 
        *
        , case
            -- Se for caminho entre aspas simples
            when substring(remainder, 1, 1) = chr(39) 
                 then concat(chr(39), substring_index(substring(remainder, 2), chr(39), 1), chr(39))
            -- Se for caminho entre aspas duplas
            when substring(remainder, 1, 1) = chr(34) 
                 then concat(chr(34), substring_index(substring(remainder, 2), chr(34), 1), chr(34))
            -- Se for um FILEREF ou caminho sem aspas (pega até o próximo espaço)
            else regexp_extract(remainder, '^([^\\s]+)', 1)
          end as raw_include_path
      from filter_include
  )

  -- ============== LIMPEZA FINAL ==============
  , final as (
      select
        log_file
        , project_name
        , task_name
        , content
        , case
            when substring(raw_include_path, 1, 1) = chr(39) then substring_index(substring(raw_include_path, 2), chr(39), 1)
            when substring(raw_include_path, 1, 1) = chr(34) then substring_index(substring(raw_include_path, 2), chr(34), 1)
            else raw_include_path
          end as include_path
        , case 
            when substring(raw_include_path, 1, 1) in (chr(39), chr(34), '/', '\\') then 'DIRECT_PATH'
            else 'FILEREF'
          end as include_type
      from parsed_include
      where raw_include_path is not null and trim(raw_include_path) <> ''
  )

select * from final
