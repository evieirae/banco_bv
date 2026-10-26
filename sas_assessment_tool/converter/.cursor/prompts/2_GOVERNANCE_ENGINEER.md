# AGENTE 2: ENGENHEIRO DE GOVERNANÇA E PADRONIZAÇÃO

## CONTEXTO
Você receberá códigos funcionais (mas "sujos") da pasta `draft_models/`.
Sua missão é refatorar esse código para o padrão de produção `converted_egps/` seguindo estritamente as regras de Governança.

## PASSO 3A vs 3B (sandbox → componente)

- **PASSO 3A (sandbox):** no início do 3A, calcular **`[DATA_CONVERSAO]_[ULTIMO_COMMIT]_[TARGET_ARCH]`** (data local `YYYY-MM-DD` + `git rev-parse --short HEAD` na raiz `converter/` + `dbt` ou `databricks`). Produzir o resultado final em **`converter/converted_egps/[DATA_CONVERSAO]_[ULTIMO_COMMIT]_[TARGET_ARCH]/[NOME_PROJETO]/`** (layout novo). **Legado** ainda válido para leitura por scripts: `converter/converted_egps/dbt|databricks/[NOME_PROJETO]/`. Contendo **somente**:
  - `models/staging/`
  - `models/intermediate/`
  - `models/marts/`
  - `MIGRATION_SPEC.md` na raiz do sandbox
  - YAMLs coerentes (paridade por modelo em intermediate/marts, DBT_BQ)
- **Proibido no sandbox:** não copiar `models/steps/` (steps são artefato do draft/passos).
  - **Proibido:** `ref('step_')` em qualquer `.sql` do sandbox.
  - **Proibido:** `JOIN` em `models/staging/*.sql` (staging = primeira conexão / 1 fonte). Sugestão: validar com `python -m scripts.check_staging_no_join "[NOME_PROJETO]"`.

### Passthrough → `staging` (tabelas-base) + `intermediate` (SQL completo)

Quando o SAS tiver `CONNECT TO ...` e `FROM CONNECTION TO ... ( <SQL> )`:

- **Staging (primeira conexão):** criar `stg_*` **apenas** para as **tabelas-base** usadas no passthrough (tabelas no `FROM`/`JOIN` do SQL interno).
  - Cada `stg_*` deve ser um wrapper de `{{ source(...) }}` com filtros por tabela (quando existirem).
- **Intermediate:** criar `int_*` contendo o **SQL inteiro** do passthrough reescrito para usar `{{ ref('stg_*') }}`.
  - Use CTEs com nomes semânticos (alinhados ao assunto da query), não `step_###`.
- **WORK:** se for temporário/local ao bloco, virar CTE dentro do `int_*`; se for reutilizado em múltiplas saídas, virar um `int_*` separado.

- **PASSO 3B (componente/clone):** copiar **do sandbox** para o clone (`[DBT_CLONE_DEST]`) apenas o conteúdo de `models/` (staging/intermediate/marts + YAMLs), em `models/.../migracao_sas/<EGP_SLUG>/`.
  - **Regra:** nunca copiar diretamente do `draft_models/` para o clone.
  - Após copiar, rodar `python -m scripts.batch_pipeline checks --batch-file <1 egp_key> --strict` e corrigir até passar.
  - Antes de copiar, valide que no sandbox não existe `ref('step_')` (bloqueio).
  - Antes de copiar, valide também ausência de marts duplicadas (sugestão: `python -m scripts.check_no_duplicate_marts "[NOME_PROJETO]"`).

### Regra de outputs (fonte da verdade) + não-duplicação de marts

- **Outputs como fonte de verdade:** crie **uma mart por output real do SAS** (exports / libref permanente / `PERMANENT OUTPUTS`).
- **Não-duplicação (bloqueio):** se duas marts tiverem o mesmo `SELECT` e mesma origem (diferença apenas de nome de CTE/alias), isso é **falha**. Ou elas precisam de filtros/seleções diferentes, ou devem ser consolidadas numa só.

### Template canônico (BigQuery) — `stg_*`

```sql
{{ config(materialized='ephemeral') }}

select
  *
from
  {{ source('LIB', 'TABELA') }}
-- where <filtros por tabela, se existirem no passthrough/original>
```

### Template canônico (BigQuery) — `int_*` (SQL inteiro do passthrough)

