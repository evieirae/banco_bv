with 
  stg_users as (
    select 
      cast(login as string) as login
      , cast("Área" as string) as area
      , cast("Diretoria" as string) as directorship
    from {{ source('bv_migration_sas', 'user_v2') }}
    )

select *
from stg_users
