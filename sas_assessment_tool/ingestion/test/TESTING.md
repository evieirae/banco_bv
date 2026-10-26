# 🧪 Guia de Testes - Pipeline de Ingestão

Este documento explica como executar os testes unitários para os scripts de ingestão.

**Localização dos Testes**: `ingestion/test/`

## 📋 Pré-requisitos

Instale as dependências de teste:

```bash
cd ingestion
pip install -r requirements.txt
```

**Nota**: Os testes devem ser executados a partir do diretório `ingestion/` para que os imports dos módulos (`sas_log_analyzer`, `regex_patterns`) funcionem corretamente.

## 🚀 Executando os Testes

**Importante**: Execute os testes a partir do diretório `ingestion/` (não de dentro de `test/`):

```bash
cd ingestion
```

### Executar Todos os Testes

```bash
# Executa todos os testes do diretório test/
pytest test/

# Com output verboso
pytest test/ -v

# Com output muito verboso
pytest test/ -vv
```

### Executar Testes Específicos

```bash
# Testes do analisador de logs
pytest test/test_sas_log_analyzer.py -v

# Testes dos padrões regex
pytest test/test_regex_patterns.py -v

# Teste específico
pytest test/test_sas_log_analyzer.py::TestSASLogAnalyzer::test_extract_session_info_full_pattern -v
```

### Executar com Cobertura

```bash
# Cobertura básica
pytest test/ --cov=sas_log_analyzer --cov=regex_patterns

# Cobertura com relatório HTML
pytest test/ --cov=sas_log_analyzer --cov=regex_patterns --cov-report=html

# Abrir relatório HTML (após gerar)
# Windows:
start htmlcov/index.html
# Linux/Mac:
open htmlcov/index.html
```

### Executar Testes em Modo Debug

```bash
# Para quando encontrar primeiro erro
pytest test/ -x

# Mostrar print statements
pytest test/ -s

# Combinado: verbose + stop on first failure + show prints
pytest test/ -vx -s
```

## 📊 Estrutura de Testes

Os testes estão localizados no diretório `ingestion/test/`:

```
ingestion/
├── test/
│   ├── test_sas_log_analyzer.py    # Testes do analisador de logs
│   ├── test_regex_patterns.py      # Testes dos padrões regex
│   └── TESTING.md                   # Este arquivo
├── sas_log_analyzer.py              # Módulo principal
├── regex_patterns.py                # Padrões regex
└── ...
```

### `test/test_sas_log_analyzer.py`

Testa as funções principais do `SASLogAnalyzer`:

- ✅ `extract_session_info()` - Extração de informações de sessão
- ✅ `extract_area()` - Extração de áreas SAS
- ✅ `extract_error_message()` - Extração de mensagens de erro
- ✅ `determine_type_process()` - Classificação de tipos de processo
- ✅ `extract_extended_performance_metrics()` - Métricas de performance
- ✅ `extract_database_objects_corrected()` - Objetos de banco de dados
- ✅ `detect_expensive_queries()` - Queries custosas
- ✅ `_is_delta_concurrency_error()` - Detecção de erros Delta Lake
- ✅ `_retry_with_backoff()` - Retry com exponential backoff

### `test/test_regex_patterns.py`

Testa os padrões regex centralizados:

- ✅ `PERFORMANCE_PATTERNS` - Padrões de performance
- ✅ `PROCESS_TYPE_PATTERNS` - Padrões de tipo de processo
- ✅ `AREA_PATTERNS` - Padrões de área
- ✅ `SESSION_INFO_PATTERNS` - Padrões de sessão
- ✅ `DATABASE_OBJECT_PATTERNS` - Padrões de objetos de banco
- ✅ `ERROR_PATTERNS` - Padrões de erro
- ✅ `EXPENSIVE_QUERY_PATTERNS` - Padrões de queries custosas

## 🎯 Exemplos de Uso

### Testar uma Função Específica

```bash
# Testar apenas extração de sessão
pytest test/test_sas_log_analyzer.py::TestSASLogAnalyzer::test_extract_session_info_full_pattern -v
```

### Testar com Arquivo de Log Real

Os testes de integração podem usar arquivos de log reais:

```python
# Exemplo de teste com arquivo real
def test_analyze_log_file_real(analyzer):
    result = analyzer.analyze_log_file("log_files/test.log")
    assert len(result['log_base']) > 0
```

### Adicionar Novo Teste

1. Abra o arquivo de teste correspondente em `test/`
2. Adicione um novo método de teste:

```python
def test_nova_funcao(self, analyzer):
    """Testa nova funcionalidade"""
    result = analyzer.nova_funcao("input")
    assert result == "expected_output"
```

3. Execute o teste:

```bash
pytest test/test_sas_log_analyzer.py::TestSASLogAnalyzer::test_nova_funcao -v
```

## 🔍 Troubleshooting

### Erro: "ModuleNotFoundError: No module named 'pytest'"

**Solução**: Instale pytest:
```bash
pip install pytest pytest-cov
```

### Erro: "ModuleNotFoundError: No module named 'sas_log_analyzer'"

**Solução**: Execute os testes a partir do diretório `ingestion` (não de dentro de `test/`):
```bash
cd ingestion
pytest test/
```

**Importante**: Os testes devem ser executados do diretório `ingestion/` para que os imports funcionem corretamente, pois os módulos `sas_log_analyzer` e `regex_patterns` estão no diretório pai.

### Testes Falhando

1. Verifique se as dependências estão instaladas
2. Verifique se está no diretório correto
3. Execute com `-v` para ver detalhes do erro
4. Execute com `-s` para ver prints de debug

## 📝 Notas

- Os testes **não requerem conexão com Databricks** (usam mocks)
- Os testes são **unitários** (testam funções isoladamente)
- Para testes de integração completos, seria necessário configurar um ambiente de teste Databricks

## 🎓 Próximos Passos

Para adicionar mais testes:

1. Identifique funções críticas que precisam de testes
2. Crie casos de teste para diferentes cenários (sucesso, erro, edge cases)
3. Execute os testes regularmente durante o desenvolvimento
4. Mantenha a cobertura de código acima de 80%

---

**Última atualização**: 2026-01-06

