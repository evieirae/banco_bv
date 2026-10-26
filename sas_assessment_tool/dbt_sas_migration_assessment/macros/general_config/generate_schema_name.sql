{#
    Macro: generate_schema_name
    
    This macro determines the schema name for dbt models based on the target environment
    and custom schema configuration. It overrides dbt's default schema generation behavior.
    
    Args:
        custom_schema_name (str, optional): The custom schema name specified in model configs.
            If provided and in a production environment, this value will be used.
        node (dict): The node context provided by dbt, containing information about the
            current model being processed.
        
    Returns:
        str: The schema name to use for the model.
        
    Behavior:
        - In production ('prod') or monitoring environments, uses the custom schema name
          if one is provided.
        - In all other environments (dev, test, etc.), uses the target schema regardless
          of any custom schema configuration.
        - Trims whitespace from custom schema names to prevent errors.
        
    Example:
        In a model config:
        ```yaml
        models:
          - name: my_model
            config:
              schema: custom_schema
        ```
        
        In prod: Will use "custom_schema"
        In dev: Will use the target schema (e.g., "dbt_jdoe")
#}

{% macro generate_schema_name(custom_schema_name, node) -%}
    {# Set the default schema from the target configuration #}
    {%- set default_schema = target.schema -%}
    
    {# 
        In production or monitoring environments, use the custom schema if provided.
        Otherwise, fall back to the default schema from the target configuration.
    #}
    {%- if target.name in ('prod', 'monitoring') and custom_schema_name is not none -%}
        {# Trim whitespace to prevent schema name errors #}
        {{ custom_schema_name | trim }}
    {%- else -%}
        {{ default_schema }}
    {%- endif -%}
{%- endmacro %}