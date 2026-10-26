{% macro get_uc_tables(relation) %}
  {# 
    Macro customizada para substituir a macro padrão do dbt-databricks
    que usa system.information_schema.tables (requer permissões especiais).
    Esta versão usa SHOW TABLES que não requer acesso ao catálogo 'system'.
  #}
  {%- set database = relation.database -%}
  {%- set schema = relation.schema -%}
  
  {%- set query -%}
    SHOW TABLES IN {{ adapter.quote(database) }}.{{ adapter.quote(schema) }}
  {%- endset -%}
  
  {%- set results = run_query(query) -%}
  
  {%- if execute -%}
    {%- set tables = [] -%}
    {%- for row in results -%}
      {# SHOW TABLES retorna: database, tableName, isTemporary #}
      {%- set table_name = row[1] if row|length > 1 else row[0] -%}
      {%- set table_info = {
        'table_name': table_name,
        'table_type': 'table',
        'file_format': 'delta',
        'table_owner': ''
      } -%}
      {%- set _ = tables.append(table_info) -%}
    {%- endfor -%}
    {{ return(tables) }}
  {%- else -%}
    {{ return([]) }}
  {%- endif -%}
{% endmacro %}

