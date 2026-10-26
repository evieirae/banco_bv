# 📊 Pipeline de Ingestão de Dados - SAS Assessment Tool

Pipeline completo para ingestão de dados SAS no Databricks, incluindo logs, usuários e tabelas modernizadas.

## 📋 Índice

- [Visão Geral](#visão-geral)
- [Pré-requisitos](#pré-requisitos)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Scripts Disponíveis](#scripts-disponíveis)
- [Processamento Paralelo](#processamento-paralelo)
- [Flags e Opções](#flags-e-opções)
- [Exemplos de Uso](#exemplos-de-uso)
- [Estrutura de Diretórios](#estrutura-de-diretórios)
- [Troubleshooting](#troubleshooting)

---

## 🎯 Visão Geral

Este pipeline permite:

- **Ingestão de Logs SAS**: Processa arquivos `.log` e extrai métricas de performance, erros e objetos de banco de dados
- **Ingestão de Usuários**: Carrega dados de usuários do CSV para o Databricks
- **Ingestão de Tabelas Modernizadas**: Carrega lista de tabelas modernizadas do BigQuery

### Características Principais

✅ **Processamento Paralelo**: Suporta processamento sequencial e paralelo (3-8x mais rápido)  
✅ **Inserção Incremental**: Verificação de duplicatas e processamento incremental seguro  
✅ **Autenticação OAuth**: Login via navegador (OAuth U2M)  
✅ **Retry Automático**: Tratamento de erros de concorrência Delta Lake  
✅ **Feedback Visual**: Progresso em tempo real durante processamento  

---

## 📦 Pré-requisitos

- Python 3.8 ou superior
- Acesso ao Databricks SQL Warehouse
- Credenciais configuradas no arquivo `.env`
- Arquivos de dados na estrutura correta (ver [Estrutura de Diretórios](#estrutura-de-diretórios))

---

## 🔧 Instalação

1. **Clone o repositório** (se ainda não tiver):
   ```bash
   git clone <repository-url>
   cd sas_assessment_tool
   ```

2. **Instale as dependências**:
   ```bash
   cd ingestion
   pip install -r requirements.txt
   ```

   Ou instale individualmente:
   ```bash
   pip install databricks-sql-connector>=3.0.0
   pip install pandas>=2.0.0
   pip install python-dotenv>=1.0.0
   ```

---

## ⚙️ Configuração

Crie um arquivo `.env` na raiz do projeto com as seguintes variáveis:

```env
# Databricks Configuration (Obrigatório)
DATABRICKS_SERVER_HOSTNAME=seu-workspace.cloud.databricks.com
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/seu-warehouse-id

# Databricks Catalog e Schema (Opcional - valores padrão)
DATABRICKS_CATALOG=bv_dev_db
DATABRICKS_SCHEMA=bv_migration_sas
```

### Como obter as credenciais:

1. **DATABRICKS_SERVER_HOSTNAME**: URL do seu workspace Databricks
   - Exemplo: `dbc-5626df64-1b10.cloud.databricks.com`

2. **DATABRICKS_HTTP_PATH**: Path do SQL Warehouse
   - Acesse: Databricks → SQL Warehouses → Seu Warehouse → Connection Details
   - Copie o "Server hostname" e "HTTP path"

---

## 📜 Scripts Disponíveis

### 1. `ingest_sas_logs.py` - Ingestão de Logs SAS

Processa arquivos `.log` do diretório `log_files/` e extrai:
- Métricas de performance (CPU, memória, tempo de execução)
- Erros e warnings
- Objetos de banco de dados (tabelas, libnames, arquivos)
- Classificação de tipos de processo (ETL, analítico, modelo)
- Queries custosas

**Tabela de destino**: `{catalog}.{schema}.log_base_final`

### 2. `ingest_users.py` - Ingestão de Usuários

Carrega dados de usuários do arquivo `src/users.csv` para o Databricks.

**Tabela de destino**: `{catalog}.{schema}.users_final`

### 3. `ingest_modernized_tables.py` - Ingestão de Tabelas Modernizadas

Carrega lista de tabelas modernizadas do arquivo `src/Tabelas-Modernizadas-BQ.csv`.

**Tabela de destino**: `{catalog}.{schema}.modernized_tables`

---

## ⚡ Processamento Paralelo

O script `ingest_sas_logs.py` suporta processamento **sequencial** e **paralelo**.

### Modo Sequencial

- Processa um arquivo por vez
- Mais seguro e previsível
- Melhor para debug
- Mais lento (1x velocidade)

### Modo Paralelo

- Processa múltiplos arquivos simultaneamente
- **3-8x mais rápido** que o sequencial
- Usa múltiplos workers (processos)
- Ideal para grandes volumes de dados

#### Como Funciona

1. **Workers**: Cada worker processa um arquivo por vez
2. **Lock de Autenticação**: Evita múltiplas abas do navegador durante OAuth
3. **Retry Automático**: Trata erros de concorrência Delta Lake
4. **Progresso em Tempo Real**: Mostra status de cada arquivo processado

#### Configuração de Workers

- **Padrão**: `CPUs - 1` (automático)
- **Manual**: Use `--workers N` para especificar o número
- **Recomendação**: 
  - 4-6 workers para máquinas com 8+ CPUs
  - 2-4 workers para máquinas com 4-8 CPUs
  - 1-2 workers para máquinas com menos de 4 CPUs

#### Exemplo de Saída Paralela

```
🚀 Iniciando processamento paralelo...

🔧 Usando 6 workers paralelos (de 8 CPUs disponíveis)
⚡ Aceleração esperada: ~6x
🔒 Usando lock de autenticação para evitar múltiplas abas do navegador

✅ [1/50] arquivo1.log | 2.0% | ETA: 15.3min
✅ [2/50] arquivo2.log | 4.0% | ETA: 14.8min
...
```

---

## 🚩 Flags e Opções

### Flags do `ingest_sas_logs.py`

| Flag | Descrição | Quando Usar |
|------|-----------|-------------|
| `--parallel` | Ativa processamento paralelo | Para grandes volumes de dados |
| `--workers N` | Define número de workers (padrão: CPUs-1) | Para controlar paralelismo |
| `--clean` | Limpa a tabela antes de processar | Primeira execução ou reset completo |
| `--sort_minsize` | Ordena arquivos por tamanho (menores primeiro) | Para processar arquivos pequenos primeiro |
| `--check_duplicates` | Verifica duplicatas no banco | Para inserção incremental segura |
| `--check_file_hash` | Valida arquivos únicos por hash SHA256 | Para detectar arquivos duplicados por conteúdo |

### Detalhamento das Flags

#### `--clean`
- **O que faz**: Remove todos os dados da tabela `log_base_final` antes de processar
- **Confirmação**: Solicita confirmação interativa (digite 'SIM' para confirmar)
- **Uso**: Primeira execução ou quando quiser reprocessar tudo do zero

#### `--sort_minsize`
- **O que faz**: Ordena arquivos por tamanho (menores primeiro)
- **Vantagem**: Processa arquivos pequenos primeiro, mostrando progresso mais rápido
- **Uso**: Quando há muitos arquivos de tamanhos variados

#### `--check_duplicates`
- **O que faz**: Verifica se o arquivo já foi inserido no banco antes de processar
- **Threshold**: Arquivos com menos de 100 registros são considerados "parciais" e reprocessados
- **Uso**: Para inserção incremental sem duplicatas

#### `--check_file_hash`
- **O que faz**: Calcula hash SHA256 de cada arquivo e remove duplicatas por conteúdo
- **Vantagem**: Detecta arquivos idênticos mesmo com nomes diferentes
- **Uso**: Quando há suspeita de arquivos duplicados

---

## 💡 Exemplos de Uso

### Ingestão de Logs SAS

#### 1. Processamento Sequencial Básico
```bash
cd ingestion
python ingest_sas_logs.py
```

#### 2. Processamento Sequencial com Limpeza
```bash
python ingest_sas_logs.py --clean
```
> ⚠️ **Atenção**: Solicita confirmação antes de apagar dados!

#### 3. Processamento Paralelo (Recomendado)
```bash
python ingest_sas_logs.py --parallel
```

#### 4. Processamento Paralelo com 6 Workers
```bash
python ingest_sas_logs.py --parallel --workers 6
```

#### 5. Processamento Paralelo com Limpeza e Ordenação
```bash
python ingest_sas_logs.py --parallel --clean --sort_minsize
```

#### 6. Inserção Incremental (Verifica Duplicatas)
```bash
python ingest_sas_logs.py --check_duplicates
```

#### 7. Validação de Arquivos Únicos por Hash
```bash
python ingest_sas_logs.py --check_file_hash
```

#### 8. Combinado: Verifica Banco E Hash
```bash
python ingest_sas_logs.py --check_duplicates --check_file_hash
```

#### 9. Processamento Paralelo Completo (Recomendado para Produção)
```bash
python ingest_sas_logs.py --parallel --workers 6 --check_duplicates --sort_minsize
```

### Ingestão de Usuários

```bash
cd ingestion
python ingest_users.py
```

**Arquivo esperado**: `src/users.csv`  
**Formato**: CSV com separador `;` (ponto e vírgula)

### Ingestão de Tabelas Modernizadas

```bash
cd ingestion
python ingest_modernized_tables.py
```

**Arquivo esperado**: `src/Tabelas-Modernizadas-BQ.csv`  
**Formato**: CSV com separador `,` (vírgula)

---

## 📁 Estrutura de Diretórios

```
ingestion/
├── ingest_sas_logs.py              # Script principal de logs
├── ingest_users.py                  # Script de usuários
├── ingest_modernized_tables.py      # Script de tabelas modernizadas
├── sas_log_analyzer.py              # Módulo de análise de logs
├── regex_patterns.py                # Padrões regex centralizados
├── requirements.txt                 # Dependências Python
├── README.md                        # Este arquivo
│
├── log_files/                       # Diretório de logs SAS
│   ├── *.log                        # Arquivos de log para processar
│   ├── processed/                   # Arquivos processados com sucesso
│   └── failed/                      # Arquivos que falharam
│
└── src/                             # Arquivos de dados
    ├── users.csv                    # CSV de usuários
    └── Tabelas-Modernizadas-BQ.csv  # CSV de tabelas modernizadas
```

### Fluxo de Processamento de Logs

1. **Arquivos `.log`** são colocados em `log_files/`
2. Script processa cada arquivo
3. **Sucesso**: Arquivo movido para `log_files/processed/`
4. **Falha**: Arquivo movido para `log_files/failed/`

---

## 🔍 Troubleshooting

### Erro: "DATABRICKS_SERVER_HOSTNAME não configurado"

**Solução**: Verifique se o arquivo `.env` existe e contém as variáveis necessárias.

```bash
# Verifique o arquivo .env
cat .env
```

### Erro: "cannot access local variable 'use_merge'"

**Solução**: Este erro foi corrigido. Certifique-se de estar usando a versão mais recente do código.

### Erro: "DELTA_METADATA_CHANGED"

**Solução**: Este erro é tratado automaticamente com retry. Se persistir:
- Reduza o número de workers: `--workers 2`
- Use modo sequencial: remova `--parallel`

### Múltiplas abas do navegador abrindo

**Solução**: O script já trata isso com lock. Se ainda ocorrer:
- Use menos workers: `--workers 2`
- Aguarde a primeira autenticação completar antes de iniciar outra

### Arquivo não encontrado

**Solução**: Verifique se os arquivos estão nos diretórios corretos:
- Logs: `ingestion/log_files/*.log`
- Usuários: `ingestion/src/users.csv`
- Tabelas: `ingestion/src/Tabelas-Modernizadas-BQ.csv`

### Processamento muito lento

**Soluções**:
1. Use processamento paralelo: `--parallel --workers 6`
2. Ordene por tamanho: `--sort_minsize`
3. Verifique conexão com Databricks
4. Reduza workers se houver muitos erros de concorrência

### Erro de autenticação OAuth

**Solução**:
1. Certifique-se de estar logado no Databricks
2. Verifique se o navegador não bloqueou pop-ups
3. Tente novamente após alguns segundos

---

## 📊 Métricas e Performance

### Tempo de Processamento

- **Sequencial**: ~1-2 minutos por arquivo de 1MB
- **Paralelo (6 workers)**: ~10-20 segundos por arquivo de 1MB
- **Aceleração**: 3-8x mais rápido com paralelismo

### Taxa de Inserção

- **Lotes**: 500 registros por lote
- **Velocidade**: ~1000-5000 registros/segundo (depende do Databricks)
- **Retry**: Automático para erros de concorrência

---

## 🔐 Segurança

- **Autenticação**: OAuth U2M (Browser Login) - não armazena senhas
- **Variáveis Sensíveis**: Armazenadas no `.env` (não commitar no Git)

---

## 📝 Notas Importantes

1. **Primeira Execução**: Use `--clean` para criar a tabela do zero
2. **Execuções Subsequentes**: Use `--check_duplicates` para inserção incremental
3. **Processamento Paralelo**: Recomendado para mais de 10 arquivos
4. **Arquivos Grandes**: Processamento paralelo é especialmente benéfico
5. **Backup**: Sempre faça backup antes de usar `--clean`

---

## 🆘 Suporte

Para problemas ou dúvidas:
1. Verifique os logs de erro em `log_files/failed/`
2. Revise a seção [Troubleshooting](#troubleshooting)
3. Consulte a documentação do Databricks SQL Connector

---

## 📄 Licença

Copyright (c) 2026 Indicium. Todos os direitos reservados.

Este código-fonte é estritamente confidencial e proprietário.
A cópia, modificação, distribuição ou uso não autorizado deste arquivo,
por qualquer meio, é estritamente proibido.

---

**Última atualização**: 2026-01-06

## 📝 Notas de Migração

### Migração para Databricks SQL
- ✅ Todos os scripts foram migrados de PostgreSQL para Databricks SQL
- ✅ Autenticação via OAuth U2M (Browser Login)
- ✅ Suporte a processamento paralelo com lock de autenticação
- ✅ Retry automático para erros de concorrência Delta Lake
- ✅ Inserção em lotes otimizada (500 registros por lote)