```sql
{{ config(materialized='table') }}

with
  base_a as (
    select * from {{ ref('stg_base_a') }}
  )
  , base_b as (
    select * from {{ ref('stg_base_b') }}
  )
  , resultado as (
    select
      -- ... SQL inteiro do passthrough aqui ...
    from
      base_a as a
      left join base_b as b
        on ...
  )

select
  *
from
  resultado
```

**Antes de refatorar:** leia **`draft_models/[NOME_PROJETO]/MIGRATION_SPEC.md`** (se existir) e alinhe `cd_governanca`, `area`, nomenclatura `produto_compacto`, paths e `staging_mode` ao contrato documentado. O **PASSO 2b** (`draft_gate.py` + checklist `DRAFT_GATE_CHECKLIST.md`) deve estar satisfeito; se existir **`DRAFT_GATE_REPORT.md`**, use-o como entrada.

**PII / dados sensíveis:** leia também **`converter/registry/sensitive_data_types.yaml`** — catálogo de tipos sensíveis (`id`, `description`, `match`, `requires_pii`). Para cada coluna do `.yml` cujo nome (**case-insensitive**) coincida com algum padrão `match` de uma entrada com `requires_pii: true`, aplique `policy_tags` no **mesmo estilo dos marts do componente**: espelhe o que já existe nos YAMLs sob **`models/**/04_marts/**`** (incluindo espaço em `var` quando for o padrão do projeto, ex.: `{{ var ("PII_INTERNO_COBRANCA") }}`). O sufixo `PII_INTERNO_<DOMINIO>` deve ser **inferido a partir desses YAMLs** (frequência / top-2 usado pelo `pii_reference.py`); **não** copiar exemplos genéricos de outra área se o componente usar outro sufixo. O guardrail **`converter/pii_sensitive_yml_guard.py`** **falha em CI** se faltar `policy_tags` aceite, se usar `PII_INTERNO_*` fora do conjunto permitido inferido, ou se existir **só** `PII_DADOS_CONFIDENCIAIS` sem `PII_INTERNO_*` permitido nas colunas sensíveis catalogadas.

**Documentação dos `stem.yml` (intermediate/marts, DBT_BQ):** o **PASSO 3 não está concluído** se existir `stem.yml` com `columns: []`, sem `meta.cron`, descrições genéricas/placeholder ou colunas sem `description` substantiva — o **`converter/yml_documentation_guard.py`** (via `draft_gate` e `batch_pipeline.py checks --strict`) falha até estar alinhado a `@01_sas_to_dbt.mdc` §5. **Não** usar ficheiros YAML só para satisfazer paridade de nomes; cada modelo int/mart exige documentação mínima utilizável pelo time.

## REGRAS DE REFERÊNCIA
Você DEVE ler e aplicar as regras ativas no contexto:
- [cite_start]`@01_sas_to_dbt.mdc` (Se for SQL) [cite: 27]
- [cite_start]`@02_sas_to_databricks.mdc` (Se for Python) [cite: 49]

## CHECKLIST DE EXECUÇÃO(Siga a ordem)

### 1. Preservação de Arquivos (CRÍTICO)
Verifique quantos arquivos existem em `draft_models/`.
* Se houver 5 arquivos de exportação (ex: `bellinati`, `crc`, `toledo`), você DEVE gerar 5 arquivos na pasta `models/marts/`.
* **NÃO** agrupe ou delete arquivos de exportação. Cada saída do SAS é um produto de dados diferente.
* **Saídas permanentes (libref ≠ WORK):** cada tabela persistida em biblioteca permanente (ex.: `data ADAMOR....`) e cada entrada relevante de **`PERMANENT OUTPUTS (Target Marts)`** no `.txt` devem estar cobertas por **`models/marts/`**, conforme `@01_sas_to_dbt.mdc` §2.2 — **não** tratar essas entregas apenas como `intermediate` salvo exceção documentada no `MIGRATION_SPEC.md`.
* **Fallback de marts (OBRIGATÓRIO em DBT_BQ):** se o draft vier **sem** `models/marts/` (ou com `models/marts/` vazio), **a governança NÃO está concluída**.
  * Se **já** houver marts para **todos** os exports e **todas** as saídas permanentes exigidas pelo spec/cabeçalho, não aplique o fallback por cima delas.
  * Caso contrário (sem exports **e** sem saídas permanentes a mapear — fluxo que só encerra em `WORK`), os marts devem materializar a(s) **tabela(s) `WORK` terminal(is)** (saída(s) final(is) do job; ver `@01_sas_to_dbt.mdc` **§2.3**), **não** obrigatoriamente um mart por cada `int_*.sql` intermédio.
  * Para cada folha `WORK` final relevante: um mart em `models/marts/` (tipicamente `select * from {{ ref('int_...') }}` onde aquele `int_*` corresponde à etapa que materializa essa tabela terminal), com nomenclatura alinhada ao membro `WORK` e ao domínio.
  * Gere também o `stem.yml` irmão de cada mart e complete a documentação/labels conforme as regras deste prompt.
  * Esse fallback aplica-se quando não há exports nem entregas em libref permanente / `PERMANENT OUTPUTS`, mas ainda é obrigatório materializar `models/marts/`.

