# Exemplos canónicos — SAS → dbt (BigQuery Standard SQL)

Este ficheiro é **referência** para o AGENTE 1 (draft). O SQL segue **`01_sas_to_dbt.mdc`**: BigQuery Standard SQL, **minúsculas**, **leading commas**, **CTEs** com última CTE `final`, **sem** `CREATE TABLE` (modelo dbt).

**Fonte:** use `{{ source('payer', 'members') }}` apenas se o `MIGRATION_SPEC.md` / projeto dbt definir essa `source`; caso contrário, alinhar ao contrato (`source`/`ref`) ou deixar comentário `-- [TODO]`.

---

## Exemplo: `DATA` + `MDY` + `IF/ELSE` + `INTCK` + `KEEP` → modelo dbt (flow-only)

### SAS (original)

```sas
data member_ages;
    set payer.members;

    age = floor((mdy(12, 31, measurement_year) - birth_date) / 365.25);

    if age < 18 then age_group = 'CHILD';
    else if age < 65 then age_group = 'ADULT';
    else age_group = 'SENIOR';

    months_enrolled = intck('MONTH', enrollment_start, enrollment_end);

    keep member_id plan_type age age_group months_enrolled;
run;
```

### Notas de tradução (SAS → BigQuery)

- **`mdy(12, 31, measurement_year)`** → **`date(measurement_year, 12, 31)`** (data de fim de ano alinhada ao ano de medição).
- **Idade em anos (aprox. 365.25):** `floor(date_diff(<fim>, birth_date, day) / 365.25)` — ordem dos argumentos de `date_diff` em BigQuery: **`date_diff(end_date, start_date, day)`**.
- **`if / else if / else` em colunas** → **`case when ... end`**.
- **`intck('MONTH', start, end)`** → **`date_diff(enrollment_end, enrollment_start, month)`** em muitos casos. **Atenção:** limites de mês e inclusão podem diferir do SAS; validar se o resultado for contrato crítico (ex.: faturação por mês civil).

### SQL dbt — BigQuery (ficheiro sugerido: `03_member_ages.sql` em `draft_models/<egp>/models/`)

```sql
{{ config(materialized='table') }}

with cte_payer_members as (
    select
        member_id
        , plan_type
        , birth_date
        , measurement_year
        , enrollment_start
        , enrollment_end
    from {{ source('payer', 'members') }}
)

, cte_age_calc as (
    select
        member_id
        , plan_type
        , birth_date
        , measurement_year
        , enrollment_start
        , enrollment_end
        , floor(
            date_diff(date(measurement_year, 12, 31), birth_date, day) / 365.25
        ) as age
    from cte_payer_members
)

, final as (
    select
        member_id
        , plan_type
        , age
        , case
            when age < 18 then 'child'
            when age < 65 then 'adult'
            else 'senior'
        end as age_group
        , date_diff(enrollment_end, enrollment_start, month) as months_enrolled
    from cte_age_calc
)

select * from final
```

Valores de `age_group` estão em **minúsculas** para consistência com o style guide; ajuste se o consumidor exigir maiúsculas.

---

## Exemplo: `PROC MEANS` + `CLASS` + `OUTPUT OUT=` → agregação `GROUP BY`

### SAS (original)

```sas
proc means data=gold.claims noprint;
    class member_id;
    var paid_amount;
    output out=claim_summary
        sum(paid_amount)=total_paid
        mean(paid_amount)=avg_paid
        n(*)=claim_count;
run;
```

### SQL dbt — BigQuery

Equivalente: agregar por `member_id`. Trocar `gold.claims` por `{{ source('gold', 'claims') }}` (ou `ref`) conforme o contrato do projeto.

```sql
{{ config(materialized='table') }}

with cte_claims as (
    select
        member_id
        , paid_amount
    from {{ source('gold', 'claims') }}
)

, final as (
    select
        member_id
        , sum(paid_amount) as total_paid
        , avg(paid_amount) as avg_paid
        , count(*) as claim_count
    from cte_claims
    group by member_id
)

select * from final
```

---

## Exemplo: `PROC SORT` + `KEEP` + `BY` → projeção ordenada (sem `nodupkey`)

### SAS (original)

```sas
proc sort
    data=work.ba_tamanhomunic(keep=comple_munic contrato_cyber)
    out=work.sorttemptablesorted;
    by contrato_cyber;
run;
```

### SQL dbt — BigQuery

`PROC SORT` materializa tabela ordenada; em dbt costuma ser **CTE** + `order by` só onde necessário (consumo), ou modelo `table` se precisares persistir. `WORK.*` → `ref` a um modelo upstream (nome ilustrativo).

