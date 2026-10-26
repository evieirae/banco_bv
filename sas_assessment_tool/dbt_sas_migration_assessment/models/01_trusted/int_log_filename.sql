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

  -- ============== EXPLOSÃO INTELIGENTE (POR PONTO E VÍRGULA) ==============
  , exploded as (
      select
          base_blocks.log_file
          , base_blocks.project_name
          , base_blocks.task_name
          , trim(regexp_replace(upper(pe.chunk), '(?s)/\\*.*?\\*/', '')) as content
      from base_blocks
      lateral view posexplode(split(regexp_replace(base_blocks.code_norm, '\\n|\\r', ' '), ';')) pe as pos, chunk
      where pe.chunk is not null
          and trim(pe.chunk) <> ''
  )

  -- ============== FILTRO FILENAME ==============
  , filter_exploded as (
      select
        log_file
        , project_name
        , task_name
        , content
        , trim(upper(regexp_replace(content, '(?i)^FILENAME\\s+', ''))) as sem_filename
      from exploded
      where 
        regexp_like(content, '(?i)^FILENAME\\s+') 
        and trim(content) <> ''
        and substring(trim(upper(regexp_replace(content, '(?i)^FILENAME\\s+', ''))), 1, 1) <> '%'
        and substring(trim(upper(regexp_replace(content, '(?i)^FILENAME\\s+', ''))), 1, 1) <> '='
  )

  -- ============== QUEBRA EM PARTES ==============
  , parts as (
      select
        *
        , upper(regexp_extract(sem_filename, '^([a-zA-Z0-9_\\*\\&\\.]+)', 1)) as fileref
        , trim(regexp_replace(sem_filename, '^[a-zA-Z0-9_\\*\\&\\.]+\\s*', '')) as remainder
      from filter_exploded
  )

  -- ============== A VACINA ESTENDIDA (AGORA COM PARÊNTESES) ==============
  -- ============== A VACINA ESTENDIDA (AGORA LÊ PONTOS E MACROS) ==============
  , parsed_remainder as (
      select 
        *
        , case
            when substring(remainder, 1, 1) = chr(39) 
                 then concat(chr(39), substring_index(substring(remainder, 2), chr(39), 1), chr(39))
            when substring(remainder, 1, 1) = chr(34) 
                 then concat(chr(34), substring_index(substring(remainder, 2), chr(34), 1), chr(34))
            when substring(remainder, 1, 1) = '(' 
                 then concat('(', substring_index(substring(remainder, 2), ')', 1), ')')
            when substring(remainder, 1, 1) in ('/', '\\', '.') then regexp_extract(remainder, '^([^\\s]+)', 1)
            
            -- O PULO DO GATO AQUI: Agora ele aceita ponto (.) e macro (&) como parte de uma mesma palavra contínua!
            when regexp_like(remainder, '^[a-zA-Z0-9_&]') then regexp_extract(remainder, '^([a-zA-Z0-9_\\.&]+)', 1)
            
            else regexp_extract(remainder, '^([^\\s]+)', 1)
          end as token1
      from parts
  )

  , final_logic as (
      select 
        *
        , regexp_replace(substring(remainder, length(token1) + 1), '^\\s+|\\s+$', '') as remainder2
    from parsed_remainder
  )

  -- ============== AVALIAÇÃO DO MOTOR E CAMINHO ==============
  , evaluated as (
      select 
        *
        , case
            when upper(fileref) = '_ALL_' then 'CLEAR'
            when upper(token1) in ('CLEAR', 'LIST') then upper(token1)
            when trim(token1) = '' then 'LIST'
            -- Se for um motor conhecido, crava SERVICE
            when upper(token1) in ('EMAIL', 'FTP', 'SFTP', 'ZIP', 'TEMP', 'PIPE', 'HADOOP', 'URL', 'WEBDAV', 'SOCKET') then 'SERVICE'
            
            -- MUDANÇA AQUI: Se a palavra tiver um ponto ou uma macro, sabemos que é um arquivo (PATH) e não um motor
            when regexp_like(token1, '\\.|&') then 'PATH'
            
            when substring(token1, 1, 1) in (chr(39), chr(34), '/', '\\', '.', '(') then 'PATH'          
            when substring(remainder2, 1, 1) in (chr(39), chr(34), '/', '\\', '.', '(') then 'PATH' 
            else 'SERVICE'                                                
          end as calc_filename_type
          
        , case
            -- MUDANÇA AQUI: Se tiver ponto ou macro, o token1 É o próprio caminho do arquivo
            when regexp_like(token1, '\\.|&') and upper(token1) not in ('EMAIL', 'FTP', 'SFTP', 'ZIP', 'TEMP', 'PIPE', 'HADOOP', 'URL', 'WEBDAV', 'SOCKET') then token1
            
            when substring(token1, 1, 1) in (chr(39), chr(34), '/', '\\', '.', '(') then token1
            when substring(remainder2, 1, 1) = chr(39) 
                 then concat(chr(39), substring_index(substring(remainder2, 2), chr(39), 1), chr(39))
            when substring(remainder2, 1, 1) = chr(34) 
                 then concat(chr(34), substring_index(substring(remainder2, 2), chr(34), 1), chr(34))
            when substring(remainder2, 1, 1) = '(' 
                 then concat('(', substring_index(substring(remainder2, 2), ')', 1), ')')
            when substring(remainder2, 1, 1) in ('/', '\\', '.') then regexp_extract(remainder2, '^([^\\s]+)', 1)
            else null
          end as calc_filename_path
      from final_logic
  )

  -- ============== LIMPEZA FINAL ==============
  , pos_evaluated as (
      select
        log_file
        , project_name
        , task_name
        , content
        , fileref
        , calc_filename_type as filename_type
        
        , case
            when calc_filename_type in ('CLEAR', 'LIST') then null 
            when token1 in ('-', '%INCLUDE') then null
            when upper(fileref) = '_ALL_' then null
            
            -- MUDANÇA AQUI: Se for caminho com ponto ou aspa, assume que o motor é o básico (BASE)
            when regexp_like(token1, '\\.|&') and upper(token1) not in ('EMAIL', 'FTP', 'SFTP', 'ZIP', 'TEMP', 'PIPE', 'HADOOP', 'URL', 'WEBDAV', 'SOCKET') then 'BASE'
            when substring(token1, 1, 1) in (chr(39), chr(34), '/', '\\', '.', '(') then 'BASE'
            else upper(token1)                                      
        end as connection_engine
        
        -- Limpa espaços extras e remove qualquer aspa solta que tenha ficado esquecida
        , case
            when calc_filename_path is not null then 
              regexp_replace(
                  case
                    when substring(calc_filename_path, 1, 1) = chr(39) then substring_index(substring(calc_filename_path, 2), chr(39), 1)
                    when substring(calc_filename_path, 1, 1) = chr(34) then substring_index(substring(calc_filename_path, 2), chr(34), 1)
                    else calc_filename_path
                  end
              , '["'']+', '') -- Limpa as aspas finais orfãs (como aquele ")
            else null
          end as filename_path
        
        , case
            when calc_filename_type in ('PATH', 'SERVICE') then 
                case 
                    when calc_filename_path = token1 then regexp_replace(nullif(trim(remainder2), ''), '\\s+', ' ')
                    else regexp_replace(nullif(trim(substring(remainder2, length(calc_filename_path) + 1)), ''), '\\s+', ' ')
                end
            else null
        end as file_options
      from evaluated
  )

select
    log_file
    , project_name
    , task_name
    , content
    , case when trim(fileref) <> '' then fileref else null end as fileref
    , case when trim(filename_type) <> '' then filename_type else null end as filename_type
    , case when trim(filename_path) <> '' then filename_path else null end as filename_path
    , case when trim(connection_engine) <> '' then connection_engine else null end as connection_engine
    , case when trim(file_options) <> '' then file_options else null end as file_options
from pos_evaluated
where fileref is not null 
  and trim(fileref) <> '';