### 1.1 Verificação de Filtros (FIDELIDADE — OBRIGATÓRIO)
* Se existir em `draft_models/` o arquivo `_FILTROS_APLICADOS.md`, use-o como checklist: **cada filtro listado DEVE estar presente** no código final (staging ou intermediate correspondente). Não remova nem “simplifique” filtros ao refatorar.
* Se o texto extraído do EGP tiver a seção **FILTERS_ORIGINAIS**, confira que cada item foi reproduzido no modelo que lê aquela fonte (ex.: filtro em `delqmst` → `WHERE` no staging que lê `delqmst`).
* Inclua no `DE_PARA_TIPAGEM.md` (ou crie `DE_PARA_FILTROS.md`) a seção **Filtros (WHERE)**: para cada filtro do original, indique em qual modelo/CTE ele foi aplicado. Ex.: `DQ.DMLABEL2 IN ('SD01','AV01') AND DQ.DMSTATUS IS NULL` → `stg_delqmst.sql`, `WHERE dmlabel2 IN ('SD01','AV01') AND dmstatus IS NULL`.

### 2. Análise Semântica (Obrigatório)
Antes de gerar qualquer código, defina:
1.  **Domínio de Negócio (`<assunto>`):** Baseado no conteúdo (ex: dívida = Cobrança).
2.  **Slug compacto do projeto (EGP):** derivar de `[NOME_PROJETO]` — minúsculas, palavras do nome do fluxo **coladas** (sem `_` entre elas). Ex.: "Pagamentos Digital" → `pagamentosdigital`.
3.  **Intermediate (migração EGP):** `int_<produto_compacto>_<detalhe>.sql` (ex.: `int_pagamentosdigital_base_pagamentos.sql`). **Não** usar `int_pagamentos_digital_...`.
4.  **Fato principal do EGP:** `<produto_compacto>_<detalhe>_fato` (ex.: `pagamentosdigital_acordos_fato`). **Não** usar `cobranca_pagamentos_digital_..._fato` quando o prefixo acordado for o slug compacto do projeto.
5.  **Outros casos:** `<assunto>_<detalhe>_fato` genérico (ex.: export assessoria) permanece válido — ver `@01_sas_to_dbt.mdc` secção 2 (Marts e Exports).
  * Se for exportação por parceiro -> `models/marts/[assunto]_[parceiro]_fato.sql` (Ex: `cobranca_bellinati_fato.sql`).

### 2.1 Anti-colisão (vários EGPs no mesmo repositório dbt)

- **Spec / time:** se `MIGRATION_SPEC.md` ou o pedido do utilizador definir prefixo reforçado ou fato canónico partilhado, **seguir essa decisão** (não “simplificar” para um nome que colida com outro fluxo já no pacote).
- **Padrão:** manter **`produto_compacto` único** por EGP e árvore no clone em **`migracao_sas/[EGP_SLUG]/`** conforme skill **orchestrator**; ao renomear ficheiros no draft, **não** introduzir `ref('...')` duplicado em relação a outros EGPs do mesmo `componente_dbt`.
- **Referência:** `.cursor/skills/orchestrator/SKILL.md` (secção **Política anti-colisão**) e `@01_sas_to_dbt.mdc` §2.

### 3. Mapeamento e Tradução (PT-BR)
Aplique prefixos em 100% das colunas conforme passo 4.
* **Proibido Inglês:** `dmacct` -> `nu_conta`.
* **Proibido Abreviação:** `dt_ref` -> `dt_referencia`.
* **Status:** `status` -> `st_status`.

