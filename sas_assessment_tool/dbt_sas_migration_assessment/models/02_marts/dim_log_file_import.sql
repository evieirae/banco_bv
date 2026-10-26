with 
  -- 1. Pega os imports deduplicados (removemos a coluna log_file e content para granular por tarefa)
  source_imports as (
    select distinct
        project_name
        , task_name
        , import_method
        , target_table
        , file_type
        , upper(file_path) as original_file_path
    from {{ ref('int_log_file_import') }}
    where target_table is not null 
      and trim(target_table) <> ''
  )

  -- 2. Pega os Filenames deduplicados do mesmo projeto para usar como "Dicionário de Tradução"
  , source_filenames as (
    select distinct
        project_name
        , fileref
        , connection_engine
        , upper(filename_path) as filename_path
    from {{ ref('int_log_filename') }}
    where fileref is not null
  )

  -- 3. O Casamento Perfeito (Linhagem Resolvida)
  , resolved_lineage as (
    select distinct
        i.project_name
        , i.task_name
        , i.import_method
        , i.target_table
        , i.file_type
        
        -- Mantemos o que estava escrito no código original (pode ser o caminho físico ou apenas um apelido)
        , i.original_file_path
        
        -- A MÁGICA DO CATÁLOGO: 
        -- Se o original_file_path for um apelido (Fileref), o COALESCE puxa o caminho físico real revelado pela int_log_filename!
        -- Se não for (se o dev já passou o caminho direto no import), ele mantém o caminho original.
        , coalesce(f.filename_path, i.original_file_path) as resolved_file_path
        
        -- Traz a engine do arquivo se ele veio de um FILENAME (Ex: ZIP, FTP, TEMP, EMAIL ou SUST).
        -- Se for um arquivo direto, cravamos 'BASE' (leitura padrão do sistema operacional).
        , coalesce(f.connection_engine, 'BASE') as connection_engine
        
    from source_imports i
    left join source_filenames f
        on i.project_name = f.project_name
        and upper(i.original_file_path) = upper(f.fileref)
  )

select *
from resolved_lineage