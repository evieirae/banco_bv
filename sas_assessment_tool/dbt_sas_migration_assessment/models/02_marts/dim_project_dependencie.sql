with 
    config_constants as (
        select 
            700.0 as etl_max
            , 400.0 as analytical_max
            , 165.0 as ad_hoc_max
    ),

    base as (
        select
            trim(project_name) as project_name
            , trim(task_name)    as task_name
            , log_file
            , user_id
            , min_file_line_number as file_line_number
            , code_log
        from {{ ref('int_log_grouped') }}
        where flag_block is not null
        and code_log is not null
        and length(trim(code_log)) > 0
        and project_name is not null and length(trim(project_name)) > 0
        and task_name    is not null and length(trim(task_name)) > 0
    ),

    -- explode o code_log em linhas individuais da tabela origem
    src_exploded_lines as (
        select
            base.project_name
            , base.task_name
            , base.log_file
            , base.user_id
            , base.file_line_number + pe.pos as line_number
            , trim(pe.line) as statement
            , base.file_line_number
            , pe.pos
        from base base
        lateral view posexplode(
            split(
                regexp_replace(base.code_log, '\\r\\n|\\r', '\n'),
                '\n'
            )
        ) pe as pos, line
        where trim(pe.line) != ''
    ),

    -- -- Prepara statements individuais e define o tipo básico do passo (usado para linhagem)
    src_cleaned_statements as (
        select
            project_name
            , task_name
            , log_file
            , user_id
            , line_number
            , statement
            , trim(
                regexp_replace(
                    regexp_replace(statement, '[\\r\\n]+', ' '),
                    '\\s+', ' '
                )
            ) as stmt_norm
            , case
                when regexp_like(statement, '(?i)^\\s*proc\\s+([a-z0-9_]+)')
                    then concat(
                        'proc ',
                        upper(regexp_extract(statement,'(?i)^\\s*proc\\s+([a-z0-9_]+)',1))
                    )
                when regexp_like(statement, '(?i)^\\s*data\\s+')
                    then 'data'
                else null
            end as step_type
        from src_exploded_lines
    ),


    -- ===========================================================================================
    -- 2. extração de variáveis (%let)
    -- ===========================================================================================
    vars_extracted_key_values as (
        select distinct
            project_name
            , regexp_extract(stmt_norm, '(?i)%let\\s+([a-zA-Z_][a-zA-Z0-9_]*)', 1) as let_name
            , regexp_replace(
                regexp_extract(stmt_norm, '(?is)%let\\s+[a-zA-Z_][a-zA-Z0-9_]*\\s*=\\s*(.*?);', 1)
                , "'"
                , ''
            ) as let_value_raw
        from src_cleaned_statements
        where lower(stmt_norm) like '%let %'
    ),

    agg_project_variables as (
        select 
            project_name
            , sort_array(
                collect_list(
                    named_struct('key', let_name, 'value', let_value_raw)
                )
            ) as variables_used
        from vars_extracted_key_values
        group by project_name
    ),

    -- ===========================================================================================
    -- 3. classificação geral (etl / analytical / ad hoc - scoring)
    -- ===========================================================================================
    cls_code_indicators as (
        select
            *
            , case when upper(code_log) LIKE '%PROC SQL%' then 1 else 0 end as has_proc_sql
            , case when regexp_like(code_log, '(?i)PROC\\s+(IMPORT|EXPORT|LOAD|DBLOAD)') then 1 else 0 end as has_load_procs
            , case when regexp_like(code_log, '(?i)PROC\\s+(SORT|TRANSPOSE|STANDARDIZE)') then 1 else 0 end as has_transform_procs
            , case when regexp_like(code_log, '(?i)DATA\\s+\\w+') then 1 else 0 end as has_data_step
            , case when regexp_like(code_log, '(?i)\\b(SET|MERGE)\\s+') then 1 else 0 end as has_set_merge
            , case when regexp_like(code_log, '(?i)(MERGE|JOIN|INNER|LEFT|RIGHT|FULL|CROSS)') then 1 else 0 end as has_joins
            , case when regexp_like(code_log, '(?i)(CONNECT\\s+TO|LIBNAME|FROM\\s+CONNECTION)') then 1 else 0 end as has_database_connections
            , case when regexp_like(code_log, '(?i)(INSERT\\s+INTO|CREATE\\s+TABLE|UPDATE|DELETE\\s+FROM)') then 1 else 0 end as has_table_operations
            , case when has_data_step = 1 and has_set_merge = 1 then 1 else 0 end as has_data_step_transform
            , regexp_count(upper(code_log), '\\bFROM\\s') + regexp_count(upper(code_log), '\\bINTO\\s') + regexp_count(upper(code_log), '\\bSET\\s') + regexp_count(upper(code_log), '\\bMERGE\\s') as data_operations_count
            , case when regexp_like(code_log, '(?i)PROC\\s+(MEANS|FREQ|TABULATE|SUMMARY|UNIVARIATE|GPLOT)') then 1 else 0 end as has_statistical_procs
            , case when regexp_like(code_log, '(?i)PROC\\s+(REG|LOGISTIC|GLM|MIXED|GENMOD|PHREG)') then 1 else 0 end as has_regression_procs
            , case when regexp_like(code_log, '(?i)PROC\\s+(MODEL|FORECAST|ARIMA|TIMESERIES|AUTOREG)') then 1 else 0 end as has_modeling_procs
            , case when regexp_like(code_log, '(?i)PROC\\s+(NEURAL|DM|FOREST|SVM|HPFOREST|HPNEURAL|GMM)') then 1 else 0 end as has_ml_procs
            , case when regexp_like(code_log, '(?i)\\b(MEAN|STD|VAR|CORR|REGR)\\b') then 1 else 0 end as has_pure_statistical_functions
            , case when regexp_like(code_log, '(?i)PROC\\s+(PRINT|CONTENTS|DATASETS|CATALOG|ODS)') then 1 else 0 end as has_operational_procs
            , case when regexp_like(code_log, '(?i)\\%MACRO|\\%MEND|CALL\\s+SYMPUT|CALL\\s+EXECUTE') then 1 else 0 end as has_macro_logic
        from base
    ),

    cls_scored_blocks as (
        select
            ci.*
            , cc.etl_max
            , cc.analytical_max
            , cc.ad_hoc_max
            -- scores brutos
            , (
                has_load_procs * 95 + has_table_operations * 95 + has_data_step_transform * 90 +
                has_proc_sql * 80 + has_transform_procs * 80 + has_database_connections * 75 + 
                has_joins * 70 + case when data_operations_count >= 2 then 60 else 0 end
            ) as etl_score_brute
            , (
                has_ml_procs * 100 + has_modeling_procs * 95 + has_regression_procs * 90 + 
                has_statistical_procs * 85 + has_pure_statistical_functions * 30
            ) as analytical_score_brute
            , (
                has_operational_procs * 80 +
                case 
                    when has_proc_sql = 1 and has_table_operations = 0 and has_load_procs = 0
                        and has_joins = 0 and data_operations_count <= 1 then 85
                    else 0 
                end
            ) as ad_hoc_score_brute
            -- scores normalizados
            , (etl_score_brute / cc.etl_max) * 100 as etl_score
            , (analytical_score_brute / cc.analytical_max) * 100 as analytical_score
            , (ad_hoc_score_brute / cc.ad_hoc_max) * 100 as ad_hoc_score
        from cls_code_indicators ci, config_constants cc
    ),

    cls_categorized_general as (
        select 
            *
            , greatest(
                coalesce(etl_score, 0)
                , coalesce(analytical_score, 0)
                , coalesce(ad_hoc_score, 0)
            ) as confidence_score
            , case
                when etl_score >= analytical_score and etl_score >= ad_hoc_score then 'ETL'
                when analytical_score > etl_score and analytical_score >= ad_hoc_score then 'Analítico'
                when ad_hoc_score > etl_score and ad_hoc_score > analytical_score then 'Ad Hoc'
                else 'Indefinido'
            end as category
        from cls_scored_blocks
    ),

    -- ===========================================================================================
    -- 4. CLASSIFICAÇÃO ESPECÍFICA DE ML (Palavras-chave)
    -- ===========================================================================================
    ml_raw_content as (
        select
            project_name
            , lower(stmt_norm) as content_l
        from src_cleaned_statements
        where
            lower(stmt_norm) like '%proc %'
            or lower(stmt_norm) like '%enterprise miner%'
            or lower(stmt_norm) like '%inmodel%'
            or lower(stmt_norm) like '%gradboost%'
            or lower(stmt_norm) like '%tpbig%'
            or lower(stmt_norm) like '%tptipobig%'
            or lower(stmt_norm) like '%tsinclusao%'
            or lower(stmt_norm) like '%prob1%'
            or lower(stmt_norm) like '%predicao%'
            or lower(stmt_norm) like '%safra%'
            or lower(stmt_norm) like '%parti%'
            or lower(stmt_norm) like '%partition%'
            or lower(stmt_norm) like '%target%'
            or lower(stmt_norm) like '% score %'
            or lower(stmt_norm) like '% gh %'
    ),

    ml_hits_array as (
        select
            project_name
            , filter(
                array(
                    if(content_l like '%proc freq%', 'proc freq', null)
                    , if(content_l like '%proc means%', 'proc means', null)
                    , if(content_l like '%proc univariate%', 'proc univariate', null)
                    , if(content_l like '%proc corr%', 'proc corr', null)
                    , if(content_l like '%proc anova%', 'proc anova', null)
                    , if(content_l like '%proc reg%', 'proc reg', null)
                    , if(content_l like '%enterprise miner%', 'enterprise miner', null)
                    , if(content_l like '%proc glm%', 'proc glm', null)
                    , if(content_l like '%proc logistic%', 'proc logistic', null)
                    , if(content_l like '%proc forest%', 'proc forest', null)
                    , if(content_l like '%gradboost%', 'gradboost', null)
                    , if(content_l rlike '\\binmodel\\b', 'scoring (inmodel)', null)
                    , if(content_l like '%proc transpose%', 'proc transpose', null)
                    , if(content_l like '%proc rank%', 'proc rank', null)
                    , if(content_l like '%particao%', 'particao', null)
                    , if(content_l rlike '\\bscore\\b', 'score', null)
                    , if(content_l rlike '\\bgh\\b', 'bgh', null)
                    , if(content_l rlike '\\btarget\\b', 'target', null)
                    , if(content_l rlike '\\btsinclusao\\b', 'tsinclusao', null)
                    , if(content_l rlike '\\bprob1\\b', 'prob1', null)
                    , if(content_l rlike '\\bpredito\\b', 'predito', null)
                    , if(content_l rlike '\\btpbig\\b' or content_l rlike '\\btptipobig\\b', 'campos big (tpbig/tptipobig)', null)
                )
                , x -> x is not null
            ) as ocorrencias
        from ml_raw_content
    ),

    ml_hits_exploded as (
        select
            project_name
            , ocorrencia_encontrada
        from ml_hits_array
        lateral view explode(ocorrencias) e as ocorrencia_encontrada
    ),

    ml_categorized as (
        select
            project_name
            , 'Modelo ML' as finalidade_ml
        from ml_hits_exploded
        group by project_name
    ),

    -- ===========================================================================================
    -- 5. consolidação de classificações
    -- ===========================================================================================
    meta_union_categories as (
        select 
            project_name
            , finalidade_ml as category 
        from ml_categorized
        union
        select 
            project_name
            , category 
        from cls_categorized_general
    ),

    agg_project_classification as (
        select
            project_name
            , concat_ws(', ', collect_set(category)) as process_type
        from meta_union_categories
        group by project_name
    ),

    -- ===========================================================================================
    -- 6. normalização para linhagem
    -- ===========================================================================================
    ln_stmt_normalized as (
        select
            project_name
            , task_name
            , log_file
            , user_id
            , line_number
            , step_type
            , trim(
                regexp_replace(
                    regexp_replace(statement, '[\\r\\n]+', ' '),
                    '\\s+', ' '
                )
            ) as stmt_norm
        from src_cleaned_statements
    ),

    ln_connection_info as (
        select
            project_name
            , task_name
            , log_file
            , user_id
            , line_number
            , step_type
            , stmt_norm
            , case
                when regexp_like(stmt_norm, '(?i)\\b(proc\\s+connect\\s+to|connect\\s+to|from\\s+connection\\s+to)\\b') then 1
                else 0
            end as connect_flag
            , case
                when regexp_extract(stmt_norm, '(?i)\\bconnect\\s+to\\s+([A-Za-z_][A-Za-z0-9_]*)', 1) != ''
                then upper(regexp_extract(stmt_norm, '(?i)\\bconnect\\s+to\\s+([A-Za-z_][A-Za-z0-9_]*)', 1))
                else null
            end as connect_type
        from ln_stmt_normalized
        where not startswith(stmt_norm, '+')
    ),

    -- ===========================================================================================
    -- 7. linhagem: targets (saídas)
    -- ===========================================================================================

    -- 7.1 proc sql targets
    ln_tgt_sql_raw as (
        select
            project_name
            , task_name
            , log_file
            , line_number
            , upper(regexp_extract(stmt_norm, '(?i)\\bcreate\\s+table\\s+([A-Za-z0-9_\\.]+)', 1)) as target_table
        from ln_connection_info
        where regexp_like(stmt_norm, '(?i)\\bcreate\\s+table\\b')
        union all
        select
            project_name
            , task_name
            , log_file
            , line_number
            , upper(regexp_extract(stmt_norm, '(?i)\\binsert\\s+into\\s+([A-Za-z0-9_\\.]+)', 1)) as target_table
        from ln_connection_info
        where regexp_like(stmt_norm, '(?i)\\binsert\\s+into\\b')
    ),
    ln_tgt_sql as (
        select distinct 
            project_name
            , task_name
            , log_file
            , line_number
            , target_table
        from ln_tgt_sql_raw
        where 
            target_table is not null
            and target_table != ''
    ),

    -- 7.2 data step targets
    ln_tgt_data_step_raw as (
        select
            project_name
            , task_name
            , log_file
            , line_number
            , upper(regexp_extract(stmt_norm, '(?i)\\bdata\\s*(?:=)?\\s*([A-Za-z0-9_\\.]+)', 1)) as target_table
        from ln_connection_info
        where step_type like 'DATA'
    ),
    ln_tgt_data_step as (
        select distinct project_name, task_name, log_file, line_number, target_table
        from ln_tgt_data_step_raw
        where 
            target_table is not null
            and target_table != ''
    ),

    -- 7.3 proc import targets.
    ln_tgt_proc_import_raw as (
        select
            ln_connection_info.project_name, ln_connection_info.task_name, ln_connection_info.log_file, ln_connection_info.line_number
            , UPPER(REGEXP_EXTRACT(ln_connection_info.stmt_norm, '(?i)\\bout\\s*=\\s*([A-Za-z0-9_\\.]+)', 1)) as target_table
        from ln_connection_info
        left join ln_connection_info ln_connection_info1 
            on ln_connection_info.project_name = ln_connection_info1.project_name 
            and ln_connection_info.task_name = ln_connection_info1.task_name 
            and ln_connection_info.log_file = ln_connection_info1.log_file
            and ln_connection_info.line_number+1 = ln_connection_info1.line_number
        where ln_connection_info.step_type like 'PROC IMPORT%'
    ),
    ln_tgt_proc_import as (
        select distinct project_name, task_name, log_file, line_number, target_table
        from ln_tgt_proc_import_raw
        where 
            target_table is not null 
            and target_table != ''
    ),

    -- 7.4 proc export targets
    ln_tgt_proc_export_raw as (
        select
            ln_connection_info.project_name, ln_connection_info.task_name, ln_connection_info.log_file, ln_connection_info.line_number
            , case
                when regexp_extract(ln_connection_info1.stmt_norm, '(?i)\\boutfile\\s*=\\s*\"([^\"]+)\"', 1) != '' then regexp_extract(ln_connection_info1.stmt_norm, '(?i)\\boutfile\\s*=\\s*\"([^\"]+)\"', 1)
                when regexp_extract(ln_connection_info1.stmt_norm, '(?i)\\boutfile\\s*=\\s*\\\'([^\\\']+)\\\'', 1) != '' then regexp_extract(ln_connection_info1.stmt_norm, '(?i)\\boutfile\\s*=\\s*\\\'([^\\\']+)\\\'', 1)
                else regexp_extract(ln_connection_info1.stmt_norm, '(?i)\\boutfile\\s*=\\s*([^\\s;]+)', 1)
            end as target_table
        from ln_connection_info
        left join ln_connection_info ln_connection_info1
            on ln_connection_info.project_name = ln_connection_info1.project_name 
            and ln_connection_info.task_name = ln_connection_info1.task_name 
            and ln_connection_info.log_file = ln_connection_info1.log_file
            and ln_connection_info.line_number+2 = ln_connection_info1.line_number
        where ln_connection_info.step_type like 'PROC EXPORT%'
    ),
    ln_tgt_proc_export as (
        select distinct project_name, task_name, log_file, line_number, target_table
        from ln_tgt_proc_export_raw
        where 
            target_table is not null 
            and target_table != ''
    ),

    -- 7.5 união dos targets
    ln_union_targets as (
        select 
            'PROC SQL' as target_origin
            , project_name
            , task_name
            , log_file
            , line_number
            , target_table
        from ln_tgt_sql
        union all
        select 
            'DATA' as target_origin
            , project_name
            , task_name
            , log_file
            , line_number
            , target_table
        from ln_tgt_data_step
        union all
        select 
            'PROC IMPORT' as target_origin
            , project_name
            , task_name
            , log_file
            , line_number
            , target_table
        from ln_tgt_proc_import
        union all
        select 
            'PROC EXPORT' as target_origin
            , project_name
            , task_name
            , log_file
            , line_number
            , target_table
        from ln_tgt_proc_export
    ),

    -- ===========================================================================================
    -- 8. linhagem: sources (entradas)
    -- ===========================================================================================

    -- 8.1 proc sql sources
    ln_src_sql as (
        with extracted as (
            select
                s.project_name
                , s.task_name
                , s.log_file
                , s.line_number
                , upper(
                    regexp_replace(
                        regexp_extract(
                            s.stmt_norm
                            , '(?i)\\b(from|join)\\s+([A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?)',
                            2
                        ),
                        '`',
                        ''
                    )
                ) as source_table
            from ln_connection_info s
            where 
                regexp_extract(
                    s.stmt_norm
                    , '(?i)\\b(from|join)\\s+([A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?)'
                    , 2
                ) != ''
        )
        select distinct
            e.project_name
            , e.task_name
            , e.log_file
            , e.line_number
            , e.source_table
        from extracted e
        -- left join ln_src_sql_cte_names w
        --   on  e.project_name <=> w.project_name
        --   and e.task_name    <=> w.task_name
        --   and e.log_file     <=> w.log_file
        --   and e.line_number  <=> w.line_number
        -- where w.cte_name is null or e.source_table != w.cte_name
    ),

    -- -- 8.2 proc import sources
    ln_src_proc_import_raw as (
        select
            ln_connection_info.project_name
            , ln_connection_info.task_name
            , ln_connection_info.log_file
            , ln_connection_info.line_number
            , case
                when regexp_extract(ln_connection_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*\"([^\"]+)\"', 1) != ''
                    then regexp_extract(ln_connection_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*\"([^\"]+)\"', 1)
                when regexp_extract(ln_connection_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*\\\'([^\\\']+)\\\'', 1) != ''
                    then regexp_extract(ln_connection_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*\\\'([^\\\']+)\\\'', 1)
                else regexp_extract(ln_connection_info.stmt_norm, '(?i)\\bdatafile\\s*=\\s*([^\\s;]+)', 1)
            end as source_raw
        from ln_connection_info
        where ln_connection_info.step_type = 'PROC IMPORT'
    ),
    ln_src_proc_import as (
        select
            project_name
            , task_name
            , log_file
            , line_number
            , trim(regexp_replace(source_raw, '\\s+!\\s+', ' ')) as source_table
        from ln_src_proc_import_raw
        where 
            source_raw is not null 
            and source_raw != ''
    ),

    -- 8.3 PROC EXPORT Sources
    ln_src_proc_export_raw as (
        select
            ln_connection_info.project_name
            , ln_connection_info.task_name
            , ln_connection_info.log_file
            , ln_connection_info.line_number
            , upper(regexp_extract(ln_connection_info1.stmt_norm, '(?i)\\bdata\\s*=\\s*([A-Za-z0-9_\\.]+)', 1)) as source_table
        from ln_connection_info
        left join ln_connection_info ln_connection_info1
            on ln_connection_info.project_name = ln_connection_info1.project_name 
            and ln_connection_info.task_name = ln_connection_info1.task_name 
            and ln_connection_info.log_file = ln_connection_info1.log_file
            and ln_connection_info.line_number+1 = ln_connection_info1.line_number
        where ln_connection_info.step_type like 'PROC EXPORT%'
    ),
    ln_src_proc_export as (
        select distinct 
            project_name
            , task_name
            , log_file
            , line_number
            , source_table
        from ln_src_proc_export_raw
        where 
            source_table is not null 
            and source_table != ''
    ),

    ln_src_data_step_raw as (
        select 
            project_name
            , task_name
            , log_file
            , line_number
            , upper(regexp_extract(stmt_norm, '(?i)\\bset\\s+([A-Za-z0-9_\\.]+)', 1)) as source_table
        from ln_connection_info
    ),
    ln_src_data_step as (
        select distinct 
            project_name
            , task_name
            , log_file
            , line_number
            , source_table
        from ln_src_data_step_raw
        where 
            source_table is not null 
            and source_table != ''
    ),

    -- 8.5 data step sources (infile)
    ln_src_infile_raw as (
        select
            ln_union_targets.project_name
            , ln_union_targets.task_name
            , ln_union_targets.log_file
            , ln_union_targets.line_number
            , case
                when regexp_extract(ln_connection_info.stmt_norm, '(?i)\\binfile\\s+\"([^\"]+)\"', 1) != '' 
                    then regexp_extract(ln_connection_info.stmt_norm, '(?i)\\binfile\\s+\"([^\"]+)\"', 1)
                when regexp_extract(ln_connection_info.stmt_norm, '(?i)\\binfile\\s+\\\'([^\\\']+)\\\'', 1) != '' 
                    then regexp_extract(ln_connection_info.stmt_norm, '(?i)\\binfile\\s+\\\'([^\\\']+)\\\'', 1)
                else regexp_extract(ln_connection_info.stmt_norm, '(?i)\\binfile\\s+([^\\s;]+)', 1)
            end as source_raw
        from ln_union_targets
        join ln_connection_info
        on  ln_union_targets.project_name <=> ln_connection_info.project_name
        and ln_union_targets.task_name    <=> ln_connection_info.task_name
        and ln_union_targets.log_file     <=> ln_connection_info.log_file
        and ln_union_targets.line_number  <=> ln_connection_info.line_number
        where ln_union_targets.target_origin = 'DATA'
        and regexp_like(ln_connection_info.stmt_norm, '(?i)\\binfile\\b')
    ),
    ln_src_infile as (
        select 
            project_name
            , task_name
            , log_file
            , line_number
            , source_raw as source_table
        from ln_src_infile_raw
        where 
            source_raw is not null 
            and source_raw != ''
    ),

    -- 8.6 união dos sources
    ln_union_sources as (
        select 
            project_name
            , task_name
            , log_file
            , line_number
            , source_table
        from ln_src_sql
        union all
        select 
            project_name
            , task_name
            , log_file
            , line_number
            , source_table
        from ln_src_data_step
        union all
        select 
            project_name
            , task_name
            , log_file
            , line_number
            , source_table
        from ln_src_proc_import
        union all
        select 
            project_name
            , task_name
            , log_file
            , line_number
            , source_table
        from ln_src_infile
        union all
        select 
            project_name
            , task_name
            , log_file
            , line_number
            , source_table
        from ln_src_proc_export
    ),

    -- agregação de sources por linha
    ln_agg_sources as (
        select
            project_name
            , concat_ws(', ', sort_array(collect_set(source_table))) as source_table
            , count(distinct source_table)
        from ln_union_sources
        group by project_name
    ),

    -- agregação de sources por linha
    ln_agg_targets as (
        select
            project_name
            , concat_ws(', ', sort_array(collect_set(target_table))) as target_table
        from ln_union_targets
        group by project_name
    ),

    -- ===========================================================================================
    -- 9. consolidação final
    -- ===========================================================================================

    fin_distinct_project as (
        select distinct 
            sha2(
                concat_ws(
                        '||'
                        , coalesce(cast(src_cleaned_statements.project_name as string), '')
                        )
                , 256
            ) as project_id
            , project_name
        from src_cleaned_statements
    ),

    fin_project_type_statement as (
        select 
            project_name
            , count(distinct log_file) as log_file_number
            , count(distinct task_name) as task_number
            , count(step_type) filter (where step_type = 'PROC SQL') as count_sql_blocks
            , count(step_type) filter (where step_type = 'PROC FCMP' or step_type = 'PROC PYTHON') as count_python_blocks
            , count(step_type) filter (where step_type = 'DATA') as count_sas_blocks
        from src_cleaned_statements
        where step_type is not null
        group by project_name
    ),

    fin_lineage_details as (
        select
            fin_distinct_project.project_id
            , fin_distinct_project.project_name
            , fin_project_type_statement.log_file_number
            , fin_project_type_statement.task_number
            , ln_agg_targets.target_table
            , ln_agg_sources.source_table
            , fin_project_type_statement.count_sql_blocks
            , fin_project_type_statement.count_python_blocks
            , fin_project_type_statement.count_sas_blocks
        from fin_distinct_project
        left join fin_project_type_statement 
            on fin_distinct_project.project_name = fin_project_type_statement.project_name
        left join ln_agg_targets
            on fin_distinct_project.project_name = ln_agg_targets.project_name
        left join ln_agg_sources
            on fin_distinct_project.project_name = ln_agg_sources.project_name

    ),

    final_output_joined as (
    select
        fin_lineage_details.project_id
        , fin_lineage_details.project_name
        , fin_lineage_details.log_file_number
        , fin_lineage_details.task_number
        , fin_lineage_details.target_table
        , fin_lineage_details.source_table
        , fin_lineage_details.count_sql_blocks
        , fin_lineage_details.count_python_blocks
        , fin_lineage_details.count_sas_blocks
        , agg_project_variables.variables_used
        , agg_project_classification.process_type
    from fin_lineage_details
    left join agg_project_variables
        on fin_lineage_details.project_name = agg_project_variables.project_name
    left join agg_project_classification
        on fin_lineage_details.project_name = agg_project_classification.project_name
    )

select * 
from final_output_joined