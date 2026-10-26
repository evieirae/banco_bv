# Comparação SAS × dbt (`compare_sas_dbt.py`)

Script em Python que compara um arquivo exportado do **SAS** com um exportado do **dbt** (ou BigQuery), usando [datacompy](https://github.com/capitalone/datacompy). Útil para validar paridade após migração.

## O que o script faz

- Lê dois arquivos cujo formato é inferido pela **extensão**: `.csv`, `.xls` ou `.xlsx` (Excel usa sempre a **primeira planilha**).
- Aceita combinações mistas (ex.: SAS em `.xlsx` e dbt em `.csv`).
- Opcionalmente **mapeia colunas** quando os nomes diferem entre SAS e dbt (`--sas-cols` / `--dbt-cols`).
- Define **chave de join** (`--join-cols`). Sem join, a comparação é **linha a linha por posição** (`on_index`).
- Normaliza **datas** (`--date-cols`) para comparar formatos distintos (ex.: texto SAS `DDMonYYYY` vs `YYYY-MM-DD`).
- Normaliza números (vírgula decimal, inteiros vindos como `6.0` no Excel).
- Gera **relatório em texto** e imprime um **resumo** no terminal.

Os cabeçalhos são tratados em **minúsculas**; na linha de comando você pode usar qualquer capitalização.

## Fluxo do script

Visão em alto nível do que acontece desde a linha de comando até o relatório e o código de saída.  
*(Fluxo em texto puro: funciona em qualquer visualizador de Markdown; diagramas Mermaid exigem suporte explícito no editor ou no GitHub.)*

```text
                    ┌──────────────────────────────────────┐
                    │ 1. Parse da CLI e validação          │
                    │    (paths, extensões, regras)        │
                    └───────────────────┬──────────────────┘
                                        │
                                        v
                    ┌──────────────────────────────────────┐
                    │ 2. Ler arquivo SAS                     │
                    │    (.csv / .xls / .xlsx)               │
                    └───────────────────┬──────────────────┘
                                        │
                                        v
                    ┌──────────────────────────────────────┐
                    │ 3. Ler arquivo dbt                     │
                    │    (.csv / .xls / .xlsx)               │
                    └───────────────────┬──────────────────┘
                                        │
                                        v
                    ┌──────────────────────────────────────┐
                    │ 4. Nomes de colunas em minúsculas      │
                    └───────────────────┬──────────────────┘
                                        │
                                        v
                    ┌──────────────────────────────────────┐
                    │ 5. Alinhar colunas dos dois lados    │
                    └───────────────────┬──────────────────┘
                          ┌─────────────┴─────────────┐
                          │                             │
              com --sas-cols /           sem mapeamento:
              --dbt-cols:                  exige o MESMO
              seleciona SAS e              conjunto de
              renomeia p/ nomes dbt        colunas nos dois
                          │                             │
                          └─────────────┬───────────────┘
                                        │
                                        v
                    ┌──────────────────────────────────────┐
                    │ 6. Se --date-cols: normalizar datas    │
                    │    (ex.: SAS / Excel -> YYYY-MM-DD)    │
                    │    Senão: segue                        │
                    └───────────────────┬──────────────────┘
                                        │
                                        v
                    ┌──────────────────────────────────────┐
                    │ 7. Normalizar valores numéricos       │
                    │    (vírgula decimal, 6.0 -> 6, etc.)   │
                    └───────────────────┬──────────────────┘
                                        │
                                        v
                    ┌──────────────────────────────────────┐
                    │ 8. datacompy.Compare                  │
                    └───────────────────┬──────────────────┘
                          ┌─────────────┴─────────────┐
                          │                             │
              com --join-cols:           sem --join-cols:
              join pelas chaves          compara linha i
              (nomes canônicos)          com linha i (índice)
                          │                             │
                          └─────────────┬───────────────┘
                                        │
                                        v
                    ┌──────────────────────────────────────┐
                    │ 9. Gravar relatório (--report)        │
                    │    e imprimir resumo no terminal       │
                    └───────────────────┬──────────────────┘
                                        │
                          ┌─────────────┴─────────────┐
                          │                             │
                     match total                 diferenças ou
                          │                      erro de validação
                          v                             v
                      exit 0                        exit 1
```

Resumo linear:

1. **Entrada:** valida paths, extensões e regras da CLI (ex.: `--sas-cols` e `--dbt-cols` juntos).
2. **Leitura:** cada arquivo vira um `DataFrame` conforme a extensão (CSV com delimitador/encoding opcionais; Excel com correção de escapes `_xHHHH_` quando aplicável).
3. **Alinhamento:** nomes em minúsculas; com mapeamento, o lado SAS passa a usar os mesmos nomes que o dbt na ordem definida.
4. **Pré-comparação:** datas nas colunas indicadas; depois normalização ampla de valores para reduzir ruído (Excel vs CSV).
5. **Comparação:** `datacompy` com **join nas chaves** ou **por posição de linha**.
6. **Saída:** texto do relatório no arquivo e resumo no terminal; processo termina com **0** se houver match total, **1** caso contrário (ou erro de validação).

## Pré-requisitos

Na pasta `converter` (ou no ambiente do projeto), instale as dependências:

```bash
pip install pandas datacompy openpyxl
```

Ou use o `requirements.txt` do repositório (inclui outras ferramentas além deste script):

```bash
pip install -r requirements.txt
```

- **CSV:** só `pandas` + `datacompy`.
- **`.xlsx`:** também `openpyxl`.
- **`.xls`:** pode ser necessário `xlrd` (o próprio erro do pandas indica o pacote).

## Como executar

Execute a partir do diretório onde está o script, ou com caminho absoluto para o `.py` e para os arquivos de dados.

```text
python compare_sas_dbt.py <arquivo_sas> <arquivo_dbt> [opções]
```

### Argumentos posicionais

| Argumento   | Descrição |
|------------|-----------|
| `arquivo_sas`  | Primeiro conjunto (referência “SAS”). |
| `arquivo_dbt`  | Segundo conjunto (“dbt” / destino). |

### Opções principais

| Opção | Descrição |
|-------|-----------|
| `--sas-cols` | Lista de colunas do **SAS**, separadas por vírgula, na ordem desejada. Deve ser usada em par com `--dbt-cols`. |
| `--dbt-cols` | Colunas do **dbt**, **na mesma ordem** que `--sas-cols` (mapeamento 1:1). Após o mapeamento, os nomes canônicos são os do dbt. |
| `--join-cols` | Chaves de join, em **nomes do lado SAS** (como aparecem no arquivo SAS / em `--sas-cols`). Devem estar incluídas em `--sas-cols` quando há mapeamento. |
| `--date-cols` | Colunas de data em **nomes canônicos** (ou seja, **nomes do dbt** após o mapeamento), separadas por vírgula. |
| `--report PATH` | Arquivo de saída do relatório. Se omitido, usa `comparison_report.txt` no **diretório atual de trabalho**. |
| `--sas-delim` | Delimitador do CSV SAS (padrão: `,`). |
| `--dbt-delim` | Delimitador do CSV dbt (padrão: `,`). |
| `--sas-encoding` | Encoding do CSV SAS (se omitido, tenta `utf-8`, `latin-1`, `cp1252`). |
| `--dbt-encoding` | Encoding do CSV dbt (mesma lógica). |
| `--abs-tol` | Tolerância absoluta para números (padrão: `0`). |
| `--rel-tol` | Tolerância relativa para números (padrão: `0`). |

### Código de saída

- **0:** comparação indica **match** (`datacompy` considera os dados equivalentes nas regras configuradas).
- **1:** divergência ou erro de validação (arquivo inexistente, colunas faltando, etc.).
- **2:** pacote `datacompy` não instalado.

## Exemplos

### Exemplo completo (carteira): Excel SAS + CSV dbt

Comparação com mapeamento de colunas, chave `CONTRATO_LEGADO`, normalização de datas e relatório customizado:

**Linux / macOS / Git Bash (continuação de linha com `\`):**

```bash
python compare_sas_dbt.py BASE_CARTEIRA_20260306.xlsx gcp.csv \
  --sas-cols "CONTRATO_LEGADO, DT_ENVIO_ASSESSORIA, DATA_CONTRATO, ASSESSORIA, COMPLEMENTO_ASSESSORIA, PRODUTO, NOME_CLIENTE, SALDO_ATUAL, DIAS_EM_ATRASO, FASE, PLANO, QTD_PARCELAS_PAGAS, PARCELAS_NAO_PAGAS, PARCELAS_VINCENDAS, VALOR_PARCELA, MOD_NEGOCIACAO, MOD_PARCELAS" \
  --dbt-cols "cd_contrato_legado, dt_envio_assessoria, dt_contrato, nm_assessoria, nm_complemento_assessoria, ds_produto, nm_cliente, vr_saldo_atual, qt_dias_em_atraso, nu_fase, tp_plano, nu_parcelas_pagas, nu_parcelas_nao_pagas, nu_parcelas_vencidas, vr_valor_parcela, ds_mod_negociacao, st_mod_parcelas" \
  --join-cols "CONTRATO_LEGADO" \
  --date-cols "dt_envio_assessoria, dt_contrato" \
  --report relatorio_carteira.txt
```

**Windows (CMD):** use `^` para quebrar linha, ou coloque tudo em uma única linha.

```cmd
python compare_sas_dbt.py BASE_CARTEIRA_20260306.xlsx gcp.csv ^
  --sas-cols "CONTRATO_LEGADO, DT_ENVIO_ASSESSORIA, ..." ^
  --dbt-cols "cd_contrato_legado, dt_envio_assessoria, ..." ^
  --join-cols "CONTRATO_LEGADO" ^
  --date-cols "dt_envio_assessoria, dt_contrato" ^
  --report relatorio_carteira.txt
```

**PowerShell:** use o caractere de continuação `` ` `` no final de cada linha, ou um único comando sem quebras.

Ajuste os caminhos se os arquivos não estiverem na pasta atual:

```bash
python compare_sas_dbt.py ./exports/BASE_CARTEIRA_20260306.xlsx ./exports/gcp.csv --report ./out/relatorio_carteira.txt ...
```

### Dois CSVs com as mesmas colunas (sem mapeamento)

Quando os dois arquivos têm **exatamente o mesmo conjunto de colunas** (mesmos nomes, após normalização em minúsculas):

```bash
python compare_sas_dbt.py sas_export.csv dbt_export.csv --report comparacao.txt
```

Sem `--join-cols`, a comparação é **por índice de linha** (1ª com 1ª, 2ª com 2ª, etc.).

### CSV com ponto e vírgula e encoding Latin-1

```bash
python compare_sas_dbt.py sas.csv dbt.csv \
  --sas-delim ";" \
  --sas-encoding "latin-1" \
  --report relatorio.txt
```

### Mapeamento de colunas e join composto

```bash
python compare_sas_dbt.py sas.xlsx dbt.csv \
  --sas-cols "Data_Processamento,Id,Valor" \
  --dbt-cols "data_processamento,id,valor" \
  --join-cols "Data_Processamento,Id" \
  --date-cols "data_processamento" \
  --report output/comparison_report.txt
```

## Dicas e armadilhas comuns

1. **`--sas-cols` e `--dbt-cols`** devem ser informados **os dois** ou **nenhum**; a quantidade de colunas deve ser **igual** nos dois argumentos.
2. **`--join-cols`** usa nomes do **SAS** (como no arquivo / na lista `--sas-cols`). Cada uma dessas colunas precisa existir em `--sas-cols` quando há mapeamento.
3. **`--date-cols`** usa nomes **canônicos** (colunas do **dbt** após o alinhamento), em minúsculas na prática (o script normaliza).
4. **Ordem das colunas** em `--sas-cols` / `--dbt-cols` define a ordem do mapeamento posicional: primeira com primeira, segunda com segunda, etc.
5. Se alguma coluna listada **não existir** no arquivo correspondente, o script encerra com erro listando o que faltou.

## Saída

- **Terminal:** resumo com match, linhas só no SAS, só no dbt e (quando disponível) linhas com divergência de valor.
- **Arquivo `--report`:** relatório detalhado do datacompy (UTF-8). O diretório pai do arquivo é criado automaticamente se não existir.