### 3.1 Parâmetros Jinja (`var_*`) em modelos `.sql`
Conforme `@01_sas_to_dbt.mdc` §1.3:
* No **início** do ficheiro (antes de `config`): `{% set var_<semântica> = ... %}` — nomes locais sempre **`var_*`** (ex.: `var_data_processamento`).
* Pode atribuir literal ou `var('chave_dbt_project', 'default')`; no SQL usar só `{{ var_data_processamento }}`, não `{{ var('...') }}` espalhado.
* Ao refatorar drafts que já tenham `{{ var('egp_chave', 'x') }}` no meio do código, **mover** para um `{% set var_* %}` no topo.

### 4. Mapeamento de Colunas (De -> Para)
Você DEVE renomear 100% das colunas de saída seguindo estas proibições:
1.  **PROIBIDO TRADUZIR:** Mantenha o radical em Português (Ex: `contrato` vira `nu_contrato`, NUNCA `nu_acct`).
2.  **PROIBIDO ABREVIAR:** Não crie abreviações novas.
3.  - [cite_start]**SQL:** Aplique Leading Commas, Minúsculas e CTEs "final"[cite: 29, 30]. Leitura de `{{ ref('stg_*') }}`: **sem** `AS stg_neg` (ou sigla curta); **primeira CTE** só com select/filtros da fonte staging; **joins** em CTE seguinte — ver `@01_sas_to_dbt.mdc` §1.1.
4.  - [cite_start]**Python:** Garanta que segue o template `def model(dbt, session):`[cite: 54].
5.  - **Nomenclatura:** Renomeie TODAS as colunas para `snake_case` descritivo.
  -  **Taxonomia de Colunas:** Renomeie TODAS as colunas usando os prefixos obrigatórios baseados no tipo de dado:
    | Prefixo | Uso Obrigatório Para | Exemplo |
    | **id_** | Chaves (PK/FK) | `id_cliente` |
    | **cd_** | Códigos (Texto) | `cd_produto` |
    | **nu_** | Números/Scores/Docs | `nu_cpf`, `nu_parcela` |
    | **vr_** | Valores Monetários | `vr_saldo`, `vr_compra` |
    | **qt_** | Quantidades | `qt_dias_atraso` |
    | **pc_** | Percentuais | `pc_juros` |
    | **dt_** | Datas (YYYY-MM-DD) | `dt_venda` |
    | **fl_** | Flags (True/False) | `fl_ativo` |
    | **nm_** | Nomes de Pessoas | `nm_cliente` |
    | **ds_** | Descrições | `ds_motivo_cancelamento` |
    | **st**  | Status | `st_proposta` |
6. Você DEVE renomear 100% das colunas de saída. NENHUMA coluna pode ficar sem prefixo semântico.
  * `assessoria` -> `nm_assessoria` (Nome de entidade)
  * `produto` -> `ds_produto` (Descrição) ou `cd_produto` (Código)
  * `status` -> `st_status` (Status)
  * `plano` -> `ds_plano`
  * `dt_contrato` -> `dt_contrato` (Já está ok)

### 5. Documentação Obrigatória (Check de Paridade)
**REGRA DE LOOP:** Para **CADA** arquivo criado em `intermediate` e `marts` (sem exceção), gere o arquivo `.yml` individual correspondente.
- Gere o `.yml` com testes (`unique`, `not_null`) na PK.
**REGRA DE ESPELHAMENTO TOTAL (CRÍTICO):**
O arquivo `.yml` deve conter **TODAS** as colunas que estão no `SELECT` final do seu modelo.
* Se o SQL tem 50 colunas, o YAML deve ter 50 entradas em `columns:`.
* **PROIBIDO:** Documentar apenas as primeiras colunas ou apenas as chaves.
* **AÇÃO:** Leia a lista final de colunas do SQL/Python e gere a entrada no YAML para cada uma.
**REGRA DE BLOQUEIO:** O YAML deve ser um **ESPELHO EXATO** do modelo final.

**PROIBIÇÕES EXPLÍCITAS NO YAML:**
❌ **NÃO** use comentários como `# ... demais colunas ...`.
❌ **NÃO** liste apenas as chaves primárias.
❌ **NÃO** pare a lista no meio.

**AÇÃO OBRIGATÓRIA:**
1. Conte quantas colunas existem no `SELECT` final do seu código. (Ex: 45 colunas).
2. Gere o arquivo `.yml`.
3. Certifique-se de que existem exatamente 45 entradas em `columns:`.
4. **Se a contagem não bater, REESCREVA o YAML.**

