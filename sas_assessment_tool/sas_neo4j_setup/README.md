# SAS to Neo4j Migration - Gerador de Scripts Cypher

## 📋 Visão Geral

Este diretório contém o script refatorado para converter o CSV de análise de projetos SAS em scripts Cypher para carregamento no Neo4j.

## 🎯 Refatoração: 100% Data-Driven

### O que mudou?

**Antes (Hardcoded):**
- Lógica específica para cada tipo de nó (`egp project` → `EGPProject`)
- Mapeamento manual de relacionamentos (`reads from` → `READS_FROM`)
- Necessário alterar código para adicionar novos tipos

**Depois (Data-Driven):**
- ✅ Usa diretamente os valores do CSV (labels e tipos de relacionamento)
- ✅ Zero lógica de mapeamento hardcoded
- ✅ Qualquer mudança no CSV funciona automaticamente
- ✅ Código 50% menor e mais simples

## 📂 Estrutura de Arquivos

```
sas_neo4j_setup/
├── csv_to_cypher.py           # Script principal (refatorado)
├── exemplo_de_modelagem.csv   # CSV de entrada
├── docker-compose.yml         # Orquestração Neo4j + loader
├── nodes/                     # Scripts Cypher para criar nós
│   ├── clear_all_data.cypher
│   ├── create_egpproject_nodes.cypher
│   ├── create_externalsource_nodes.cypher
│   ├── create_includefiles_nodes.cypher
│   └── create_libnamesource_nodes.cypher
└── relationships/             # Scripts Cypher para criar relacionamentos
    ├── create_depends_on_relationships.cypher
    ├── create_reads_from_relationships.cypher
    └── create_writes_to_relationships.cypher
```

## 🚀 Como Usar

### 1. Gerar Scripts Cypher

```bash
cd sas_neo4j_setup
python3 csv_to_cypher.py
```

**Saída esperada:**
```
============================================================
Conversor CSV para Cypher - Migração SAS (Time BV)
Versão: Data-Driven (100% dinâmico)
============================================================

Processando arquivo: exemplo_de_modelagem.csv
  Processadas 10000 linhas...
  Processadas 20000 linhas...

Total de linhas processadas: 27565
Linhas ignoradas (dados inválidos): 0

Resumo:
  Nós únicos: 11350
  Relacionamentos: 27565

Nós por tipo:
  EgpProject: 2623
  ExternalSource: 2801
  IncludeFiles: 25
  LibnameSource: 5901

Relacionamentos por tipo:
  DEPENDS_ON: 1347
  READS_FROM: 22998
  WRITES_TO: 3220

✓ Gerado: nodes/create_egpproject_nodes.cypher (2623 nós)
✓ Gerado: nodes/create_externalsource_nodes.cypher (2801 nós)
✓ Gerado: nodes/create_includefiles_nodes.cypher (25 nós)
✓ Gerado: nodes/create_libnamesource_nodes.cypher (5901 nós)
✓ Gerado: relationships/create_depends_on_relationships.cypher (1347 relacionamentos)
✓ Gerado: relationships/create_reads_from_relationships.cypher (22998 relacionamentos)
✓ Gerado: relationships/create_writes_to_relationships.cypher (3220 relacionamentos)
```

### 2. Carregar no Neo4j

```bash
docker-compose up -d
```

O docker-compose irá:
1. Iniciar o Neo4j
2. Esperar o Neo4j ficar pronto
3. Limpar dados existentes (`clear_all_data.cypher`)
4. Criar constraints e nós (um arquivo por tipo)
5. Criar relacionamentos (um arquivo por tipo)

### 3. Acessar o Neo4j

- **URL**: http://localhost:7474
- **Usuário**: neo4j
- **Senha**: defaultpassword (configurável no `.env`)

## 📊 Formato do CSV

O CSV de entrada deve ter as seguintes colunas:

```csv
nome_pai,tipo_pai,tipo_relacionamento,nome_filho,tipo_filho
project.egp,EgpProject,READS_FROM,/path/lib.table,LibnameSource
project.egp,EgpProject,WRITES_TO,/output/result.table,LibnameSource
project.egp,EgpProject,DEPENDS_ON,/includes/macro.sas,IncludeFiles
```

### Colunas:
- **nome_pai**: Nome do nó pai (ex: nome do projeto .egp)
- **tipo_pai**: Label do nó pai no Neo4j (ex: `EgpProject`)
- **tipo_relacionamento**: Tipo do relacionamento (ex: `READS_FROM`, `WRITES_TO`, `DEPENDS_ON`)
- **nome_filho**: Nome do nó filho (ex: nome da tabela, arquivo)
- **tipo_filho**: Label do nó filho no Neo4j (ex: `LibnameSource`, `ExternalSource`, `IncludeFiles`)

