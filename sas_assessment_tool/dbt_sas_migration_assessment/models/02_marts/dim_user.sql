with
  stg_users as (
    select
      login
      , area
      , directorship
    from {{ ref('stg_user') }}
  )

select
  login
  , area
  , directorship
from stg_users