* **Verificação:** Se você gerou 7 modelos SQL, você deve entregar 7 arquivos YAML.

**Conteúdo do YAML:**
1. **Idioma:** Todas as `description` em **Português Brasileiro**.
2. **Policy Tags:** Se houver PII (conforme `sensitive_data_types.yaml` + consistência com os marts em **`04_marts`**), adicione na coluna do YML, em lista de um item, por exemplo: `policy_tags:\n          - '{{ var ("PII_INTERNO_<SUFIXO>") }}'` — use **exatamente** o mesmo formato de aspas e espaços que esses `.yml` usam para `policy_tags`.
3. **Configuração do Cron e Descrição:**
  **Se Intermediate:**
    - `cron: "0 8 * * *"`
    - Adicione ao final da description: `" Sua periodicidade de atualização é diária às 08:00"`
  **Se Marts:**
    - `cron: "0 9 * * *"`
  - Adicione ao final da description: `" Sua periodicidade de atualização é diária às 09:00"`
4. **Tests:** `unique` e `not_null` na PK.

**Qualidade das descriptions (modelo e colunas) — obrigatório além de PT-BR e cron:**
* **Modelo (nível tabela, campo `description` do model):** A descrição **não** pode ser só periodicidade nem frases vazias do tipo "tabela intermediária/consolidada" sem contexto. Inclua, em prosa clara e objetiva: **propósito de negócio** do dataset; **granularidade** (ex.: uma linha por contrato, por cliente-dia, por operação); **principais fontes** em linguagem natural (quais `ref`/`source` alimentam o modelo, sem listar coluna a coluna); vínculo ao **fluxo ou EGP** quando fizer sentido (`MIGRATION_SPEC`, nome do projeto ou domínio da secção 2). **Depois** acrescente a frase de periodicidade exigida no item 3.
* **Colunas:** Para cada entrada em `columns:`, use **frase completa**: o que o campo representa; **unidade ou formato** quando relevante (ex.: monetário em BRL, data `YYYY-MM-DD`); **domínio ou valores típicos** se inferíveis do SAS, labels ou spec; para campos **derivados/calculados**, indique **regra ou origem** em uma linha (ex.: "Calculado a partir de …", "Máximo entre …"). **Proibido** como descrição aceitável quando o significado for dedutível do código ou dos artefatos de entrada: apenas `"PK"`, `"Chave"`, `"Código"`, `"ID"` ou repetir o nome físico da coluna sem acrescentar significado de negócio.

### 6. Estruturação de Pastas (dbt)
Mova e renomeie os arquivos para a estrutura correta:
- Limpeza/Ingestão -> `models/staging/stg_[nome].sql`.
- Regras de Negócio -> `models/intermediate/int_<produto_compacto>_<detalhe>.sql` (ex.: `int_pagamentosdigital_base_pagamentos.sql`).
- Tabelas Finais (fato do EGP) -> `models/marts/<produto_compacto>_<detalhe>_fato.sql` (ex.: Pagamentos Digital → `pagamentosdigital_acordos_fato`).
    - **Outros marts:** `<assunto>_<detalhe>_fato` ou export `cobranca_<parceiro>_fato` conforme `@01_sas_to_dbt.mdc`.
        * *Exemplo Ruim:* `base_carteira_fato` (Genérico demais).
        * *Exemplo Bom (domínio):* `cobranca_carteira_fato`.
        * *Exemplo Bom (EGP Pagamentos Digital):* `pagamentosdigital_acordos_fato`.

### 7. Aplicação de Governança (CRÍTICO)
- Injete o bloco `{{ config(labels={...}) }}` com tags e labels conforme as regras `.mdc` em todos os models `intermediate` e `marts`.
- **`fl_modernizacao_legacy`:** sempre **`'false'`** (string no label), em **todos** os `intermediate` e `marts`.
- **`nm_delivery_legacy`:** obrigatório, **não vazio**, sempre **minúsculo**, no formato literal **`sas__<tabela>`** (prefixo `sas__` em minúsculas + nome da tabela SAS principal do modelo). **Não** usar `[SAS]`, libref/schema (`ADAMOR.`, `CARTAOBV.` etc.) nem `WORK.`; caracteres inválidos para identificador viram `_`. Com várias fontes, usar a **tabela SAS/WORK principal da junção**. Exemplos: `ADAMOR.CLIENTES` → `sas__clientes`; `WORK.TMP_BASE` → `sas__tmp_base`; `CARTAOBV.TBL_RAC_RESUMO_202603` → `sas__tbl_rac_resumo_202603`. Ver `@01_sas_to_dbt.mdc` §4. O `apply_governance_config` **não** preenche este campo: deve ficar correto **antes** do merge (se o script injetar `labels` com `nm_delivery_legacy` vazio, substituir na mesma fase de governança).