```sql
{{ config(materialized='ephemeral') }}

with cte_ba_tamanhomunic as (
    select
        comple_munic
        , contrato_cyber
    from {{ ref('01_ba_tamanhomunic') }}
)

, final as (
    select
        comple_munic
        , contrato_cyber
    from cte_ba_tamanhomunic
    order by contrato_cyber
)

select * from final
```

---

## Exemplo: `DATA _NULL_` + `CALL SYMPUT` (data) → `{% set var_* %}` (dbt)

### SAS (original)

```sas
data _null_;
    call symput('DT_REF_2', put(today()-1, yymmdd10.));
run;
```

### SQL dbt — BigQuery

**Ordem** (regra `01_sas_to_dbt.mdc` §1.3): `{% set var_* %}` **antes** de `{{ config(...) }}`.

Opção A — Jinja com `datetime` (útil quando precisas do mesmo formato que no SAS):

```sql
{% set var_dt_ref_2 = (modules.datetime.date.today() - modules.datetime.timedelta(days=1)).strftime('%Y-%m-%d') %}

{{ config(materialized='table') }}

with final as (
    select *
    from {{ ref('sua_tabela') }}
    where data_processamento = date '{{ var_dt_ref_2 }}'
)

select * from final
```

Opção B — só BigQuery (sem `datetime` em Jinja): usar `date_sub(current_date(), interval 1 day)` no `where` / numa CTE, ou expor como `var()` do `dbt_project` conforme política do projeto.

---

## Exemplo: `%let` → `{% set var_* %}`

### SAS (original)

```sas
%let dt_ref_base='2026-02-05';
```

### SQL dbt — BigQuery

```sql
{% set var_dt_ref_base = '2026-02-05' %}

{{ config(materialized='table') }}

with final as (
    select *
    from {{ ref('sua_tabela') }}
    where data_referencia = date '{{ var_dt_ref_base }}'
)

select * from final
```

---

## Exemplo: `PROC SORT` + `nodupkey` → deduplicação por chave (BigQuery `qualify`)

### SAS (original)

```sas
proc sort data=solar_reabilitar_serasa nodupkey out=solar_reabilitar_serasa_ok;
    by sk_batimento_solar dt_processamento;
run;
```

### SQL dbt — BigQuery

Em BigQuery, **`qualify row_number() ... = 1`** costuma ser mais claro que subquery com `where _row_num_ = 1`. `ref`/`source` conforme o grafo real do EGP.

```sql
{{ config(materialized='table') }}

with cte_solar_reabilitar_serasa as (
    select * from {{ ref('solar_reabilitar_serasa') }}
)

, final as (
    select *
    from cte_solar_reabilitar_serasa
    qualify row_number() over (
        partition by sk_batimento_solar, dt_processamento
        order by sk_batimento_solar, dt_processamento
    ) = 1
)

select * from final
```

**Nota:** `order by` dentro de `over` define qual linha “ganha” em empates; alinha à regra de negócio se houver várias linhas idênticas na chave. Em tabelas materializadas, **não** contes com `order by` global no resultado físico — documenta ordenação no consumo (`order by` na query analítica).

---

## Exemplos adicionais (lado a lado — padrões comuns nos `text_egps/`)

Formato: **SAS** → **modelo dbt em BigQuery** (CTEs, `final`, leading commas). Ajustar `ref`/`source` ao contrato do EGP.

### `PROC SQL` — `create table` + `group by`

**SAS**

```sas
proc sql;
    create table work.resumo as
        select
            member_id
            , sum(amount) as total
        from work.claims
        group by member_id;
quit;
```

**dbt / BigQuery**

```sql
{{ config(materialized='table') }}

with cte_claims as (
    select
        member_id
        , amount
    from {{ ref('01_claims') }}
)

, final as (
    select
        member_id
        , sum(amount) as total
    from cte_claims
    group by member_id
)

select * from final
```

---

### Passthrough — `CONNECTION TO` / SQL nativo dentro do SAS

**SAS (ilustrativo)**

```sas
proc sql;
    connect to perm (...);
    create table work.x as
        select * from connection to perm (
            select a, b from schema.t where dt = current_date() - 1
        );
    disconnect from perm;
quit;
```

**dbt / BigQuery**

Reescrever o **interior** do passthrough em **BigQuery Standard SQL**; expor como modelo que lê `source`/`ref` (sem deixar funções/dialeto do motor intermédio no SQL final).

```sql
{{ config(materialized='table') }}

with final as (
    select
        a
        , b
    from {{ source('schema', 't') }}
    where dt = date_sub(current_date(), interval 1 day)
)

select * from final
```

---

### `PROC TRANSPOSE` — long → wide (agregação condicional)

**SAS**

```sas
proc transpose data=work.long out=work.wide;
    by id;
    id metric;
    var value;
run;
```

**dbt / BigQuery**