### Observações:
- Os valores de `tipo_pai`, `tipo_filho` e `tipo_relacionamento` são usados **diretamente** no Neo4j
- Labels devem estar em PascalCase (ex: `EgpProject`, `LibnameSource`)
- Tipos de relacionamento devem estar em UPPER_SNAKE_CASE (ex: `READS_FROM`, `WRITES_TO`)

## 🔧 Propriedades dos Nós

Todos os nós têm propriedades simples:

```cypher
CREATE (n:EgpProject {
  name: 'project.egp',    -- Nome único do nó
  type: 'EgpProject'      -- Tipo original do CSV
});
```

## 🔍 Queries de Exemplo

### Encontrar projetos que leem de uma tabela específica
```cypher
MATCH (e:EgpProject)-[:READS_FROM]->(s {name: 'dba.tbproposta'})
RETURN e.name, s.name;
```

### Listar todas as dependências de um projeto
```cypher
MATCH (e:EgpProject {name: 'project.egp'})-[r]->(n)
RETURN type(r) as relationship, labels(n)[0] as node_type, n.name;
```

### Encontrar projetos que escrevem e outros que leem (linhagem)
```cypher
MATCH (p1:EgpProject)-[:WRITES_TO]->(t)<-[:READS_FROM]-(p2:EgpProject)
WHERE p1 <> p2
RETURN p1.name as producer, t.name as table, p2.name as consumer
LIMIT 50;
```

### Contar relacionamentos por tipo
```cypher
MATCH ()-[r]->()
RETURN type(r) as relationship_type, count(*) as count
ORDER BY count DESC;
```

### Encontrar projetos que usam arquivos include
```cypher
MATCH (e:EgpProject)-[:DEPENDS_ON]->(i:IncludeFiles)
RETURN e.name, i.name
LIMIT 50;
```

## 🎨 Benefícios da Refatoração

1. **Flexibilidade Total**
   - Adicionar novo tipo de nó no CSV → Funciona automaticamente
   - Adicionar novo tipo de relacionamento → Funciona automaticamente
   - Mudar nomenclatura → Basta atualizar o CSV

2. **Código Limpo**
   - ~200 linhas (vs ~350 antes)
   - Sem if/elif/else por tipo
   - Fácil de entender e manter

3. **Extensibilidade**
   - Adicionar novas colunas no CSV → Novas propriedades nos nós
   - Adicionar metadados → Basta incluir no CSV

4. **Compatibilidade**
   - Mantém estrutura de diretórios esperada pelo docker-compose
   - Um arquivo por tipo de nó/relacionamento
   - Constraints criados automaticamente

## ⚙️ Configuração

Edite as constantes no início do `csv_to_cypher.py`:

```python
# Configurações
CSV_FILE = "exemplo_de_modelagem.csv"  # CSV de entrada
OUTPUT_DIR = Path(".")                  # Diretório base
NODES_DIR = OUTPUT_DIR / "nodes"        # Scripts de nós
RELATIONSHIPS_DIR = OUTPUT_DIR / "relationships"  # Scripts de relacionamentos
```

## 🐛 Troubleshooting

### Erro: "Arquivo CSV não encontrado"
- Certifique-se de que `exemplo_de_modelagem.csv` está no diretório `sas_neo4j_setup/`

### Erro: "Nenhum nó válido encontrado"
- Verifique se o CSV tem as colunas corretas
- Verifique se não há linhas com valores vazios/nulos

### Docker-compose não carrega os scripts
- Verifique se os diretórios `nodes/` e `relationships/` existem
- Verifique se os arquivos `.cypher` foram gerados corretamente
- Verifique logs: `docker-compose logs cypher-loader`

### Neo4j não aceita os comandos Cypher
- Verifique se os nomes/propriedades estão escapados corretamente
- Verifique se há caracteres especiais problemáticos no CSV

## 📝 Changelog

### v2.0 (Atual - Data-Driven)
- ✅ Refatoração completa para abordagem data-driven
- ✅ Propriedades simples (name, type)
- ✅ Um arquivo por tipo de nó/relacionamento
- ✅ Compatibilidade com docker-compose.yml
- ✅ Script de limpeza de dados (`clear_all_data.cypher`)

### v1.0 (Anterior - Hardcoded)
- Lógica específica por tipo de nó
- Mapeamento manual de relacionamentos
- Propriedades complexas (project_name, project_path, etc.)

## 📚 Documentação Adicional

- [Neo4j Cypher Manual](https://neo4j.com/docs/cypher-manual/current/)
- [Neo4j Docker Image](https://hub.docker.com/_/neo4j)
- [Resumo da Análise do Grafo](../resumo_neo4j_analise.md)

## 👥 Time BV

Desenvolvido para o projeto de Migração SAS → Databricks