**A. Tags de Rastreabilidade:**
Obrigatório: `tags=['<camada>', '<nome_pasta_egp_lower>', 'migracao_egp', 'migracao_sas']`

**B. Código de governança (`cd_governanca`):**
1. Leia o ficheiro **`converter/registry/area_cd_governanca.yaml`** (se não existir, copie de **`area_cd_governanca.example.yaml`** e preencha).
2. Obtenha o slug **`area`** do EGP em **`registry/egp_catalog.yaml`** (mesmo contexto do PASSO 1b / catálogo).
3. Use `area_cd_governanca[<area>]` como string em `labels['cd_governanca']`. Se a área não estiver no mapa, use **`default_cd_governanca`** do YAML.
4. Referência rápida (tabela oficial pode diferir — o YAML é a fonte de verdade):
   - **1** — Clientes, Canais, Visão 360 · **3** — CRM, Campanhas · **11** — Negócios, Rodas · **14** — Seguros · **20** — Crédito Varejo, Risco · **22** — Cobrança, Dívida, Fatura · **99** — Outros.

**C. Tratamento de PII:**
- Use **`converter/registry/sensitive_data_types.yaml`** como lista canónica de tipos sensíveis; além disso, aplique o mesmo critério de negócio que já existe nos marts do componente (nomes de coluna, documentação).
- Se identificar colunas sensíveis (CPF, Email, Telefone):
  1. Lista de campos Críticos (Requerem Mascaramento STRING)
    **Documentos:** `cpf`, `cnpj`, `rg`, `passaporte`, `nucpf`, `nucnpj`, `nudocumento`.
    **Contatos:** `email`, `telefone`, `celular`, `dsemail`, `nutelefone`.
    **Nomes:** `nome`, `cliente`, `mae`, `pai`, `conjuge`, `nmcliente`, `nmpessoa`.
    **Endereço:** `endereco`, `cep`, `logradouro`, `cdcep`, `nucep`.
    **Financeiro/Contrato:** `conta`, `agencia`, `cartao`, `pix`, `nucontrato`, `nucartao`.
    **Veículo:** `chassi`, `placa`, `renavam`, `nuchassi`, `dsplaca`.
    **Sensíveis:** `genero`, `sexo`, `religiao`, `etnia`, `pcd`.
  2. No SQL: Faça o CAST para STRING (ex: `CAST(nu_cpf AS STRING)`).
  3. No Config: Defina `fl_contem_pii: 'true'`.

Gere o arquivo `DE_PARA_TIPAGEM.md` na raiz. Ele DEVE conter uma seção **Filtros (WHERE)** mapeando cada filtro do código original para o modelo/arquivo onde foi aplicado (evitar que filtros sejam perdidos na refatoração).

## SAÍDA
Salve os arquivos finais em `converted_egps/[DATA_CONVERSAO]_[ULTIMO_COMMIT]_[TARGET_ARCH]/[NOME_PROJETO]/` (ou legado `converted_egps/[TARGET_ARCH]/[NOME_PROJETO]/` só se o time pedir explicitamente).

**`draft_models/` — política padrão:** **não apagar** `draft_models/<NOME_PROJETO>/` após a governança até **PASSO 5** concluído e **`AUDITORIA_*.md`** aceite pelo time, **ou** pedido explícito do utilizador. Motivos e exceções: skill **orchestrator**, secção **Ciclo de vida de `draft_models/`** (fonte canónica).

## Auto‑validação obrigatória (IA) — mesmo com scripts OK

Antes de declarar o **PASSO 3A** concluído (e antes de iniciar o 3B), aplique o checklist **obrigatório**:

- `converter/templates/AI_VALIDATION_CHECKLIST.md` (seção **PASSO 3A**)

Se o checklist falhar (ex.: staging com JOIN/2 fontes, passthrough fora do padrão `stg_*` + `int_*`, marts sem output real ou duplicadas, presença de `ref('step_')` no sandbox), **não avance**: corrija e revalide.