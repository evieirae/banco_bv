# SAS Migration Assessment Tool - dbt Project

Projeto dbt para análise e avaliação de migração de projetos SAS, processando logs de execução para extrair dependências, linhagem de dados, classificação de processos e métricas de execução.

---

## 📋 Índice

1. [Visão Geral do Projeto](#visão-geral-do-projeto)
2. [Propósito das Transformações](#propósito-das-transformações)
3. [Informações Disponíveis](#informações-disponíveis)
4. [Estrutura do Projeto](#estrutura-do-projeto)
5. [Camadas de Transformação](#camadas-de-transformação)
6. [Configuração e Instalação](#configuração-e-instalação)
7. [Como Executar](#como-executar)
8. [Modelos Principais](#modelos-principais)
9. [CI/CD](#cicd)
10. [Referências](#referências)

---

## 🎯 Visão Geral do Projeto

Este projeto dbt foi desenvolvido para **avaliar e analisar projetos SAS** como parte de um processo de migração. Ele processa logs de execução de SAS para extrair informações críticas sobre:

- **Dependências entre projetos e tabelas**
- **Linhagem de dados completa**
- **Classificação de processos** (ETL, Analítico, Ad Hoc, Machine Learning)
- **Métricas de execução e performance**
- **Variáveis e configurações utilizadas**
- **Status de modernização de tabelas**

O projeto suporta **Databricks** e **Snowflake**, permitindo análise flexível em diferentes plataformas de data warehouse.

---

## 🔄 Propósito das Transformações

### Objetivo Principal

Facilitar a **avaliação de complexidade e dependências** de projetos SAS antes da migração para plataformas modernas de data warehouse, fornecendo insights estruturados sobre:

1. **Mapeamento de Dependências**: Identificar quais tabelas cada projeto SAS lê e escreve
2. **Classificação de Processos**: Categorizar projetos como ETL, Analítico, Ad Hoc ou Machine Learning
3. **Linhagem de Dados**: Mapear o fluxo completo de dados entre projetos, tabelas e arquivos
4. **Análise de Código**: Extrair e estruturar statements SAS (PROC SQL, DATA steps, etc.)
5. **Métricas de Execução**: Coletar informações sobre performance, uso de memória e tempo de execução
6. **Modernização**: Identificar tabelas que já foram modernizadas e mapear origens

### Fluxo de Transformação

```
Logs SAS Brutos (log_base)
    ↓
[Staging] Limpeza e Normalização
    ↓
[Trusted] Agregação e Extração de Informações
    ↓
[Marts] Dimensões e Fatos para Análise
    ↓
[Serving] Camada Final para BI/Visualização
```

---

## 📊 Informações Disponíveis

### Camada Staging (`00_staging`)

**Modelos:**
- **`stg_log_process`**: Processa e limpa logs SAS brutos, extraindo código, identificando blocos e normalizando dados
- **`stg_table_modernized`**: Lista de tabelas modernizadas no BigQuery com mapeamento para tabelas originais
- **`stg_user`**: Informações de usuários (login, área, diretoria)

**Informações Extraídas:**
- Código SAS limpo e normalizado
- Números de linha e identificadores de blocos
- Tipos de conexão utilizados
- Datas e timestamps de execução

### Camada Trusted (`01_trusted`)

**Modelos:**
- **`int_log_grouped`**: Agrupa logs por blocos de código, extrai nomes de projetos e tarefas, agrega métricas de performance
- **`int_log_statement`**: Extrai e identifica statements SAS individuais (PROC SQL, DATA steps, etc.)
- **`int_table_modernized`**: Versão limpa da lista de tabelas modernizadas

**Informações Extraídas:**
- Blocos de código agrupados por projeto e tarefa
- Statements SAS categorizados por tipo
- Métricas de performance (real_time, memory, os_memory)
- Identificadores únicos de blocos e projetos

### Camada Marts (`02_marts`)

#### Dimensões

- **`dim_project_dependencie`**: Visão consolidada de dependências de projetos
  - Contagem de blocos SQL, Python e SAS
  - Tabelas fonte e destino por projeto
  - Classificação de tipo de processo (ETL, Analítico, Ad Hoc, ML)
  - Variáveis macro utilizadas

- **`dim_table`**: Catálogo de todas as tabelas referenciadas no código SAS
  - Nome da tabela normalizado
  - Papel (SOURCE ou TARGET)
  - Tipo de conexão (SAS, WORK, BIGQUERY, SYBASE, etc.)
  - Status de modernização

- **`dim_user`**: Dimensão de usuários
- **`dim_variables`**: Variáveis macro SAS (%LET) e referências de bibliotecas (LIBNAME)

#### Fatos

- **`fact_log_block`**: Métricas de execução agregadas por projeto e arquivo de log
  - Número de tarefas executadas
  - Número de blocos de código executados
  - Tempo total de processamento
  - Lista de tarefas executadas

- **`fact_project_depend`**: Relacionamentos de linhagem de dados
  - Projetos que leem/escrevem tabelas
  - Tipos de objetos (Tabela SAS, Arquivo externo, WORK, etc.)
  - Relacionamentos READ/WRITE

---

## 📁 Estrutura do Projeto

```
dbt_sas_migration_assessment/
├── models/
│   ├── 00_staging/          # Limpeza e normalização inicial
│   ├── 01_trusted/          # Agregação e extração de informações
│   ├── 02_marts/            # Dimensões e fatos para análise
│   └── 03_serving/          # Camada final para BI
├── macros/                  # Macros dbt reutilizáveis
├── hooks/                   # Hooks customizados
├── seeds/                   # Dados de referência (CSV)
├── snapshots/               # Snapshots para histórico
├── tests/                   # Testes customizados
├── analyses/                # Análises adicionais
├── dbt_project.yml          # Configuração do projeto
├── profiles.yml             # Perfis de conexão
├── packages.yml             # Pacotes dbt
└── requirements_databricks.txt  # Dependências Python
```

---

## 🏗️ Camadas de Transformação

### 1. Staging (`00_staging`)
**Propósito**: Limpeza, normalização e preparação dos dados brutos

- Remove ruídos dos logs SAS
- Extrai código limpo de statements
- Normaliza nomes de colunas e tipos de dados
- Identifica blocos de código e agrupa linhas relacionadas

### 2. Trusted (`01_trusted`)
**Propósito**: Validação, agregação e estruturação de dados confiáveis

- Agrupa logs por blocos de código
- Extrai informações de projetos e tarefas
- Identifica e categoriza statements SAS
- Calcula métricas de performance

### 3. Marts (`02_marts`)
**Propósito**: Modelagem dimensional para análise de negócio

- **Dimensões**: Projetos, Tabelas, Usuários, Variáveis
- **Fatos**: Execuções de logs, Dependências de projetos
- Permite análises como:
  - Quais projetos dependem de quais tabelas?
  - Quais projetos são ETL vs Analítico?
  - Qual é a linhagem completa de dados?

### 4. Serving (`03_serving`)
**Propósito**: Camada final otimizada para visualização e BI

- Modelos com contratos garantidos
- Estrutura otimizada para ferramentas de BI
- Agregações pré-calculadas

---

## ⚙️ Configuração e Instalação

### Pré-requisitos

- Python 3.8+
- dbt-core >= 1.7.0, < 2.0.0
- Acesso a Databricks ou Snowflake
- Variáveis de ambiente configuradas

### 1. Configurar Variáveis de Ambiente

Copie o arquivo de exemplo e configure suas credenciais:

```bash
cp example.env .env
# Edite .env com suas credenciais
```

**Para Databricks:**
```bash
DEV_DATABRICKS_CATALOG=seu_catalog
DEV_DATABRICKS_HOST=https://seu-workspace.cloud.databricks.com
DEV_DATABRICKS_TOKEN=seu_token
DEV_DATABRICKS_SCHEMA=dev
```

**Para Snowflake:**
```bash
DEV_SNOWFLAKE_ACCOUNT=seu_account
DEV_SNOWFLAKE_USER=seu_user
DEV_SNOWFLAKE_PASSWORD=sua_senha
DEV_SNOWFLAKE_DATABASE=seu_database
DEV_SNOWFLAKE_SCHEMA=dev
```

**Configurações do dbt:**
```bash
DBT_PROFILE_TARGET=indimesh_databricks  # ou indimesh_snowflake
DBT_DEFAULT_TARGET=dev
```

### 2. Criar Ambiente Virtual

```bash
# Para Databricks
python -m venv venv_databricks
source venv_databricks/bin/activate  # Windows: venv_databricks\Scripts\activate

# Para Snowflake
python -m venv venv_snowflake
source venv_snowflake/bin/activate  # Windows: venv_snowflake\Scripts\activate
```

### 3. Instalar Dependências

```bash
# Para Databricks
pip install -r requirements_databricks.txt

# Para Snowflake
pip install -r requirements_snowflake.txt
```

### 4. Instalar Pacotes dbt

```bash
dbt deps
```

### 5. Carregar Variáveis de Ambiente

```bash
# Linux/macOS
source .env

# Windows PowerShell
. .\.env
```

---

## 🚀 Como Executar

### Verificar Conexão

```bash
dbt debug
```

### Executar Modelos Específicos

```bash
# Executar apenas a camada staging
dbt build -s 00_staging

# Executar apenas a camada trusted
dbt build -s 01_trusted

# Executar apenas a camada marts
dbt build -s 02_marts

# Executar um modelo específico
dbt build -s stg_log_process

# Executar um modelo e suas dependências
dbt build -s dim_project_dependencie --select dim_project_dependencie+
```

### Executar Todo o Projeto

```bash
# Executar todos os modelos
dbt build

# Executar apenas modelos alterados (Slim CI)
dbt build --select state:modified+
```

### Executar Testes

```bash
# Executar todos os testes
dbt test

# Executar testes de um modelo específico
dbt test -s dim_project_dependencie
```

### Gerar Documentação

```bash
# Gerar documentação
dbt docs generate

# Servir documentação localmente
dbt docs serve
```

### Limpar Artefatos

```bash
# Limpar diretórios target e dbt_packages
dbt clean
```

---

## 📈 Modelos Principais

### `stg_log_process`
Processa logs SAS brutos, extraindo código limpo e identificando blocos de execução.

**Colunas principais:**
- `log_file`: Nome do arquivo de log
- `log_date`: Data/hora da execução
- `user_id`: Usuário que executou
- `clean_text`: Código SAS limpo
- `connection_type`: Tipo de conexão utilizada

### `int_log_grouped`
Agrupa logs por blocos de código, extrai projetos e tarefas, agrega métricas.

**Colunas principais:**
- `block_id`: Identificador único do bloco
- `project_name`: Nome do projeto SAS
- `task_name`: Nome da tarefa
- `code_log`: Código completo do bloco
- `real_time`, `memory`, `os_memory`: Métricas de performance

### `dim_project_dependencie`
Visão consolidada de dependências e características de projetos SAS.

**Colunas principais:**
- `project_id`: ID único do projeto
- `project_name`: Nome do projeto
- `target_table`: Tabelas escritas pelo projeto
- `source_table`: Tabelas lidas pelo projeto
- `process_type`: Classificação (ETL, Analítico, Ad Hoc, ML)
- `count_sql_blocks`, `count_sas_blocks`: Contadores de tipos de código

### `dim_table`
Catálogo de todas as tabelas referenciadas no código SAS.

**Colunas principais:**
- `table_name`: Nome da tabela
- `role`: SOURCE ou TARGET
- `connection_type`: Tipo de conexão (SAS, BIGQUERY, SYBASE, etc.)
- `is_modernized`: Flag indicando se a tabela foi modernizada

### `fact_project_depend`
Relacionamentos de linhagem de dados entre projetos e objetos.

**Colunas principais:**
- `parent_name`: Nome do projeto
- `relationship_type`: "le" (lê) ou "escreve"
- `children_name`: Nome do objeto (tabela/arquivo)
- `children_type`: Tipo do objeto

### `fact_log_block`
Métricas agregadas de execução por projeto e arquivo de log.

**Colunas principais:**
- `log_block_fk`: Chave única do bloco de log
- `project_id`: ID do projeto
- `tasks_executed_number`: Número de tarefas executadas
- `code_blocks_executed_number`: Número de blocos executados
- `execution_process_time`: Tempo total de execução

---

## 🔍 Exemplos de Uso

### Identificar Projetos que Usam uma Tabela Específica

```sql
SELECT 
    project_name,
    relationship_type,
    children_name
FROM {{ ref('fact_project_depend') }}
WHERE children_name LIKE '%nome_da_tabela%'
```

### Listar Projetos Classificados como ETL

```sql
SELECT 
    project_name,
    count_sql_blocks,
    count_sas_blocks,
    source_table,
    target_table
FROM {{ ref('dim_project_dependencie') }}
WHERE process_type LIKE '%ETL%'
```

### Analisar Performance de Execução

```sql
SELECT 
    project_name,
    log_filename,
    tasks_executed_number,
    code_blocks_executed_number,
    execution_process_time
FROM {{ ref('fact_log_block') }}
ORDER BY execution_process_time DESC
```

### Verificar Tabelas Modernizadas

```sql
SELECT 
    table_name,
    role,
    connection_type,
    is_modernized
FROM {{ ref('dim_table') }}
WHERE is_modernized = 1
```

---

## 🔄 CI/CD

O projeto inclui pipeline CI/CD configurado via Bitbucket Pipelines (`bitbucket-pipelines.yml`).

### Processo CI/CD

1. **Validação**: Linting (SQLFluff, yamllint), validação de sintaxe
2. **Build**: Execução de `dbt build` apenas para modelos alterados (Slim CI)
3. **Testes**: Execução de testes dbt
4. **Upload de Artefatos**: Upload de manifest e catalog para reutilização
5. **Limpeza**: Limpeza automática de schemas inativos

### Executar Manualmente

Para executar o pipeline manualmente no Bitbucket:
- Acesse **Pipelines** → **Run pipeline**
- Selecione o branch e as variáveis de ambiente

---

## 📚 Referências

### Arquivos Importantes

- [`dbt_project.yml`](dbt_project.yml): Configuração principal do projeto
- [`profiles.yml`](profiles.yml): Perfis de conexão com data warehouses
- [`packages.yml`](packages.yml): Pacotes dbt utilizados
- [`example.env`](example.env): Template de variáveis de ambiente
- [`bitbucket-pipelines.yml`](bitbucket-pipelines.yml): Configuração CI/CD

### Pacotes dbt Utilizados

- `dbt-labs/dbt_utils`: Utilitários comuns
- `calogica/dbt_expectations`: Testes de qualidade de dados
- `dbt-labs/codegen`: Geração de código
- `indiciumtech/indicium_dbt_utils`: Utilitários customizados Indicium

### Documentação Adicional

Para documentação detalhada sobre modelagem, consulte:
- [Documentation Repository](https://bitbucket.org/indiciumtech/documentation-indimesh-acceleration-suite/src/main/4-%20Delivery%20Mesh%20Project/Data%20Modeling/)

---

## 🤝 Contribuindo

1. Crie uma branch: `feature/...`, `bugfix/...`, ou `hotfix/...`
2. Faça suas alterações e atualize a documentação
3. Submeta um pull request
4. Garanta que todos os checks do CI passem
5. Aguarde revisão e aprovação

---

## 📝 Notas

- O projeto suporta **Databricks** e **Snowflake** simultaneamente
- Em produção, recomenda-se manter apenas a plataforma utilizada
- Modelos na camada `serving` têm contratos garantidos
- Documentação é persistida apenas em ambientes `prod` e `ci`

---

> Para dúvidas ou problemas, abra uma issue ou entre em contato com os mantenedores.