```sql
{{ config(materialized='table') }}

with cte_long as (
    select
        id
        , metric
        , value
    from {{ ref('01_long') }}
)

, final as (
    select
        id
        , sum(case when metric = 'a' then value end) as a
        , sum(case when metric = 'b' then value end) as b
    from cte_long
    group by id
)

select * from final
```

*(Muitas colunas dinâmicas: documentar estratégia no `MIGRATION_SPEC.md`.)*

---

### `PROC EXPORT` + macro em nome (`&DT_REF`) — entrega vs modelo

**SAS**

```sas
%let dt_ref = 2026-02-05;

proc export data=work.out
    outfile=".../arq_&dt_ref..csv";
run;
```

**dbt / BigQuery**

O **equivalente lógico** ao dataset que alimentava o export é um modelo `marts` (ver `01_sas_to_dbt.mdc` §2.1). O ficheiro `.csv` em si costuma sair de **orquestração fora do dbt**.

```sql
{% set var_dt_ref = '2026-02-05' %}

{{ config(materialized='table') }}

with final as (
    select *
    from {{ ref('01_out') }}
    where dt_ref = date '{{ var_dt_ref }}'
)

select * from final
```

---

### `RETAIN` + `BY` — soma acumulada por `id`

**SAS**

```sas
data t2;
    set t1;
    by id;
    retain cum 0;
    if first.id then cum = 0;
    cum = cum + amount;
run;
```

**dbt / BigQuery**

```sql
{{ config(materialized='table') }}

with cte_ordered as (
    select
        id
        , amount
        , dt
    from {{ ref('01_t1') }}
)

, final as (
    select
        id
        , dt
        , amount
        , sum(amount) over (
            partition by id
            order by dt
            rows between unbounded preceding and current row
        ) as cum
    from cte_ordered
)

select * from final
```

---

### `INTCK('day', ...)` — diferença em dias

**SAS**

```sas
intck('day', datepart(d1), datepart(d2))
```

**dbt / BigQuery**

```sql
date_diff(date(d2), date(d1), day)
```

**Nota:** se `d1`/`d2` forem `timestamp`, normalizar com `date()` ou `datetime_trunc(..., day)` conforme a regra de negócio.

---

## Exemplo: `DATA` + `DO WHILE` + `LENGTH` + `OUTPUT` em loop — expandir linhas (tally)

### SAS (original)

```sas
data endertamanho (keep= contrato_cyber n comple_ender);
    set base_aux_cadastro;
    tamanhoender = length(ender);
    n = 0;
    do while (n <= (45 - tamanhoender));
        comple_ender = '.';
        n = n + 1;
        output;
    end;
run;
```

### Notas

- O loop emite **uma linha por iteração**; o contador `n` no SAS incrementa **antes** do `output` (no excerto acima: `comple_ender`, depois `n = n + 1`, depois `output` → primeira linha já leva `n = 1`).
- Número de linhas por registo de origem: **`45 - tamanhoender + 1`** quando `tamanhoender <= 45`; se `tamanhoender > 45`, o SAS **não** entra no loop (0 linhas). No SQL abaixo usa-se `generate_array` só quando esse comprimento é `>= 1`.
- Em **BigQuery**, prefira **`generate_array` + `unnest`** a `WITH RECURSIVE` (evita limites de profundidade e costuma ser mais claro).

### SQL dbt — BigQuery

`base_aux_cadastro` → `{{ ref(...) }}` conforme o grafo do EGP. `length` / `rtrim` / `coalesce` alinham `ender` nulo ou vazio ao comportamento típico do SAS.

```sql
{{ config(materialized='table') }}

with cte_base as (
    select
        contrato_cyber
        , ender
        , length(rtrim(coalesce(ender, ''))) as tamanhoender
    from {{ ref('base_aux_cadastro') }}
)

, cte_expanded as (
    select
        b.contrato_cyber
        , pos as n
        , '.' as comple_ender
    from cte_base b
    , unnest(
        if(
            45 - b.tamanhoender + 1 >= 1,
            generate_array(1, 45 - b.tamanhoender + 1),
            []
        )
    ) as pos
)

, final as (
    select
        contrato_cyber
        , n
        , comple_ender
    from cte_expanded
)

select * from final
```

### Variante (SQL genérico com `WITH RECURSIVE`)

Se o motor alvo suportar **CTE recursiva** para gerar `1..46`, o padrão abaixo reproduz a ideia da “tally table”; em **BigQuery** para este caso use preferencialmente o bloco com `generate_array` acima.

```sql
with recursive sequence as (
    select 1 as n
    union all
    select n + 1
    from sequence
    where n < 46
)
select
    b.contrato_cyber
    , s.n
    , '.' as comple_ender
from base_aux_cadastro b
inner join sequence s
    on s.n <= (45 - (
        case
            when b.ender is null or b.ender = '' then 1
            else length(rtrim(b.ender))
        end
    ) + 1)
```
