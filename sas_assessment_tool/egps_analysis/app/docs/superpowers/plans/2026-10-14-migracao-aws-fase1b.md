# Migração para a AWS — Fase 1b (espelho fiel, dialeto, leitor) — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer cada tela do app na AWS mostrar o mesmo que o app do Databricks, sem controles de escrita para quem não grava, e deixar pronto o que falta para abrir ao BV (cadastro como leitor e critério do JIT).

**Architecture:** Na Fase 1 o Postgres guarda uma **cópia fiel** (schema `legado`) de cada tabela Delta que o app lê, e cada view `compat.<tabela>` só lê dessa cópia: o dado chega ao app exatamente como o Databricks o devolve. O código continua um só para os dois bancos; o SQL que o Postgres não entendia foi reescrito numa forma que roda igual nos dois. O critério de pronto é a comparação de leituras, tabela a tabela e rota a rota. O de-para para o schema novo, com as correções, fica para a Fase 2.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3, PostgreSQL 17, databricks-sdk, React/Vite/TypeScript, React Query.

Spec: [`../specs/2026-10-14-migracao-aws-design.md`](../specs/2026-10-14-migracao-aws-design.md) · ADR: [`docs/adr/0005-app-sai-do-databricks.md`](../../../../../docs/adr/0005-app-sai-do-databricks.md) · Plano anterior: [`2026-10-14-migracao-aws-fase1a.md`](2026-10-14-migracao-aws-fase1a.md)

---

## A decisão que muda a spec (14/10/2026)

A spec mandava a sincronização da Fase 1 **transformar** cada tabela para o schema novo e a view `compat` remontar o formato antigo. O inventário de prod de 14/10 mostrou que, para as ~33 tabelas restantes, isso exigiria modelar e depois remontar byte a byte muito caso especial:
- 17 colunas de data/hora guardadas como texto, com 3 a 6 casas de fração;
- 8 auditorias com 8 formatos;
- chaves `familia::` em 4 tabelas;
- 16 recebimentos que apontam para outputs que não existem;
- nomes de Responsável BV fora do cadastro;
- JSON de configuração e do plano.

**Decisão (do usuário, 14/10):** na Fase 1, essas tabelas entram como **cópia fiel** em `legado`, e o de-para com as correções vai para a Fase 2, grupo a grupo, que é onde a spec já punha as correções.
- **O que fica como estava:** as 5 tabelas do 1a continuam sendo normalizadas também. Elas servem ao cadastro e às âncoras, e são o começo da Fase 2.
- **O que muda nas duas views do 1a:** `compat.sas_inputs_monitor` e `compat.sas_egp_inputs` passam a ler o espelho, como todas. Assim o app mostra o `escopo_indi` que o Databricks gravou, e não um derivado.
- **O que se perde:** a auditoria de integridade (FKs) sai da Fase 1 e vai para a Fase 2.

## O que já rodou (14/10/2026, numa cópia de rascunho da branch do 1a com a `main` mesclada)

| Prova | Resultado |
|---|---|
| Sincronização real de prod (só leitura no Databricks) num Postgres 17 local | 33 tabelas espelhadas + as 5 normalizadas numa transação; **32 s**, pico de **198 MB** (a tarefa tem 2 GB) |
| `paridade.tabelas`: cada view `compat` × a tabela Delta de prod, célula a célula, no formato que o app recebe | **33/33 iguais** (~125 mil linhas) |
| `paridade.compara`: app em modo Databricks × app em modo Postgres, os dois locais e lendo o schema de **dev** | **82/82 rotas iguais**: as 48 rotas GET e 34 chamadas com amostra de parâmetro e de filtro |
| Chave de família no Postgres × regra em Python, sobre todos os artefatos reais | **0 divergências** em 13.069 |
| Testes | backend 717 + 18 do SQL portável; db/sync/paridade/treino 64; front: regra de escrita 6 casos, `tsc` e build verdes |

Antes das correções de dialeto, 31 das 48 rotas já saíam iguais; cada correção abaixo saiu de uma diferença real dessa comparação.

**Partes A–E executadas em 14/10 na branch `feat/aws-migration-phase1b`, sem commit.** O merge da `main` está preparado à parte, para virar o próprio commit. Cada task seguiu o passo a passo deste plano: o teste falhou onde ele diz e passou depois. As provas foram refeitas a partir da branch e deram o mesmo resultado:
- **E1:** 33/33 tabelas;
- **E2:** 82/82 rotas, com as mesmas exceções previstas;
- **testes:** 799 em Python; no front, build e os 12 `*.test.mts` verdes.

Faltam as Partes F e G (dependem do apply da infra e do login) e o resto da H.

## Escopo deste plano

**Entra:** espelho fiel e sua sincronização; port de dialeto das rotas GET; comparadores; front sem controles de escrita para leitor e modo leitura; subida na AWS (dev e prod) com a comparação de tabelas lá; cadastro do BV e critério do JIT.

**Não entra:**
- **Escrita no Postgres e o de-para com correções:** ficam para a Fase 2.
- **Rotas de propósito fora:** `sas_egp_prioridades`, que a spec diz que não migra (a rota `/api/prioridades` fica fora da comparação), e a rotina de consulta (ADR 0004), que fica desligada no Postgres.
- **O login do Google:** segue pendente da PR `gcloud/monitoramento-sas-auth`. Abrir ao BV (Parte G) depende de ter login.

## Regras (não negociáveis)

- **Commit e push só quando o usuário pedir.** Mensagem em português, **sem** `Co-Authored-By`. Branch em inglês.
- **Deploy e escrita em prod só com consentimento explícito** do usuário, a cada vez. Ler prod no Databricks é permitido (a sincronização e a comparação só leem).
- **Bash: um comando por chamada** (regra da organização). Pipe pode; `&&` e `;` não. `curl` não: use `urllib`.
- O app local roda contra o schema de **dev** do Databricks, nunca o de prod (`local_app.sh` recusa). Algumas rotas GET gravam no Databricks (o log diário de sanitização): contra o dev isso é o uso normal; contra prod, não.
- Dado do BV fica fora da training. O Postgres local da comparação é descartado no fim (Task E2).
- Branch do app: `feat/aws-migration-phase1b`, a partir de `feat/aws-migration-phase1a` com a `main` mesclada.

## Mapa de arquivos (`egps_analysis/app/`)

| Arquivo | Responsabilidade |
|---|---|
| `sync/espelho_tabelas.py` (novo) | Colunas e tipos Delta das 33 tabelas espelhadas (fonte única) |
| `sync/espelho.py` (novo) | Conversão texto → tipo, montagem e carga do espelho |
| `sync/test_espelho.py` (novo) | Conversão, cobertura das tabelas do backend, ida e volta pelo `compat`, papéis |
| `db/migrations/0005_legado_espelho.sql` (novo) | Schema `legado`, as 33 tabelas, as views `compat`, `instr`/`regexp_extract`, grants |
| `sync/leitor.py`, `retrato.py`, `carrega.py`, `sincroniza.py` (modificar) | Ler todas as colunas (instante como texto), espelhar na mesma transação, conferir o fuso |
| `sync/sintetico.py`, `sync/test_sync.py` (modificar) | Massas com o `escopo_indi` gravado e instantes no formato lido |
| `db/migra.py`, `db/test_migra.py` (modificar) | Recusar banco cujo `upper()` não entende acento |
| `backend/main.py`, `familias.py`, `egps_atualizados.py` (modificar) | SQL que roda igual nos dois bancos; nada de escrita em GET no Postgres |
| `backend/test_sql_portavel_pg.py` (novo) | O SQL portável conferido num Postgres de verdade |
| `paridade/tabelas.py`, `test_tabelas.py` (novos) | Comparação tabela a tabela, célula a célula |
| `paridade/compara.py`, `test_compara.py` (modificar), `paridade/amostras.py` (novo) | Listas sem ordem na origem, diferenças por desenho, mesmo erro, rotas com amostra |
| `frontend/src/escrita.ts`, `usePodeEscrever.ts`, `escrita.test.mts` (novos) | Quem vê controle de escrita |
| `frontend/src/api.ts`, `App.tsx` e 14 componentes (modificar) | Tipar o papel, semear o cache, esconder/desabilitar os controles |

## Decisões de implementação

1. **Espelho sem restrição.** As tabelas de `legado` não têm PK, FK nem `NOT NULL`. O Delta não tem nenhuma, e a cópia não pode recusar o que o Databricks aceitou. A view `compat.<tabela>` é um `SELECT` das colunas, sem transformar nada.
2. **Tipos.** `string`→`text`, `int`→`integer`, `bigint`→`bigint`, `double`→`double precision`, `boolean`→`boolean`, `timestamp`→`timestamp` **sem fuso, em UTC**.
   - **Por que sem fuso:** assim `CAST(x AS STRING)` no Postgres sai igual ao do Spark, e o driver devolve `AAAA-MM-DDTHH:MM:SS.mmmZ`, como o JSON do Databricks.
   - **Por que o instante é lido como texto:** a sincronização usa `CAST(x AS STRING)`, porque o JSON do Databricks corta em milissegundos e o texto guarda os micros.
   - **Guarda:** a sincronização para se a sessão do Databricks não estiver em UTC.
3. **Uma leitura por tabela.** As 5 tabelas do 1a também são espelhadas: a mesma leitura serve ao espelho e ao de-para delas.
4. **Toda tabela que o backend cita** (nome montado sobre o schema do app) está no espelho ou em `FORA_DO_ESPELHO`, com o motivo. Um teste recusa o esquecimento, porque no Postgres ele viraria resposta vazia em silêncio (`_objeto_ausente`).
5. **Dialeto.**
   - **SQL reescrito** numa forma que roda igual nos dois bancos:
     - `element_at(split(..), 1)` no lugar de `split(..)[0]`;
     - `_lista_tem_algum` no lugar de lambda com `array()`;
     - `NULLS FIRST/LAST` explícito, com a regra do Spark;
     - desempate no `ORDER BY` antes de `LIMIT`;
     - `current_date` sem parênteses.
   - **Funções novas em `compat`:** `instr` e `regexp_extract`.
   - **Escrita em GET:** desligada no Postgres (log diário de sanitização e congelamento automático do plano), porque na Fase 1 quem grava é o Databricks.
6. **Comparação.**
   - **Duas camadas:** tabelas (prova a cópia) e rotas (prova o dialeto).
   - **Lista sem ordem definida na origem** (`set` do Python, SQL sem `ORDER BY`) é comparada como conjunto, e cada caso diz por quê.
   - **Diferença por desenho** (nome do schema, papel, modo leitura) sai à parte, com o motivo.
   - **Mesmo erro HTTP nos dois lados** é comportamento igual.
7. **Front.**
   - **Uma regra só:** `podeEscrever(cfg, me)` = não está em modo leitura **e** o papel não é `leitor`.
   - **Como aparece:** botão de ação some; campo que mostra valor fica desabilitado, e o valor continua legível.
   - **No Databricks nada muda:** o `/api/me` não traz papel e o modo leitura é falso.
8. **Caixa de texto.** A collation C não muda o `upper()`, que segue o `LC_CTYPE` do banco. O `migra` recusa banco onde `upper('ç')` não dá `'Ç'`, porque a regra de família (MARÇO, ABRIL) daria chave diferente da do Spark, sem erro.

## Preparação (uma vez)

- [ ] Branch a partir do 1a, com a `main` do momento:

```bash
git fetch origin main feat/aws-migration-phase1a
```

```bash
git switch -c feat/aws-migration-phase1b origin/feat/aws-migration-phase1a
```

```bash
git merge origin/main
```

Em 14/10 o merge foi automático (só o fix das tabelas DOR1 entrou), sem conflito. Se a `main` tiver andado, resolva os conflitos e rode a suíte do backend antes de seguir. **As linhas citadas abaixo são da branch do 1a com esse merge: procure pelo conteúdo.**

- [ ] Postgres 17 local, como no 1a (`docker run -d --name pg17-monitoramento -e POSTGRES_HOST_AUTH_METHOD=trust -p 127.0.0.1:55432:5432 postgres:17`). Nos testes, `PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres`.

Os comandos abaixo rodam a partir de `egps_analysis/app`, com o `.venv` do app (`.venv/bin/python`; `PY` nos exemplos).

---

## Parte A — Espelho fiel

### Task A1: Lista de colunas, módulo do espelho e migração 0005

**Files:**
- Create: `sync/espelho_tabelas.py`, `sync/espelho.py`, `db/migrations/0005_legado_espelho.sql`
- Test: `sync/test_espelho.py`

- [ ] **Step 1: Teste**

```python
# -*- coding: utf-8 -*-
"""Espelho fiel: o que o Databricks devolve tem de voltar igual pela view compat."""
import datetime
import os
import pathlib
import re
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import migra  # noqa: E402
from sync import espelho  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
precisa_pg = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend"

# Tabelas que o backend cita e que NÃO são espelhadas, com o motivo. Tabela nova no app tem
# de entrar no espelho (sync/espelho_tabelas.py + migração) ou aqui — o teste abaixo recusa
# o esquecimento, que no Postgres viraria resposta vazia em silêncio (_objeto_ausente).
FORA_DO_ESPELHO = {
    "sas_egp_prioridades": "não migra (spec): rotas sem tela",
    "sas_consulta_egp": "não migra (ADR 0004): rotina de consulta fica desligada no Postgres",
    "sas_consulta_egp_dia": "idem",
    "sas_consulta_input": "idem",
    "sas_consulta_input_dia": "idem",
    "sas_pipeline_metrics": "nenhuma rota GET lê; só o publish escreve",
    "sas_resumo_proj": "só o recompute de escopo (escrita) lê",
    "sas_egp_dep_mantida_audit": "só escrita",
    "sas_egp_input_periodo_audit": "só escrita",
    "sas_familia_ingestao_audit": "só escrita",
    "sas_egp_atualizados_audit": "só escrita (PATCH da aba aposentada)",
}


# ------------------------------------------------------------------ conversão
def test_texto_fica_como_veio_inclusive_vazio():
    assert espelho.converte("string", "") == "" and espelho.converte("string", " a ") == " a "
    assert espelho.converte("string", None) is None


def test_numeros_booleanos_e_instantes():
    assert espelho.converte("int", "7") == 7 and espelho.converte("bigint", "10233") == 10233
    assert espelho.converte("double", "100.0") == 100.0
    assert espelho.converte("boolean", "false") is False
    assert espelho.converte("timestamp", "2026-06-16 15:53:59.840271") == \
        datetime.datetime(2026, 6, 16, 15, 53, 59, 840271)
    assert espelho.converte("timestamp", "2026-10-14T15:28:33.607Z") == \
        datetime.datetime(2026, 10, 14, 15, 28, 33, 607000)


def test_valor_fora_do_previsto_para_a_sincronizacao():
    with pytest.raises(espelho.ValorInesperado):
        espelho.converte("boolean", "sim")
    with pytest.raises(espelho.ValorInesperado):
        espelho.converte("timestamp", "2026-06-16 15:53:59-03:00")
    with pytest.raises(espelho.ValorInesperado):
        espelho.converte("array<string>", "[]")


def test_selecao_le_instante_como_texto():
    sel = dict(zip(espelho.colunas("sas_inputs_audit"), espelho.selecao("sas_inputs_audit")))
    assert sel["updated_at"] == "CAST(updated_at AS STRING) AS updated_at"
    assert sel["campo"] == "campo"


def test_monta_tabela_ausente_vazia_e_coluna_ausente_nula():
    m = espelho.monta({"sas_funil_area": [{"area": "Cobrança", "qtd_dor1": "168"}]})
    assert m["sas_funil_area"] == [("Cobrança", 168, None, None)]
    assert m["sas_escopo"] == [] and len(m) == len(espelho.TABELAS)


def test_toda_tabela_do_backend_esta_no_espelho_ou_tem_motivo():
    citadas = set()
    for p in BACKEND.glob("*.py"):    # tabela de verdade = nome montado sobre o schema do app
        if not p.name.startswith("test_"):
            citadas |= set(re.findall(r"\{(?:FQ|fq)\}\.(sas_[a-z0-9_]+)", p.read_text(encoding="utf-8")))
    assert len(citadas) > 30          # o padrão ainda acha as tabelas (sanidade do próprio teste)
    sem_destino = citadas - set(espelho.TABELAS) - set(FORA_DO_ESPELHO)
    assert not sem_destino, f"tabelas sem espelho nem motivo: {sorted(sem_destino)}"


# ------------------------------------------------------------------ banco
@pytest.fixture
def banco():
    import psycopg
    nome = "t_esp_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    dsn = f"{base}/{nome}"
    migra.aplica(dsn, saida=lambda *_: None)
    yield dsn
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


@precisa_pg
def test_legado_bate_com_a_lista(banco):
    import psycopg
    with psycopg.connect(banco) as c:
        for t in espelho.TABELAS:
            cols = c.execute("SELECT column_name, data_type FROM information_schema.columns "
                             "WHERE table_schema = 'legado' AND table_name = %s ORDER BY ordinal_position",
                             (t,)).fetchall()
            esperado = [(col, "timestamp without time zone" if tipo == "timestamp" else espelho.TIPO_PG[tipo])
                        for col, tipo in espelho.TABELAS[t]]
            assert cols == esperado, t
            vcols = [r[0] for r in c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'compat' "
                "AND table_name = %s ORDER BY ordinal_position", (t,))]
            assert vcols == list(espelho.colunas(t)), f"compat.{t}"


def _amostra(tipo, i):
    """Uma célula como o Databricks devolve; varia entre linhas para cobrir '' e NULL."""
    return {"string": ("texto", "", None)[i % 3], "int": ("7", None, "0")[i % 3],
            "bigint": "10233", "double": ("87.5", "100.0", None)[i % 3],
            "boolean": ("true", "false", None)[i % 3],
            "timestamp": ("2026-06-16 15:53:59.840271", "2026-06-23 17:37:46", None)[i % 3]}[tipo]


@precisa_pg
def test_ida_e_volta_pelo_compat_sai_como_no_databricks(banco):
    """Célula pela view compat, formatada pelo driver do app (db_pg.texto), tem de ser o texto
    que o Databricks devolveria. Instante: o JSON do Databricks sai em ms com 'Z', e
    CAST(x AS STRING) sai com os micros, sem fuso — os dois iguais aos do Spark."""
    import psycopg
    import db_pg
    linhas = {t: [{c: _amostra(tipo, i) for c, tipo in cols} for i in range(3)]
              for t, cols in espelho.TABELAS.items()}
    with psycopg.connect(banco) as conn:
        with conn.transaction(), conn.cursor() as cur:
            espelho.carrega(cur, espelho.monta(linhas))
        conn.execute("SET search_path = compat, derivado, pg_catalog, public")
        json_do_databricks = {"2026-06-16 15:53:59.840271": "2026-06-16T15:53:59.840Z",
                              "2026-06-23 17:37:46": "2026-06-23T17:37:46.000Z", None: None}
        for t, cols in espelho.TABELAS.items():
            lidas = [tuple(db_pg.texto(v) for v in r) for r in conn.execute(f"SELECT * FROM compat.{t}")]
            esperadas = [tuple(json_do_databricks[r[c]] if tipo == "timestamp" else r[c]
                               for c, tipo in cols) for r in linhas[t]]
            chave = lambda x: repr(x)  # noqa: E731
            assert sorted(lidas, key=chave) == sorted(esperadas, key=chave), t
        ts = sorted((r[0] or "") for r in conn.execute(
            "SELECT CAST(updated_at AS STRING) FROM compat.sas_inputs_audit"))
        assert ts == ["", "2026-06-16 15:53:59.840271", "2026-06-23 17:37:46"]


@precisa_pg
def test_so_a_sincronizacao_regrava_o_legado(banco):
    import psycopg
    papel = "t_esp_" + uuid.uuid4().hex[:6]
    with psycopg.connect(banco, autocommit=True) as adm:
        adm.execute(f"CREATE ROLE {papel} LOGIN IN ROLE sincronizador")
    try:
        with psycopg.connect(banco) as conn:
            conn.execute(f"SET ROLE {papel}")
            with conn.transaction(), conn.cursor() as cur:
                espelho.carrega(cur, espelho.monta({"sas_funil_area": [{"area": "X", "qtd_dor1": "1"}]}))
        with psycopg.connect(banco) as conn:
            conn.execute("SET ROLE app_leitura")
            assert conn.execute("SELECT area FROM compat.sas_funil_area").fetchall() == [("X",)]
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("DELETE FROM legado.sas_funil_area")
    finally:
        with psycopg.connect(banco, autocommit=True) as adm:
            adm.execute(f"DROP OWNED BY {papel}")
            adm.execute(f"DROP ROLE {papel}")


@precisa_pg
def test_funcoes_do_spark_que_faltavam(banco):
    import psycopg
    with psycopg.connect(banco) as c:
        c.execute("SET search_path = compat, derivado, pg_catalog, public")
        assert c.execute("SELECT instr('a | B | c', 'B'), instr('abc', 'z'), instr(NULL, 'a')").fetchone() \
            == (5, 0, None)
        assert c.execute("SELECT regexp_extract('tabela::X', '^([^:]+)::', 1), "
                         "regexp_extract('sem', '^([^:]+)::', 1), regexp_extract(NULL, 'a', 1)").fetchone() \
            == ("tabela", "", None)
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q sync/test_espelho.py
```

Esperado: `ImportError: cannot import name 'espelho' from 'sync'`.

- [ ] **Step 3: Lista de colunas.** Gerada do `DESCRIBE TABLE` de prod em 14/10 (33 tabelas, 319 colunas). Coluna nova numa tabela espelhada entra aqui e numa migração nova, na mesma PR.

```python
# -*- coding: utf-8 -*-
"""Colunas e tipos Delta das 33 tabelas espelhadas, na ordem do DESCRIBE de prod (14/10/2026).

Gerado a partir do schema real (`DESCRIBE TABLE` em bv_dev_db.monitoramento_sas) e revisado.
Coluna nova numa tabela espelhada entra AQUI e na migração do schema `legado`, na mesma PR;
o teste test_espelho.test_legado_bate_com_a_lista confere as duas.
"""

TABELAS = {
    "sas_inputs_monitor": (
        ("chave_canonica", "string"),
        ("artifact", "string"),
        ("categoria", "string"),
        ("source_types", "string"),
        ("qtd_projetos", "int"),
        ("areas", "string"),
        ("escopo_indi", "boolean"),
        ("modernizada_auto", "string"),
        ("status_humano", "string"),
        ("responsavel", "string"),
        ("observacao", "string"),
        ("updated_at", "timestamp"),
        ("updated_by", "string"),
        ("orfao", "boolean"),
        ("refreshed_at", "timestamp"),
        ("origem", "string"),
        ("paths_fisicos", "string"),
        ("n_paths_fisicos", "int"),
        ("etapa", "string"),
        ("status", "string"),
    ),
    "sas_egp_inputs": (
        ("projeto", "string"),
        ("area", "string"),
        ("onda", "string"),
        ("escopo_indi", "boolean"),
        ("ciclo_id", "int"),
        ("chave_canonica", "string"),
        ("artifact", "string"),
        ("categoria", "string"),
        ("source_types", "string"),
        ("modernizada_auto", "string"),
    ),
    "sas_lineage_nodes": (
        ("projeto", "string"),
        ("area", "string"),
        ("onda", "string"),
        ("n_inputs", "int"),
        ("n_outputs", "int"),
        ("escopo_indi", "boolean"),
        ("ciclo_id", "int"),
        ("loc", "int"),
        ("code_tasks_count", "int"),
        ("n_outputs_avaliados", "int"),
        ("n_outputs_consumidos_por_outro_egp", "int"),
        ("pct_outputs_consumidos_por_outro_egp", "double"),
        ("n_egps_consumidores", "int"),
        ("n_exports_arquivos", "int"),
        ("flag_output_100pct_egp", "boolean"),
        ("flag_algum_output_egp", "boolean"),
        ("flag_sem_export_arquivo", "boolean"),
        ("flag_output_unico", "boolean"),
        ("flag_hub_multiplos_consumidores", "boolean"),
    ),
    "sas_lineage_edges": (
        ("projeto_alvo", "string"),
        ("depende_do", "string"),
        ("via_tabelas", "string"),
        ("qtd_via", "int"),
        ("max_produtores", "int"),
    ),
    "sas_egp_outputs": (
        ("projeto", "string"),
        ("area", "string"),
        ("onda", "string"),
        ("escopo_indi", "boolean"),
        ("chave_canonica", "string"),
        ("artifact", "string"),
        ("categoria", "string"),
        ("apenas_contribui", "boolean"),
    ),
    "sas_outputs_monitor": (
        ("chave_canonica", "string"),
        ("artifact", "string"),
        ("categoria", "string"),
        ("areas", "string"),
        ("qtd_produtores", "int"),
        ("qtd_criadores", "int"),
        ("qtd_consumidores", "int"),
        ("terminal", "boolean"),
        ("modernizada_auto", "string"),
        ("escopo_indi", "boolean"),
        ("paths_fisicos", "string"),
    ),
    "sas_resumo_inputs": (
        ("chave_canonica", "string"),
        ("area_principal", "string"),
        ("origem_bucket", "string"),
        ("escopo_indi", "boolean"),
        ("modernizada_auto", "string"),
    ),
    "sas_funil_area": (
        ("area", "string"),
        ("qtd_dor1", "int"),
        ("egps_enviados", "int"),
        ("egps_analisados", "int"),
    ),
    "sas_escopo": (
        ("id", "string"),
        ("egp_dor1", "string"),
        ("area", "string"),
        ("status_extracao", "string"),
        ("projeto", "string"),
        ("origem", "string"),
        ("created_by", "string"),
        ("created_at", "string"),
        ("ativo", "boolean"),
    ),
    "sas_egp_pipeline": (
        ("projeto", "string"),
        ("etapa_migracao", "string"),
        ("status_migracao", "string"),
        ("etapa_progresso", "string"),
        ("status_progresso", "string"),
        ("updated_by", "string"),
        ("updated_at", "string"),
        ("responsavel", "string"),
        ("mes_prioridade", "int"),
        ("jira_id", "string"),
        ("responsavel_bv", "string"),
        ("preworking_preenchido", "string"),
        ("preworking_data", "string"),
        ("egp_atualizado_key", "string"),
        ("egp_vinculo_tipo", "string"),
        ("egp_sucessor", "string"),
    ),
    "sas_egp_input_link": (
        ("projeto", "string"),
        ("chave_canonica", "string"),
        ("link_broken", "boolean"),
        ("updated_by", "string"),
        ("updated_at", "timestamp"),
    ),
    "sas_egp_dep_mantida": (
        ("projeto", "string"),
        ("chave_canonica", "string"),
        ("motivo", "string"),
        ("updated_by", "string"),
        ("updated_at", "timestamp"),
    ),
    "sas_output_producer_choice": (
        ("chave_canonica", "string"),
        ("projeto_escolhido", "string"),
        ("chosen_by", "string"),
        ("chosen_at", "string"),
    ),
    "sas_outputs_pipeline": (
        ("chave_canonica", "string"),
        ("recebido", "string"),
        ("recebido_data", "string"),
        ("updated_by", "string"),
        ("updated_at", "string"),
        ("carga_fria", "string"),
        ("cf_etapa", "string"),
        ("cf_status", "string"),
        ("cf_responsavel", "string"),
        ("cf_inicio", "string"),
        ("cf_fim", "string"),
        ("cf_caminho", "string"),
        ("cf_tabela", "string"),
    ),
    "sas_inputs_preworking": (
        ("chave_canonica", "string"),
        ("origem_arquivo", "string"),
        ("frequencia", "string"),
        ("horario", "string"),
        ("tipo_carga", "string"),
        ("pos_processamento", "string"),
        ("dados_sensiveis", "string"),
        ("updated_by", "string"),
        ("updated_at", "string"),
        ("recebido", "string"),
        ("data_recebimento", "string"),
        ("modernizado_bv", "string"),
        ("data_modernizado_bv", "string"),
        ("iniciado_em", "string"),
        ("concluido_em", "string"),
    ),
    "sas_egp_input_periodo": (
        ("projeto", "string"),
        ("categoria", "string"),
        ("familia", "string"),
        ("tipo", "string"),
        ("valor", "string"),
        ("updated_by", "string"),
        ("updated_at", "timestamp"),
    ),
    "sas_familia_ingestao": (
        ("categoria", "string"),
        ("familia", "string"),
        ("desde", "string"),
        ("ingerida_em", "string"),
        ("updated_by", "string"),
        ("updated_at", "timestamp"),
    ),
    "sas_app_config": (
        ("chave", "string"),
        ("valor", "string"),
        ("updated_by", "string"),
        ("updated_at", "string"),
    ),
    "sas_priorizacao_snapshot": (
        ("id", "string"),
        ("payload", "string"),
        ("capacidade", "int"),
        ("saved_by", "string"),
        ("saved_at", "string"),
    ),
    "sas_gestao_status": (
        ("id", "string"),
        ("entity", "string"),
        ("entity_id", "string"),
        ("autor", "string"),
        ("criado_por", "string"),
        ("ts", "string"),
        ("texto", "string"),
    ),
    "sas_gestao_datas": (
        ("entity", "string"),
        ("entity_id", "string"),
        ("inicio", "string"),
        ("fim_conversao", "string"),
        ("fim", "string"),
        ("updated_by", "string"),
        ("updated_at", "string"),
    ),
    "sas_gestao_bv": (
        ("id", "string"),
        ("entity", "string"),
        ("entity_id", "string"),
        ("com_bv", "boolean"),
        ("data", "string"),
        ("autor", "string"),
        ("ts", "string"),
    ),
    "sas_gestao_revisao": (
        ("entity", "string"),
        ("entity_id", "string"),
        ("contador", "int"),
        ("updated_by", "string"),
        ("updated_at", "string"),
    ),
    "sas_inputs_audit": (
        ("chave_canonica", "string"),
        ("campo", "string"),
        ("valor_antigo", "string"),
        ("valor_novo", "string"),
        ("updated_by", "string"),
        ("updated_at", "timestamp"),
    ),
    "sas_pipeline_audit": (
        ("id", "string"),
        ("projeto", "string"),
        ("funil", "string"),
        ("campo", "string"),
        ("valor_antigo", "string"),
        ("valor_novo", "string"),
        ("ator", "string"),
        ("ts", "string"),
    ),
    "sas_escopo_audit": (
        ("id", "string"),
        ("acao", "string"),
        ("egp_dor1", "string"),
        ("projeto", "string"),
        ("ator", "string"),
        ("ts", "string"),
    ),
    "sas_egp_input_link_audit": (
        ("id", "string"),
        ("projeto", "string"),
        ("chave_canonica", "string"),
        ("campo", "string"),
        ("valor_antigo", "string"),
        ("valor_novo", "string"),
        ("ator", "string"),
        ("ts", "timestamp"),
    ),
    "sas_egp_atualizados": (
        ("versao_id", "string"),
        ("egp_key", "string"),
        ("nome", "string"),
        ("area", "string"),
        ("arquivo", "string"),
        ("arquivo_hash", "string"),
        ("origem", "string"),
        ("egp_original", "string"),
        ("n_antecessores", "int"),
        ("confianca_par", "string"),
        ("overlap_tasks", "double"),
        ("autor_ultimo_save", "string"),
        ("login_autor", "string"),
        ("data_ultimo_save", "string"),
        ("data_criacao", "string"),
        ("data_recebimento", "string"),
        ("valor", "double"),
        ("esforco", "double"),
        ("razao", "double"),
        ("quadrante", "string"),
        ("n_vetos", "int"),
        ("vetos", "string"),
        ("alertas", "string"),
        ("table_in_antigo", "int"),
        ("table_in_novo", "int"),
        ("a_ingerir_antigo", "int"),
        ("a_ingerir_novo", "int"),
        ("disponivel_antigo", "int"),
        ("disponivel_novo", "int"),
        ("file_in_antigo", "int"),
        ("file_in_novo", "int"),
        ("script_in_antigo", "int"),
        ("script_in_novo", "int"),
        ("outputs_antigo", "int"),
        ("outputs_novo", "int"),
        ("outputs_removidos_com_consumidor", "int"),
        ("outputs_removidos_privados", "int"),
        ("inputs_macro_nao_resolvido", "int"),
        ("inputs_rede_novos", "int"),
        ("deps_novas", "int"),
        ("loc_antigo", "int"),
        ("loc_novo", "int"),
        ("linhas_add", "int"),
        ("linhas_rem", "int"),
        ("tasks_novas", "int"),
        ("alcance_total", "int"),
        ("alcance_por_grafo", "int"),
        ("alcance_por_output", "int"),
        ("status_troca", "string"),
        ("publicado_por", "string"),
        ("publicado_em", "timestamp"),
    ),
    "sas_egp_atualizados_inputs": (
        ("versao_id", "string"),
        ("chave_canonica", "string"),
        ("artefato", "string"),
        ("categoria", "string"),
        ("source", "string"),
        ("situacao_no_recebimento", "string"),
        ("novo", "boolean"),
        ("publicado_em", "timestamp"),
    ),
    "sas_egp_atualizados_outputs": (
        ("versao_id", "string"),
        ("chave_canonica", "string"),
        ("artefato", "string"),
        ("situacao", "string"),
        ("novo", "boolean"),
        ("removido", "boolean"),
        ("n_consumidores_externos", "int"),
        ("publicado_em", "timestamp"),
        ("padrao", "boolean"),
        ("categoria", "string"),
    ),
    "sas_egp_atualizados_pipeline": (
        ("egp_key", "string"),
        ("etapa", "string"),
        ("status", "string"),
        ("responsavel", "string"),
        ("updated_by", "string"),
        ("updated_at", "timestamp"),
        ("responsavel_bv", "string"),
        ("tipo_vinculo", "string"),
    ),
    "sas_analistas": (
        ("email", "string"),
        ("nome", "string"),
        ("ativo", "boolean"),
        ("created_by", "string"),
        ("created_at", "string"),
        ("updated_by", "string"),
        ("updated_at", "string"),
        ("organograma", "boolean"),
        ("papel", "string"),
    ),
    "sas_responsaveis_bv": (
        ("nome_key", "string"),
        ("nome", "string"),
        ("subarea", "string"),
        ("ativo", "boolean"),
        ("created_by", "string"),
        ("created_at", "string"),
        ("updated_by", "string"),
        ("updated_at", "string"),
    ),
}
```

- [ ] **Step 4: Módulo do espelho**

```python
# -*- coding: utf-8 -*-
"""Espelho fiel das tabelas Delta que o app lê (ADR 0005, Fase 1 — decisão de 14/10/2026).

Na Fase 1 o Databricks é a fonte da verdade e o app na AWS só lê. As tabelas que o app lê
entram no Postgres como CÓPIA FIEL no schema `legado` — mesmas colunas, mesmos tipos, mesmos
valores, inclusive '' x NULL e os instantes que o Databricks guarda como texto — e cada view
`compat.<tabela>` só lê de lá. Assim a resposta da API sai igual à do Databricks por
construção. O de-para com correções para o schema novo é da Fase 2, grupo a grupo; as 5
tabelas do 1a continuam sendo normalizadas também (cadastro, âncoras, início da Fase 2).

Tipos: string -> text, int -> integer, bigint -> bigint, double -> double precision,
boolean -> boolean, timestamp -> timestamp SEM fuso, em UTC. Sem fuso porque assim
`CAST(x AS STRING)` no Postgres sai igual ao do Spark e o driver devolve
AAAA-MM-DDTHH:MM:SS.mmmZ, como o JSON do Databricks. O TIMESTAMP é LIDO como
`CAST(x AS STRING)`: o JSON do Databricks corta em milissegundos; o texto guarda os micros.
"""
import datetime

from .espelho_tabelas import TABELAS

TIPO_PG = {"string": "text", "int": "integer", "bigint": "bigint", "double": "double precision",
           "boolean": "boolean", "timestamp": "timestamp"}


class ValorInesperado(ValueError):
    pass


def colunas(tabela):
    return tuple(c for c, _ in TABELAS[tabela])


def selecao(tabela):
    """Expressões do SELECT no Databricks, na ordem de colunas(tabela)."""
    return tuple(f"CAST({c} AS STRING) AS {c}" if t == "timestamp" else c for c, t in TABELAS[tabela])


def converte(tipo, v):
    """Texto do Databricks -> valor Python do tipo da coluna em `legado`. Texto fica como veio."""
    if v is None:
        return None
    if tipo == "string":
        return v
    if tipo in ("int", "bigint"):
        return int(v)
    if tipo == "double":
        return float(v)
    if tipo == "boolean":
        if v in ("true", "false"):
            return v == "true"
        raise ValorInesperado(f"booleano inesperado: {v!r}")
    if tipo == "timestamp":
        d = datetime.datetime.fromisoformat(v)      # 'AAAA-MM-DD HH:MM:SS[.ffffff]', sessão em UTC
        if d.tzinfo is not None:                    # 'Z' (formato JSON) também é UTC
            if d.utcoffset() != datetime.timedelta(0):
                raise ValorInesperado(f"instante fora de UTC: {v!r}")
            d = d.replace(tzinfo=None)
        return d
    raise ValorInesperado(f"tipo Delta não previsto: {tipo!r}")


def monta(linhas):
    """`linhas`: tabela Delta -> lista de dicts (texto). Devolve tabela -> lista de tuplas na
    ordem de colunas(). Tabela ausente vira lista vazia (a massa sintética só traz algumas);
    coluna ausente vira NULL."""
    saida = {}
    for t, cols in TABELAS.items():
        saida[t] = [tuple(converte(tipo, r.get(c)) for c, tipo in cols) for r in linhas.get(t, [])]
    return saida


def carrega(cur, espelho):
    """Regrava `legado` inteiro (DELETE + COPY) dentro da transação de quem chama."""
    resumo = {}
    for t in TABELAS:
        cur.execute(f"DELETE FROM legado.{t}")
        with cur.copy(f"COPY legado.{t} ({', '.join(colunas(t))}) FROM STDIN") as cp:
            for linha in espelho.get(t, []):
                cp.write_row(linha)
        resumo[t] = len(espelho.get(t, []))
    return resumo
```

- [ ] **Step 5: Migração.** As 33 tabelas e views saem da lista do Step 3. O teste `test_legado_bate_com_a_lista` confere as duas.

```sql
-- Espelho fiel das tabelas Delta que o app lê (ADR 0005, Fase 1 — decisão de 14/10/2026).
--
-- Na Fase 1 o app na AWS só LÊ, e o Databricks é a fonte da verdade. Cada tabela que o app lê
-- vira uma cópia fiel em `legado` (mesmas colunas e tipos, sem restrição nenhuma: o Delta não
-- tem PK nem FK, e a cópia não pode recusar o que o Databricks aceitou). A view compat.<tabela>
-- só lê de lá, então a resposta da API sai igual à do Databricks por construção.
-- `timestamp` é SEM fuso e em UTC: CAST(x AS STRING) sai como no Spark e o driver devolve
-- AAAA-MM-DDTHH:MM:SS.mmmZ, como o JSON do Databricks.
-- O de-para com correções para o schema novo é da Fase 2, por grupo; aí a view de cada grupo
-- passa a ler do schema novo e `legado` encolhe até sumir.
-- Lista de colunas: sync/espelho_tabelas.py (o teste test_espelho confere as duas).

CREATE SCHEMA legado;

CREATE TABLE legado.sas_inputs_monitor (
  chave_canonica text,
  artifact text,
  categoria text,
  source_types text,
  qtd_projetos integer,
  areas text,
  escopo_indi boolean,
  modernizada_auto text,
  status_humano text,
  responsavel text,
  observacao text,
  updated_at timestamp,
  updated_by text,
  orfao boolean,
  refreshed_at timestamp,
  origem text,
  paths_fisicos text,
  n_paths_fisicos integer,
  etapa text,
  status text
);

CREATE TABLE legado.sas_egp_inputs (
  projeto text,
  area text,
  onda text,
  escopo_indi boolean,
  ciclo_id integer,
  chave_canonica text,
  artifact text,
  categoria text,
  source_types text,
  modernizada_auto text
);

CREATE TABLE legado.sas_lineage_nodes (
  projeto text,
  area text,
  onda text,
  n_inputs integer,
  n_outputs integer,
  escopo_indi boolean,
  ciclo_id integer,
  loc integer,
  code_tasks_count integer,
  n_outputs_avaliados integer,
  n_outputs_consumidos_por_outro_egp integer,
  pct_outputs_consumidos_por_outro_egp double precision,
  n_egps_consumidores integer,
  n_exports_arquivos integer,
  flag_output_100pct_egp boolean,
  flag_algum_output_egp boolean,
  flag_sem_export_arquivo boolean,
  flag_output_unico boolean,
  flag_hub_multiplos_consumidores boolean
);

CREATE TABLE legado.sas_lineage_edges (
  projeto_alvo text,
  depende_do text,
  via_tabelas text,
  qtd_via integer,
  max_produtores integer
);

CREATE TABLE legado.sas_egp_outputs (
  projeto text,
  area text,
  onda text,
  escopo_indi boolean,
  chave_canonica text,
  artifact text,
  categoria text,
  apenas_contribui boolean
);

CREATE TABLE legado.sas_outputs_monitor (
  chave_canonica text,
  artifact text,
  categoria text,
  areas text,
  qtd_produtores integer,
  qtd_criadores integer,
  qtd_consumidores integer,
  terminal boolean,
  modernizada_auto text,
  escopo_indi boolean,
  paths_fisicos text
);

CREATE TABLE legado.sas_resumo_inputs (
  chave_canonica text,
  area_principal text,
  origem_bucket text,
  escopo_indi boolean,
  modernizada_auto text
);

CREATE TABLE legado.sas_funil_area (
  area text,
  qtd_dor1 integer,
  egps_enviados integer,
  egps_analisados integer
);

CREATE TABLE legado.sas_escopo (
  id text,
  egp_dor1 text,
  area text,
  status_extracao text,
  projeto text,
  origem text,
  created_by text,
  created_at text,
  ativo boolean
);

CREATE TABLE legado.sas_egp_pipeline (
  projeto text,
  etapa_migracao text,
  status_migracao text,
  etapa_progresso text,
  status_progresso text,
  updated_by text,
  updated_at text,
  responsavel text,
  mes_prioridade integer,
  jira_id text,
  responsavel_bv text,
  preworking_preenchido text,
  preworking_data text,
  egp_atualizado_key text,
  egp_vinculo_tipo text,
  egp_sucessor text
);

CREATE TABLE legado.sas_egp_input_link (
  projeto text,
  chave_canonica text,
  link_broken boolean,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_egp_dep_mantida (
  projeto text,
  chave_canonica text,
  motivo text,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_output_producer_choice (
  chave_canonica text,
  projeto_escolhido text,
  chosen_by text,
  chosen_at text
);

CREATE TABLE legado.sas_outputs_pipeline (
  chave_canonica text,
  recebido text,
  recebido_data text,
  updated_by text,
  updated_at text,
  carga_fria text,
  cf_etapa text,
  cf_status text,
  cf_responsavel text,
  cf_inicio text,
  cf_fim text,
  cf_caminho text,
  cf_tabela text
);

CREATE TABLE legado.sas_inputs_preworking (
  chave_canonica text,
  origem_arquivo text,
  frequencia text,
  horario text,
  tipo_carga text,
  pos_processamento text,
  dados_sensiveis text,
  updated_by text,
  updated_at text,
  recebido text,
  data_recebimento text,
  modernizado_bv text,
  data_modernizado_bv text,
  iniciado_em text,
  concluido_em text
);

CREATE TABLE legado.sas_egp_input_periodo (
  projeto text,
  categoria text,
  familia text,
  tipo text,
  valor text,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_familia_ingestao (
  categoria text,
  familia text,
  desde text,
  ingerida_em text,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_app_config (
  chave text,
  valor text,
  updated_by text,
  updated_at text
);

CREATE TABLE legado.sas_priorizacao_snapshot (
  id text,
  payload text,
  capacidade integer,
  saved_by text,
  saved_at text
);

CREATE TABLE legado.sas_gestao_status (
  id text,
  entity text,
  entity_id text,
  autor text,
  criado_por text,
  ts text,
  texto text
);

CREATE TABLE legado.sas_gestao_datas (
  entity text,
  entity_id text,
  inicio text,
  fim_conversao text,
  fim text,
  updated_by text,
  updated_at text
);

CREATE TABLE legado.sas_gestao_bv (
  id text,
  entity text,
  entity_id text,
  com_bv boolean,
  data text,
  autor text,
  ts text
);

CREATE TABLE legado.sas_gestao_revisao (
  entity text,
  entity_id text,
  contador integer,
  updated_by text,
  updated_at text
);

CREATE TABLE legado.sas_inputs_audit (
  chave_canonica text,
  campo text,
  valor_antigo text,
  valor_novo text,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_pipeline_audit (
  id text,
  projeto text,
  funil text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts text
);

CREATE TABLE legado.sas_escopo_audit (
  id text,
  acao text,
  egp_dor1 text,
  projeto text,
  ator text,
  ts text
);

CREATE TABLE legado.sas_egp_input_link_audit (
  id text,
  projeto text,
  chave_canonica text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts timestamp
);

CREATE TABLE legado.sas_egp_atualizados (
  versao_id text,
  egp_key text,
  nome text,
  area text,
  arquivo text,
  arquivo_hash text,
  origem text,
  egp_original text,
  n_antecessores integer,
  confianca_par text,
  overlap_tasks double precision,
  autor_ultimo_save text,
  login_autor text,
  data_ultimo_save text,
  data_criacao text,
  data_recebimento text,
  valor double precision,
  esforco double precision,
  razao double precision,
  quadrante text,
  n_vetos integer,
  vetos text,
  alertas text,
  table_in_antigo integer,
  table_in_novo integer,
  a_ingerir_antigo integer,
  a_ingerir_novo integer,
  disponivel_antigo integer,
  disponivel_novo integer,
  file_in_antigo integer,
  file_in_novo integer,
  script_in_antigo integer,
  script_in_novo integer,
  outputs_antigo integer,
  outputs_novo integer,
  outputs_removidos_com_consumidor integer,
  outputs_removidos_privados integer,
  inputs_macro_nao_resolvido integer,
  inputs_rede_novos integer,
  deps_novas integer,
  loc_antigo integer,
  loc_novo integer,
  linhas_add integer,
  linhas_rem integer,
  tasks_novas integer,
  alcance_total integer,
  alcance_por_grafo integer,
  alcance_por_output integer,
  status_troca text,
  publicado_por text,
  publicado_em timestamp
);

CREATE TABLE legado.sas_egp_atualizados_inputs (
  versao_id text,
  chave_canonica text,
  artefato text,
  categoria text,
  source text,
  situacao_no_recebimento text,
  novo boolean,
  publicado_em timestamp
);

CREATE TABLE legado.sas_egp_atualizados_outputs (
  versao_id text,
  chave_canonica text,
  artefato text,
  situacao text,
  novo boolean,
  removido boolean,
  n_consumidores_externos integer,
  publicado_em timestamp,
  padrao boolean,
  categoria text
);

CREATE TABLE legado.sas_egp_atualizados_pipeline (
  egp_key text,
  etapa text,
  status text,
  responsavel text,
  updated_by text,
  updated_at timestamp,
  responsavel_bv text,
  tipo_vinculo text
);

CREATE TABLE legado.sas_analistas (
  email text,
  nome text,
  ativo boolean,
  created_by text,
  created_at text,
  updated_by text,
  updated_at text,
  organograma boolean,
  papel text
);

CREATE TABLE legado.sas_responsaveis_bv (
  nome_key text,
  nome text,
  subarea text,
  ativo boolean,
  created_by text,
  created_at text,
  updated_by text,
  updated_at text
);

-- As duas views do 1a liam o schema novo; passam a ler o espelho, como as demais
-- (o escopo_indi gravado pelo Databricks, e não o derivado, é o que o app antigo mostra).
DROP VIEW compat.sas_inputs_monitor;
DROP VIEW compat.sas_egp_inputs;

CREATE VIEW compat.sas_inputs_monitor AS SELECT chave_canonica, artifact, categoria, source_types, qtd_projetos, areas, escopo_indi, modernizada_auto, status_humano, responsavel, observacao, updated_at, updated_by, orfao, refreshed_at, origem, paths_fisicos, n_paths_fisicos, etapa, status FROM legado.sas_inputs_monitor;

CREATE VIEW compat.sas_egp_inputs AS SELECT projeto, area, onda, escopo_indi, ciclo_id, chave_canonica, artifact, categoria, source_types, modernizada_auto FROM legado.sas_egp_inputs;

CREATE VIEW compat.sas_lineage_nodes AS SELECT projeto, area, onda, n_inputs, n_outputs, escopo_indi, ciclo_id, loc, code_tasks_count, n_outputs_avaliados, n_outputs_consumidos_por_outro_egp, pct_outputs_consumidos_por_outro_egp, n_egps_consumidores, n_exports_arquivos, flag_output_100pct_egp, flag_algum_output_egp, flag_sem_export_arquivo, flag_output_unico, flag_hub_multiplos_consumidores FROM legado.sas_lineage_nodes;

CREATE VIEW compat.sas_lineage_edges AS SELECT projeto_alvo, depende_do, via_tabelas, qtd_via, max_produtores FROM legado.sas_lineage_edges;

CREATE VIEW compat.sas_egp_outputs AS SELECT projeto, area, onda, escopo_indi, chave_canonica, artifact, categoria, apenas_contribui FROM legado.sas_egp_outputs;

CREATE VIEW compat.sas_outputs_monitor AS SELECT chave_canonica, artifact, categoria, areas, qtd_produtores, qtd_criadores, qtd_consumidores, terminal, modernizada_auto, escopo_indi, paths_fisicos FROM legado.sas_outputs_monitor;

CREATE VIEW compat.sas_resumo_inputs AS SELECT chave_canonica, area_principal, origem_bucket, escopo_indi, modernizada_auto FROM legado.sas_resumo_inputs;

CREATE VIEW compat.sas_funil_area AS SELECT area, qtd_dor1, egps_enviados, egps_analisados FROM legado.sas_funil_area;

CREATE VIEW compat.sas_escopo AS SELECT id, egp_dor1, area, status_extracao, projeto, origem, created_by, created_at, ativo FROM legado.sas_escopo;

CREATE VIEW compat.sas_egp_pipeline AS SELECT projeto, etapa_migracao, status_migracao, etapa_progresso, status_progresso, updated_by, updated_at, responsavel, mes_prioridade, jira_id, responsavel_bv, preworking_preenchido, preworking_data, egp_atualizado_key, egp_vinculo_tipo, egp_sucessor FROM legado.sas_egp_pipeline;

CREATE VIEW compat.sas_egp_input_link AS SELECT projeto, chave_canonica, link_broken, updated_by, updated_at FROM legado.sas_egp_input_link;

CREATE VIEW compat.sas_egp_dep_mantida AS SELECT projeto, chave_canonica, motivo, updated_by, updated_at FROM legado.sas_egp_dep_mantida;

CREATE VIEW compat.sas_output_producer_choice AS SELECT chave_canonica, projeto_escolhido, chosen_by, chosen_at FROM legado.sas_output_producer_choice;

CREATE VIEW compat.sas_outputs_pipeline AS SELECT chave_canonica, recebido, recebido_data, updated_by, updated_at, carga_fria, cf_etapa, cf_status, cf_responsavel, cf_inicio, cf_fim, cf_caminho, cf_tabela FROM legado.sas_outputs_pipeline;

CREATE VIEW compat.sas_inputs_preworking AS SELECT chave_canonica, origem_arquivo, frequencia, horario, tipo_carga, pos_processamento, dados_sensiveis, updated_by, updated_at, recebido, data_recebimento, modernizado_bv, data_modernizado_bv, iniciado_em, concluido_em FROM legado.sas_inputs_preworking;

CREATE VIEW compat.sas_egp_input_periodo AS SELECT projeto, categoria, familia, tipo, valor, updated_by, updated_at FROM legado.sas_egp_input_periodo;

CREATE VIEW compat.sas_familia_ingestao AS SELECT categoria, familia, desde, ingerida_em, updated_by, updated_at FROM legado.sas_familia_ingestao;

CREATE VIEW compat.sas_app_config AS SELECT chave, valor, updated_by, updated_at FROM legado.sas_app_config;

CREATE VIEW compat.sas_priorizacao_snapshot AS SELECT id, payload, capacidade, saved_by, saved_at FROM legado.sas_priorizacao_snapshot;

CREATE VIEW compat.sas_gestao_status AS SELECT id, entity, entity_id, autor, criado_por, ts, texto FROM legado.sas_gestao_status;

CREATE VIEW compat.sas_gestao_datas AS SELECT entity, entity_id, inicio, fim_conversao, fim, updated_by, updated_at FROM legado.sas_gestao_datas;

CREATE VIEW compat.sas_gestao_bv AS SELECT id, entity, entity_id, com_bv, data, autor, ts FROM legado.sas_gestao_bv;

CREATE VIEW compat.sas_gestao_revisao AS SELECT entity, entity_id, contador, updated_by, updated_at FROM legado.sas_gestao_revisao;

CREATE VIEW compat.sas_inputs_audit AS SELECT chave_canonica, campo, valor_antigo, valor_novo, updated_by, updated_at FROM legado.sas_inputs_audit;

CREATE VIEW compat.sas_pipeline_audit AS SELECT id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_pipeline_audit;

CREATE VIEW compat.sas_escopo_audit AS SELECT id, acao, egp_dor1, projeto, ator, ts FROM legado.sas_escopo_audit;

CREATE VIEW compat.sas_egp_input_link_audit AS SELECT id, projeto, chave_canonica, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_egp_input_link_audit;

CREATE VIEW compat.sas_egp_atualizados AS SELECT versao_id, egp_key, nome, area, arquivo, arquivo_hash, origem, egp_original, n_antecessores, confianca_par, overlap_tasks, autor_ultimo_save, login_autor, data_ultimo_save, data_criacao, data_recebimento, valor, esforco, razao, quadrante, n_vetos, vetos, alertas, table_in_antigo, table_in_novo, a_ingerir_antigo, a_ingerir_novo, disponivel_antigo, disponivel_novo, file_in_antigo, file_in_novo, script_in_antigo, script_in_novo, outputs_antigo, outputs_novo, outputs_removidos_com_consumidor, outputs_removidos_privados, inputs_macro_nao_resolvido, inputs_rede_novos, deps_novas, loc_antigo, loc_novo, linhas_add, linhas_rem, tasks_novas, alcance_total, alcance_por_grafo, alcance_por_output, status_troca, publicado_por, publicado_em FROM legado.sas_egp_atualizados;

CREATE VIEW compat.sas_egp_atualizados_inputs AS SELECT versao_id, chave_canonica, artefato, categoria, source, situacao_no_recebimento, novo, publicado_em FROM legado.sas_egp_atualizados_inputs;

CREATE VIEW compat.sas_egp_atualizados_outputs AS SELECT versao_id, chave_canonica, artefato, situacao, novo, removido, n_consumidores_externos, publicado_em, padrao, categoria FROM legado.sas_egp_atualizados_outputs;

CREATE VIEW compat.sas_egp_atualizados_pipeline AS SELECT egp_key, etapa, status, responsavel, updated_by, updated_at, responsavel_bv, tipo_vinculo FROM legado.sas_egp_atualizados_pipeline;

CREATE VIEW compat.sas_analistas AS SELECT email, nome, ativo, created_by, created_at, updated_by, updated_at, organograma, papel FROM legado.sas_analistas;

CREATE VIEW compat.sas_responsaveis_bv AS SELECT nome_key, nome, subarea, ativo, created_by, created_at, updated_by, updated_at FROM legado.sas_responsaveis_bv;


-- Funções do Spark que o app usa em rotas GET e ainda faltavam (levantamento de 14/10).
-- instr(str, sub): posição a partir de 1; 0 se não acha; NULL se algum lado é NULL.
CREATE FUNCTION compat.instr(text, text) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$ SELECT strpos($1, $2) $$;

-- regexp_extract(str, regex, grupo): '' quando não casa (o Spark não devolve NULL).
CREATE FUNCTION compat.regexp_extract(text, text, integer) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN $1 IS NULL THEN NULL ELSE coalesce((regexp_match($1, $2))[$3], '') END
$$;

-- Leitura para os dois papéis; regravação só para a sincronização. As views novas de compat
-- já nascem legíveis pelos privilégios padrão da 0004.
GRANT USAGE ON SCHEMA legado TO app_leitura, sincronizador;
GRANT SELECT ON ALL TABLES IN SCHEMA legado TO app_leitura, sincronizador;
GRANT INSERT, DELETE ON ALL TABLES IN SCHEMA legado TO sincronizador;
ALTER DEFAULT PRIVILEGES IN SCHEMA legado GRANT SELECT ON TABLES TO app_leitura, sincronizador;
```

- [ ] **Step 6: Rodar e ver passar**

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q sync/test_espelho.py
```

Esperado: `10 passed`.

### Task A2: A sincronização lê e grava o espelho

**Files:**
- Modify: `sync/leitor.py`, `sync/retrato.py`, `sync/carrega.py`, `sync/sincroniza.py`, `sync/sintetico.py`
- Test: `sync/test_sync.py` (modify)

O que muda:
- **Leitura:** a sincronização lê **todas** as colunas de cada tabela espelhada, e o instante vem como texto (`espelho.selecao`).
- **Fuso:** antes de ler, confere que a sessão do Databricks está em UTC.
- **Carga:** grava o espelho na **mesma transação** do de-para do 1a, então quem lê vê um retrato só.
- **Massas de teste:** a do teste e a do ensaio passam a trazer o `escopo_indi`, que a view `compat` agora mostra como o Databricks gravou.

- [ ] **Step 1: Ajustar o teste da carga.** A view `compat.sas_inputs_monitor` lê o espelho: a massa traz o `escopo_indi` e os instantes no formato lido (`CAST(x AS STRING)`):

```diff
--- a/egps_analysis/app/sync/test_sync.py
+++ b/egps_analysis/app/sync/test_sync.py
@@ -48,11 +48,12 @@ def test_leitor_falha_alto_se_o_total_nao_bate():
 
 # ---------------------------------------------------------------- de-para
 def _monitor(**kw):
+    # Instantes no formato em que a sincronização lê (CAST(x AS STRING), sessão em UTC).
     base = {"chave_canonica": "tabela::LIB.T", "artifact": "LIB.T", "categoria": "tabela",
             "source_types": "PROC SQL | DATA", "qtd_projetos": "2", "areas": "Cobranças | Riscos",
-            "modernizada_auto": "A ingerir", "responsavel": "", "observacao": None,
-            "updated_at": None, "updated_by": None, "orfao": "false",
-            "refreshed_at": "2026-10-13T10:00:00.000Z", "origem": "BigQuery",
+            "escopo_indi": "true", "modernizada_auto": "A ingerir", "responsavel": "",
+            "observacao": None, "updated_at": None, "updated_by": None, "orfao": "false",
+            "refreshed_at": "2026-10-13 10:00:00", "origem": "BigQuery",
             "paths_fisicos": None, "etapa": "A Receber", "status": "A Iniciar"}
     base.update(kw)
     return base
@@ -71,7 +72,7 @@ def test_estado_do_publish_leva_a_sentinela():
 
 def test_estado_editado_guarda_quem_e_quando():
     e = mp.estado_input(_monitor(responsavel="Fulano@indicium.ai", updated_by="b@indicium.ai",
-                                 updated_at="2026-10-01T12:00:00.000Z"))
+                                 updated_at="2026-10-01 12:00:00.000123"))
     assert e[3] == "fulano@indicium.ai" and e[6] == "b@indicium.ai" and e[5].isoformat().startswith("2026-10-01T12:00")
 
 
@@ -96,7 +97,7 @@ def _linhas():
         "sas_lineage_nodes": [{"projeto": "Cob__A", "area": "Cobranças", "ciclo_id": "0"}],
         "sas_inputs_monitor": [_monitor(responsavel="fulano@indicium.ai",
                                         updated_by="fulano@indicium.ai",
-                                        updated_at="2026-10-01T12:00:00.000Z")],
+                                        updated_at="2026-10-01 12:00:00.000123")],
         "sas_egp_inputs": [
             {"projeto": "Cob__A", "chave_canonica": "tabela::LIB.T", "artifact": "LIB.T",
              "categoria": "tabela", "source_types": "PROC SQL"},
@@ -141,8 +142,10 @@ def test_carga_completa_ancoras_e_e_repetivel(banco):
         u = conn.execute("SELECT papel, ativo, cargo FROM cadastro.usuario WHERE email = 'fulano@indicium.ai'").fetchone()
         assert u == ("leitor", False, "DE")          # sincronização nunca dá acesso
         assert conn.execute("SELECT count(*) FROM historico.publicacao WHERE ok").fetchone()[0] == 2
+        # compat lê o espelho: devolve o que o Databricks gravou, inclusive o escopo_indi
         linha = conn.execute("SELECT areas, escopo_indi, updated_by FROM compat.sas_inputs_monitor").fetchone()
         assert linha == ("Cobranças | Riscos", True, "fulano@indicium.ai")
+        assert r2["espelho"]["sas_inputs_monitor"] == 1 and r2["espelho"]["sas_egp_inputs"] == 3
 
 
 @precisa_pg
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q sync/test_sync.py
```

Esperado: `test_carga_completa_ancoras_e_e_repetivel` falha. A view `compat.sas_inputs_monitor` (0005) lê o espelho, que a carga ainda não grava, e a linha vem `None`.

- [ ] **Step 3: Leitor com expressões no SELECT**

```diff
--- a/egps_analysis/app/sync/leitor.py
+++ b/egps_analysis/app/sync/leitor.py
@@ -10,8 +10,10 @@ import time
 from databricks.sdk.service.sql import Disposition, Format, StatementState
 
 
-def le_tabela(w, warehouse_id, fq_tabela, colunas):
-    sql = f"SELECT {', '.join(colunas)} FROM {fq_tabela}"
+def le_tabela(w, warehouse_id, fq_tabela, colunas, expressoes=None):
+    """`expressoes`: o que vai no SELECT, uma por coluna (ex.: CAST(ts AS STRING) AS ts);
+    sem elas, as próprias colunas."""
+    sql = f"SELECT {', '.join(expressoes or colunas)} FROM {fq_tabela}"
     r = w.statement_execution.execute_statement(
         statement=sql, warehouse_id=warehouse_id, wait_timeout="50s",
         disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
```

- [ ] **Step 4: Retrato e carga**

```diff
--- a/egps_analysis/app/sync/retrato.py
+++ b/egps_analysis/app/sync/retrato.py
@@ -1,11 +1,12 @@
 # -*- coding: utf-8 -*-
 """Monta o retrato a partir das linhas lidas do Databricks: aplica o de-para e completa as
 âncoras (EGP/input citados por um par mas ausentes da tabela-mãe entram como órfãos)."""
-from . import mapeamento as mp
+from . import espelho, mapeamento as mp
 
 
 def monta(linhas):
-    """`linhas`: dict tabela Delta -> lista de dicts (texto). Devolve o retrato de carrega()."""
+    """`linhas`: dict tabela Delta -> lista de dicts (texto). Devolve o retrato de carrega():
+    o de-para das 5 tabelas do 1a para o schema novo e o espelho fiel do que o app lê."""
     egps = {r["projeto"]: mp.egp(r) for r in linhas["sas_lineage_nodes"]}
     inputs = {r["chave_canonica"]: mp.input_(r) for r in linhas["sas_inputs_monitor"]}
     estados = [e for e in (mp.estado_input(r) for r in linhas["sas_inputs_monitor"]) if e]
@@ -41,4 +42,5 @@ def monta(linhas):
         "pessoas_referenciadas": referenciadas,
         "ancoras_acrescentadas": {"egp": egps_novos, "input": inputs_novos,
                                   "pares_duplicados_descartados": duplicados},
+        "espelho": espelho.monta(linhas),
     }
```

```diff
--- a/egps_analysis/app/sync/carrega.py
+++ b/egps_analysis/app/sync/carrega.py
@@ -10,7 +10,7 @@ inativas, e atualiza nome/cargo) e `historico.publicacao` (só recebe linha).
 import datetime
 import json
 
-from . import mapeamento as mp
+from . import espelho, mapeamento as mp
 
 # Apaga filhos antes dos pais; insere pais antes dos filhos.
 SINCRONIZADAS = ("trabalho.estado_input", "corpus.egp_input", "trabalho.escopo_item",
@@ -47,6 +47,7 @@ def carrega(conn, retrato, versao_codigo=None, agora=None):
                             "ON CONFLICT (email) DO NOTHING", (email, email))
             for t in reversed(SINCRONIZADAS):
                 _copia(cur, t, retrato.get(t, []))
+            resumo["espelho"] = espelho.carrega(cur, retrato.get("espelho", {}))
             cur.execute("SELECT count(*) FROM derivado.v_trabalho_orfao")
             resumo["trabalho_orfao"] = cur.fetchone()[0]
             resumo["ancoras_acrescentadas"] = retrato.get("ancoras_acrescentadas", {})
```

- [ ] **Step 5: Ponto de entrada: fuso e leitura única**

```diff
--- a/egps_analysis/app/sync/sincroniza.py
+++ b/egps_analysis/app/sync/sincroniza.py
@@ -17,7 +17,28 @@ import psycopg
 from databricks.sdk import WorkspaceClient
 from psycopg import sql
 
-from . import carrega, leitor, mapeamento as mp, retrato
+from . import carrega, espelho, leitor, mapeamento as mp, retrato
+
+FUSOS_UTC = ("Etc/UTC", "UTC", "Z", "+00:00")
+
+
+def le_tudo(w, warehouse, origem):
+    """Uma leitura por tabela. As 5 do 1a também são espelhadas: lê as colunas do espelho
+    (que incluem as do de-para) e as duas partes usam a mesma leitura."""
+    fuso = leitor.le_tabela(w, warehouse, "(SELECT current_timezone() AS fuso)", ["fuso"])[0]["fuso"]
+    if fuso not in FUSOS_UTC:   # CAST(timestamp AS STRING) sai no fuso da sessão
+        raise RuntimeError(f"sessão do Databricks em {fuso}, não UTC: os instantes sairiam deslocados")
+    linhas = {}
+    for t in dict.fromkeys([*espelho.TABELAS, *mp.ORIGEM]):
+        if t in espelho.TABELAS:
+            faltam = set(mp.ORIGEM.get(t, ())) - set(espelho.colunas(t))
+            if faltam:
+                raise RuntimeError(f"{t}: o de-para lê colunas fora do espelho: {sorted(faltam)}")
+            linhas[t] = leitor.le_tabela(w, warehouse, f"{origem}.{t}", espelho.colunas(t),
+                                         espelho.selecao(t))
+        else:
+            linhas[t] = leitor.le_tabela(w, warehouse, f"{origem}.{t}", mp.ORIGEM[t])
+    return linhas
 
 
 def main():
@@ -25,8 +46,7 @@ def main():
     try:
         warehouse = os.environ["DATABRICKS_WAREHOUSE_ID"]
         w = WorkspaceClient()
-        linhas = {t: leitor.le_tabela(w, warehouse, f"{origem}.{t}", cols)
-                  for t, cols in mp.ORIGEM.items()}
+        linhas = le_tudo(w, warehouse, origem)
         with psycopg.connect(os.environ.get("PG_DSN") or "") as conn:
             # Entra como mestre (girado pela plataforma) e baixa para o papel da carga.
             papel = os.environ.get("PG_PAPEL")
```

- [ ] **Step 6: Massa sintética do ensaio**

```diff
--- a/egps_analysis/app/sync/sintetico.py
+++ b/egps_analysis/app/sync/sintetico.py
@@ -27,6 +27,7 @@ def linhas(n_egps=40, n_inputs=300, semente=42):
     Databricks). Determinístico pela semente: o ensaio de hoje é igual ao de ontem."""
     rnd = random.Random(semente)
     egps = [f"{AREAS[i % 3]}__EGP_TREINO_{i:03d}" for i in range(n_egps)]
+    no_escopo = set(egps[: n_egps * 2 // 3])
     inputs = []
     for i in range(n_inputs):
         cat, molde = MOLDES[i % 3]
@@ -38,20 +39,28 @@ def linhas(n_egps=40, n_inputs=300, semente=42):
             "areas": " | ".join(sorted(rnd.sample(AREAS, rnd.randint(1, 2)))),
             "modernizada_auto": "Disponível" if etapa == "Modernizado" else "A ingerir",
             "responsavel": "", "observacao": None, "updated_at": None, "updated_by": None,
-            "orfao": "false", "refreshed_at": "2026-10-15T09:00:00.000Z",
-            "origem": rnd.choice(("BigQuery", "Transacional", "Arquivo")), "paths_fisicos": None,
-            "etapa": etapa, "status": status})
+            "orfao": "false", "refreshed_at": "2026-10-15 09:00:00",
+            "origem": rnd.choice(("BigQuery", "Transacional", "Arquivo")), "paths_fisicos": "",
+            "n_paths_fisicos": "0", "etapa": etapa, "status": status})
     pares = []
     for p in egps:
         for r in rnd.sample(inputs, rnd.randint(3, 8)):
-            pares.append({"projeto": p, "chave_canonica": r["chave_canonica"], "artifact": r["artifact"],
-                          "categoria": r["categoria"], "source_types": "PROC SQL"})
-    nos = [{"projeto": p, "area": p.split("__")[0], "ciclo_id": "0",
+            pares.append({"projeto": p, "area": p.split("__")[0], "onda": "Onda 0",
+                          "escopo_indi": "true" if p in no_escopo else "false", "ciclo_id": "0",
+                          "chave_canonica": r["chave_canonica"], "artifact": r["artifact"],
+                          "categoria": r["categoria"], "source_types": "PROC SQL",
+                          "modernizada_auto": r["modernizada_auto"]})
+    # escopo_indi gravado como o publish do Databricks grava: EGP do escopo, e input lido por um
+    lidos = {x["chave_canonica"] for x in pares if x["projeto"] in no_escopo}
+    for r in inputs:
+        r["escopo_indi"] = "true" if r["chave_canonica"] in lidos else "false"
+    nos = [{"projeto": p, "area": p.split("__")[0], "onda": "Onda 0", "ciclo_id": "0",
+            "escopo_indi": "true" if p in no_escopo else "false", "n_outputs": "0",
             "n_inputs": str(sum(1 for x in pares if x["projeto"] == p))} for p in egps]
     escopo = [{"id": uuid.UUID(int=rnd.getrandbits(128)).hex, "egp_dor1": p.split("__")[1],
                "area": p.split("__")[0], "status_extracao": "exato", "projeto": p, "origem": "csv",
-               "created_by": None, "created_at": "seed", "ativo": "true"}
-              for p in egps[: n_egps * 2 // 3]]
+               "created_by": "seed", "created_at": "seed", "ativo": "true"}
+              for p in egps if p in no_escopo]
     return {"sas_lineage_nodes": nos, "sas_inputs_monitor": inputs, "sas_egp_inputs": pares,
             "sas_escopo": escopo, "sas_analistas": []}
 
```

- [ ] **Step 7: Rodar a suíte da sincronização e do banco**

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres PG_TEST_OBRIGATORIO=1 .venv/bin/python -m pytest -q db sync paridade treino
```

Esperado: tudo verde (58 testes em 14/10, antes das Tasks A3 e C).

### Task A3: Recusar banco cujo `upper()` não entende acento

**Files:**
- Modify: `db/migra.py`
- Test: `db/test_migra.py` (modify)

- [ ] **Step 1: Teste**

```diff
--- a/egps_analysis/app/db/test_migra.py
+++ b/egps_analysis/app/db/test_migra.py
@@ -63,6 +63,23 @@ def test_banco_sem_collation_c_e_recusado(tmp_path):
             c.execute(f"DROP DATABASE {nome} WITH (FORCE)")
 
 
+def test_banco_com_ctype_sem_unicode_e_recusado(tmp_path):
+    """Collation C ordena como o Spark, mas a caixa vem do LC_CTYPE: com 'C' o upper('ç')
+    fica 'ç' e a chave de família de MARÇO sairia diferente da do Spark, em silêncio."""
+    import psycopg
+    nome = "t_migra_" + uuid.uuid4().hex[:8]
+    with psycopg.connect(DSN, autocommit=True) as c:
+        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'")
+    base, _, _ = DSN.rpartition("/")
+    try:
+        (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (x int);")
+        with pytest.raises(SystemExit, match="upper"):
+            migra.aplica(f"{base}/{nome}", tmp_path, saida=lambda *_: None)
+    finally:
+        with psycopg.connect(DSN, autocommit=True) as c:
+            c.execute(f"DROP DATABASE {nome} WITH (FORCE)")
+
+
 def test_cria_banco_com_collation_c_e_idempotente():
     import psycopg
     nome = "t_migra_" + uuid.uuid4().hex[:8]
```

- [ ] **Step 2: Rodar e ver falhar** (`.venv/bin/python -m pytest -q db/test_migra.py` com o `PG_TEST_DSN`). Esperado: `test_banco_com_ctype_sem_unicode_e_recusado` falha (`DID NOT RAISE`).

- [ ] **Step 3: Implementar**

```diff
--- a/egps_analysis/app/db/migra.py
+++ b/egps_analysis/app/db/migra.py
@@ -65,6 +65,12 @@ def _confere_collation(conn):
     if col != COLLATION:
         raise SystemExit(f"banco {nome} com collation {col!r}; o app precisa de {COLLATION!r} "
                          f"(ordem de bytes, como o Spark). Recrie com --cria-banco.")
+    # A collation C não muda a CAIXA: upper() segue o LC_CTYPE do banco (o padrão do
+    # servidor; no RDS, en_US.UTF-8). Com LC_CTYPE 'C' o upper() só vê ASCII, e a regra de
+    # família (MARÇO, ABRIL...) daria chave diferente da do Spark, sem erro nenhum.
+    if conn.execute("SELECT upper('ç') = 'Ç'").fetchone()[0] is not True:
+        raise SystemExit(f"banco {nome}: upper('ç') não dá 'Ç' (LC_CTYPE sem Unicode); o app "
+                         f"precisa da caixa como no Spark. Recrie num servidor com LC_CTYPE UTF-8.")
 
 
 def _garante_controle(conn):
```

- [ ] **Step 4: Rodar e ver passar.** No RDS, o `LC_CTYPE` padrão é `en_US.UTF-8`, e o banco do app herda (o `--cria-banco` só fixa a collation).

---

## Parte B — Dialeto das rotas GET

### Task B1: SQL que roda igual nos dois bancos

**Files:**
- Modify: `backend/main.py`, `backend/familias.py`, `backend/egps_atualizados.py`
- Test: `backend/test_sql_portavel_pg.py`

Cada mudança veio de uma diferença real na comparação de 14/10:

| Onde | Antes | Depois | Rota que quebrava |
|---|---|---|---|
| `familias.familia_candidata_sql` | `split(x, ' [|] ')[0]` | `element_at(split(x, ' [|] '), 1)` | `/api/egp-readiness` (502), `/api/priorizacao` (campo sumia), `/api/audit` |
| `main.py`: filtro de área (`/api/metrics`, `/api/inputs`) e produtores da família (`/api/input`) | `arrays_overlap(transform(split(..), x -> trim(x)), array(..))` | `_lista_tem_algum(lista, valores)` | 502 com `area` e no detalhe de família |
| `ORDER BY` com coluna que pode ser NULL (9 em `main.py`, 3 em `egps_atualizados.py`) | sem `NULLS` | `NULLS FIRST` no ASC, `NULLS LAST` no DESC (a regra do Spark) | `/api/responsaveis-bv` e outras |
| `/api/audit` | `ORDER BY ts DESC LIMIT n` | o mesmo, com desempate | edição em lote grava dezenas de linhas no mesmo instante, e o `LIMIT` escolhia um subconjunto diferente em cada banco (e no próprio Databricks, a cada vez) |
| `_migrados_mes` | `current_date()` | `current_date` (vale nos dois) | `migrados_mes` dava 0 em silêncio |
| `_log_san_contadores`, auto-congelamento em `/api/priorizacao` | gravavam durante um GET | desligados no Postgres | na Fase 1 quem grava é o Databricks |

- [ ] **Step 1: Teste do SQL portável num Postgres de verdade**

```python
# -*- coding: utf-8 -*-
"""SQL escrito para rodar igual no Spark e no Postgres (ADR 0005, 1b): confere no Postgres de
verdade contra a régua em Python. O lado Spark dessas mesmas expressões é o que o app de
produção já roda; a comparação de leituras (paridade) fecha a ponta entre os dois."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import familias as F  # noqa: E402
from backend import main as m  # noqa: E402
from db import migra  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
precisa_pg = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")
SEM_OVERRIDES = {"juntar": {}, "separar": set()}


@pytest.fixture(scope="module")
def conn():
    import psycopg
    nome = "t_port_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    migra.aplica(f"{base}/{nome}", saida=lambda *_: None)
    with psycopg.connect(f"{base}/{nome}", autocommit=True) as c:
        c.execute("SET search_path = compat, derivado, pg_catalog, public")
        yield c
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def _lit(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


@precisa_pg
@pytest.mark.parametrize("art,cat,paths", [
    ("GRIMALDI.CARGA_MASSIFICADOS_20250415", "tabela", None),
    ("SEGUROS.RECLAMACOES_ICATU_ABR25", "tabela", None),
    ("X.BASE_MARÇO25", "tabela", None),                      # upper() fora do ASCII
    ("ALVESDS.EMP_8_20260305._GCP", "tabela", None),
    ("ATIVOS.ATIVOS_ENCART_23_202509.30", "tabela", None),
    ("grimaldi.carga_massificados_202506", "tabela", None),
    ("202506", "tabela", None),
    ("EXCECOES_20250701.CSV", "arquivo", "/RISCOSBV/COBRANCA/EXCECOES_20250701.CSV"),
    ("EXCECOES_20250701.CSV", "arquivo", "\\\\srv\\COBRANCA\\EXCECOES_20250701.CSV | /B/X.CSV"),
    ("EXCECOES_20250701.CSV", "arquivo", ""),
    ("EXCECOES_20250701.CSV", "arquivo", None),
    ("ANSWERS.CSV", "arquivo", "/A/B/ANSWERS.CSV"),
    ("SCRIPT_20250101.SAS", "script", None),
])
def test_chave_de_familia_no_postgres_igual_a_regra_python(conn, art, cat, paths):
    expr = F.familia_candidata_sql(_lit(art), _lit(cat), _lit(paths), overrides=SEM_OVERRIDES)
    assert conn.execute(f"SELECT {expr}").fetchone()[0] == F.familia_candidata(art, cat, paths)


@precisa_pg
@pytest.mark.parametrize("lista,valores", [
    ("Cobranças | Crédito | Riscos", ["Crédito"]),
    ("Cobranças | Crédito | Riscos", ["Créd"]),               # pedaço de item não casa
    (" Cobranças|Riscos ", ["Riscos", "Jurídico"]),
    ("Planejamento e P&L (Rodas)", ["Planejamento e P&L (Rodas)"]),
    ("O'Brien | X", ["O'Brien"]),
])
def test_lista_tem_algum_casa_item_a_item(conn, monkeypatch, lista, valores):
    monkeypatch.setattr(m.dialeto, "PG", True)       # literal com a regra de aspas do Postgres
    esperado = any(v in [t.strip() for t in lista.split("|")] for v in valores)
    assert conn.execute(f"SELECT {m._lista_tem_algum(_lit(lista), valores)}").fetchone()[0] is esperado
```

- [ ] **Step 2: Rodar e ver falhar.** Esperado:
  - os casos de família dão erro de sintaxe no Postgres (a expressão leva `split(...)[0]` em todos);
  - os de lista dão `AttributeError: module 'backend.main' has no attribute '_lista_tem_algum'`.

- [ ] **Step 3: Implementar**

```diff
--- a/egps_analysis/app/backend/familias.py
+++ b/egps_analysis/app/backend/familias.py
@@ -104,7 +104,7 @@ def diretorio_de(paths):
     caixa alta. Vazio = sem evidência de localização, e aí o arquivo não colapsa.
 
     O PRIMEIRO, não o menor nem o ordenado: é o que a forma SQL consegue reproduzir com
-    `split(...)[0]` sem ordenar, e as duas formas têm de dar a mesma chave (ver o cabeçalho
+    `element_at(split(...), 1)` sem ordenar, e as duas formas têm de dar a mesma chave (ver o cabeçalho
     do módulo). Arquivo em 2 pastas fica com a chave da 1ª — conservador: no máximo deixa
     de juntar, nunca junta errado."""
     p = (paths or "").split(" | ")[0].strip()
@@ -372,10 +372,12 @@ def familia_candidata_sql(art="artifact", cat="categoria", paths="''", overrides
     ov = overrides if overrides is not None else carrega_overrides()
     up = f"upper({art})"
     regra = (f"coalesce(nullif(regexp_replace({up}, {_lit(_TOKEN)}, ''), ''), {up})")
-    # SAFRA EM ARQUIVO: espelho de `diretorio_de()` + a regra do candidato. `split(x, ...)[0]`
-    # pega o PRIMEIRO caminho, igual ao Python; `regexp_replace` tira o nome do arquivo e o
-    # separador final. `{regra} <> {up}` é o "só datado colapsa"; diretório vazio não colapsa.
-    prim = f"split({paths}, ' [|] ')[0]"
+    # SAFRA EM ARQUIVO: espelho de `diretorio_de()` + a regra do candidato. `element_at(.., 1)`
+    # pega o PRIMEIRO caminho, igual ao Python, nos dois bancos (`split(x)[0]` não roda no
+    # Postgres, onde o índice começa em 1 e função não aceita colchete); `regexp_replace` tira
+    # o nome do arquivo e o separador final. `{regra} <> {up}` é o "só datado colapsa";
+    # diretório vazio não colapsa.
+    prim = f"element_at(split({paths}, ' [|] '), 1)"
     _nao_sep = "'[^/" + "\\\\" * 2 + "]*$'"
     _sep_fim = "'[/" + "\\\\" * 2 + "]$'"
     dir_ = f"upper(regexp_replace(regexp_replace({prim}, {_nao_sep}, ''), {_sep_fim}, ''))"
```

```diff
--- a/egps_analysis/app/backend/egps_atualizados.py
+++ b/egps_analysis/app/backend/egps_atualizados.py
@@ -304,7 +304,7 @@ def register(app, run_sql, fq: str, modern_expr: str, http_exc, enrich_contexto,
                 ) WHERE rn = 1
             ) m
             LEFT JOIN {_prontidao} p ON p.versao_id = m.versao_id
-            ORDER BY m.area, m.nome
+            ORDER BY m.area NULLS FIRST, m.nome NULLS FIRST
         """
         try:
             rows = run_sql(sql) or []
@@ -456,14 +456,14 @@ def register(app, run_sql, fq: str, modern_expr: str, http_exc, enrich_contexto,
             LEFT JOIN {t_mon} i ON v.chave_canonica = i.chave_canonica
             LEFT JOIN {_ma} ma ON ma.chave_canonica = v.chave_canonica
             WHERE v.versao_id = {vids}
-            ORDER BY v.categoria, v.artefato
+            ORDER BY v.categoria NULLS FIRST, v.artefato NULLS FIRST
         """) or []
         outputs = run_sql(f"""
             SELECT chave_canonica, artefato, situacao, novo, removido,
                    n_consumidores_externos, padrao,
                    coalesce(categoria, 'tabela') AS categoria
             FROM {t_out} WHERE versao_id = {vids}
-            ORDER BY removido DESC, situacao, artefato
+            ORDER BY removido DESC NULLS LAST, situacao NULLS FIRST, artefato NULLS FIRST
         """) or []
         v = _tipa(versao[0])
         _anexa_antecessores([v])
```

```diff
--- a/egps_analysis/app/backend/main.py
+++ b/egps_analysis/app/backend/main.py
@@ -662,6 +662,15 @@ def sql_lit(v):
     return dialeto.lit(v)
 
 
+def _lista_tem_algum(lista_sql, valores):
+    """SQL: a lista em texto `lista_sql` ('a | b | c') tem algum dos `valores`, item a item e
+    sem os espaços das pontas. Roda igual no Spark e no Postgres: sem lambda (`x -> trim(x)`)
+    nem `array(...)`, que o Postgres não tem; `instr` e `regexp_replace` existem nos dois
+    (no Postgres, em compat). `valores` não pode ser vazio."""
+    norm = f"concat('|', regexp_replace(trim({lista_sql}), ' *[|] *', '|'), '|')"
+    return "(" + " OR ".join(f"instr({norm}, {sql_lit('|' + v + '|')}) > 0" for v in valores) + ")"
+
+
 def _sql_http_error(msg):
     """Mapeia falha de SQL/SDK para o status HTTP correto (permissão→403, token→401)."""
     low = (msg or "").lower()
@@ -921,7 +930,7 @@ def responsaveis_bv_list(incluir_inativos: bool = False):
     _ensure_responsaveis_bv_table()
     where = "" if incluir_inativos else "WHERE ativo IS NOT false"
     rows = run_sql(f"SELECT nome_key, nome, subarea, ativo FROM {T_RESPBV} {where} "
-                   f"ORDER BY subarea, nome")
+                   f"ORDER BY subarea NULLS FIRST, nome NULLS FIRST")
     return {"rows": rows, "is_gestao": _is_gestao()}
 
 
@@ -1224,9 +1233,7 @@ def metrics(scope: str = "indi", area: list[str] = Query(default=[])):
         conds.append("escopo_indi = true")
     if area:
         # areas é multivalorado (pipe-delimitado): "Cobranças | Crédito | Riscos".
-        arr = ", ".join(sql_lit(a) for a in area)
-        conds.append(f"areas IS NOT NULL AND arrays_overlap("
-                     f"transform(split(areas, '[|]'), x -> trim(x)), array({arr}))")
+        conds.append(f"areas IS NOT NULL AND {_lista_tem_algum('areas', area)}")
     where = (" WHERE " + " AND ".join(conds)) if conds else ""
     mod = _modern()
     rows = run_sql(
@@ -1555,7 +1562,9 @@ def _sanitizacao_derivada():
 SAN_LOG_CHAVE = "san_contadores"
 # Saída de emergência do log, sem redeploy do resto: desligar NÃO muda nenhum número
 # da fila (é o critério de aceite do ticket 15, e test_desligar_o_log_nao_muda_*).
-_SAN_LOG_ON = os.environ.get("SAN_LOG_DIARIO", "1").strip().lower() not in ("0", "false", "no")
+# Na AWS (ADR 0005, Fase 1) o app só lê: quem grava o log é o app do Databricks.
+_SAN_LOG_ON = (os.environ.get("SAN_LOG_DIARIO", "1").strip().lower() not in ("0", "false", "no")
+               and not dialeto.PG)
 _san_log_dia = None   # dia já gravado por ESTE processo (a escrita é idempotente por data)
 
 
@@ -2110,7 +2119,7 @@ def _dataset_escopo(scope, areas=()):
             rows = _enrich_autoprodutor(_enrich_vinculo_ativo(_enrich_n_proj_ativos(run_sql(
                 f"SELECT {INPUTS_COLS} FROM {T_IN} i WHERE chave_canonica IN "
                 f"(SELECT DISTINCT chave_canonica FROM {T_EGP} WHERE projeto IN ({fin})) "
-                f"ORDER BY qtd_projetos DESC, artifact LIMIT {SCOPE_DATASET_CAP}")),
+                f"ORDER BY qtd_projetos DESC NULLS LAST, artifact LIMIT {SCOPE_DATASET_CAP}")),
                 f"e.projeto IN ({fin})"))
             # inputs consumidos EXCLUSIVAMENTE por ex-dependências: entram FLAGADOS
             # (ex_dependencia=True) — linha cinza + chip off-by-default no front; NUNCA
@@ -2122,7 +2131,7 @@ def _dataset_escopo(scope, areas=()):
                 ex_rows = [r for r in run_sql(
                     f"SELECT {INPUTS_COLS} FROM {T_IN} i WHERE chave_canonica IN "
                     f"(SELECT DISTINCT chave_canonica FROM {T_EGP} WHERE projeto IN ({exin})) "
-                    f"ORDER BY qtd_projetos DESC, artifact LIMIT {SCOPE_DATASET_CAP}")
+                    f"ORDER BY qtd_projetos DESC NULLS LAST, artifact LIMIT {SCOPE_DATASET_CAP}")
                     if r["chave_canonica"] not in seen]
                 _enrich_autoprodutor(_enrich_vinculo_ativo(_enrich_n_proj_ativos(ex_rows), f"e.projeto IN ({exin})"))
                 for r in ex_rows:
@@ -2143,7 +2152,7 @@ def _dataset_escopo(scope, areas=()):
         ew = "e.escopo_indi = true" if scope == "indi" else "true"
         _rows = _enrich_autoprodutor(_enrich_vinculo_ativo(_enrich_n_proj_ativos(run_sql(
             f"SELECT {INPUTS_COLS} FROM {T_IN} i{wsql} "
-            f"ORDER BY qtd_projetos DESC, artifact LIMIT {SCOPE_DATASET_CAP}")), ew))
+            f"ORDER BY qtd_projetos DESC NULLS LAST, artifact LIMIT {SCOPE_DATASET_CAP}")), ew))
         sanitizacao.aplica_em_linhas(_rows, _sanitizacao_derivada())
         return _marca_extra(_marca_safra(_agrega_familias(_rows) if FAMILIAS_ON else _rows))
     return _cache_scope_dataset(scope, _produce_scope)
@@ -2242,9 +2251,7 @@ def inputs(scope: str = "indi", categoria: list[str] = Query(default=[]),
     if scope == "indi":
         where.append("escopo_indi = true")
     if area:
-        arr = ", ".join(sql_lit(a) for a in area)
-        where.append(f"areas IS NOT NULL AND arrays_overlap("
-                     f"transform(split(areas, '[|]'), x -> trim(x)), array({arr}))")
+        where.append(f"areas IS NOT NULL AND {_lista_tem_algum('areas', area)}")
     cats = [c for c in categoria if c in CATEGORIAS]
     if cats:
         where.append(f"categoria IN ({', '.join(sql_lit(c) for c in cats)})")
@@ -2276,7 +2283,7 @@ def inputs(scope: str = "indi", categoria: list[str] = Query(default=[]),
     total = run_sql(f"SELECT count(*) AS n FROM {T_IN}{wsql}")[0]["n"]
     rows = _enrich_autoprodutor(_enrich_vinculo_ativo(_enrich_n_proj_ativos(run_sql(
         f"SELECT {INPUTS_COLS} "
-        f"FROM {T_IN} i{wsql} ORDER BY qtd_projetos DESC, artifact LIMIT {READ_CAP}")),
+        f"FROM {T_IN} i{wsql} ORDER BY qtd_projetos DESC NULLS LAST, artifact LIMIT {READ_CAP}")),
         "e.escopo_indi = true" if scope == "indi" else "true"))
     sanitizacao.aplica_em_linhas(rows, _sanitizacao_derivada())
     # Caminho FILTRADO (legado): continua no grão SAFRA mesmo com a flag ligada, e se
@@ -2403,8 +2410,8 @@ def _detalhe_familia(cat, fam, membros):
     produtores = run_sql(
         f"SELECT DISTINCT ed.depende_do AS projeto, n.area, n.onda, n.escopo_indi, n.ciclo_id "
         f"FROM {T_ED} ed LEFT JOIN {T_ND} n ON ed.depende_do = n.projeto "
-        f"WHERE arrays_overlap(transform(split(upper(ed.via_tabelas), '[|]'), x -> trim(x)), "
-        f"array({art_in})) ORDER BY n.escopo_indi DESC, projeto")
+        f"WHERE {_lista_tem_algum('upper(ed.via_tabelas)', membros)} "
+        f"ORDER BY n.escopo_indi DESC NULLS LAST, projeto")
     escolhas = _producer_choices()
     com_escolha = {a: escolhas[a] for a in membros if escolhas.get(a)}
     # Só poda quando TODAS as safras têm produtor canônico escolhido. A versão anterior
@@ -2855,7 +2862,7 @@ def input_detail(chave: str = ""):
         f"FROM {T_EGP} e LEFT JOIN {T_ND} n ON e.projeto = n.projeto "
         f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
         f"WHERE e.chave_canonica = {sql_lit(chave)} "
-        f"ORDER BY link_broken ASC, n.escopo_indi DESC, e.projeto")
+        f"ORDER BY link_broken ASC NULLS FIRST, n.escopo_indi DESC NULLS LAST, e.projeto")
     # Statement Execution API serializa bool como string ("true"/"false"); coerção
     # explícita p/ FastAPI enviar JSON bool, senão o front lê 'false' como truthy.
     for r in egps:
@@ -2869,7 +2876,7 @@ def input_detail(chave: str = ""):
         f"SELECT DISTINCT ed.depende_do AS projeto, n.area, n.onda, n.escopo_indi, n.ciclo_id "
         f"FROM {T_ED} ed LEFT JOIN {T_ND} n ON ed.depende_do = n.projeto "
         f"WHERE instr(upper(concat(' | ', ed.via_tabelas, ' | ')), {sql_lit(needle)}) > 0 "
-        f"ORDER BY n.escopo_indi DESC, projeto")
+        f"ORDER BY n.escopo_indi DESC NULLS LAST, projeto")
     _ch = _producer_choices().get(artifact)
     if _ch and any(p.get("projeto") == _ch for p in produtores):
         # produtor canonico escolhido -> mostra so ele (poda os demais candidatos)
@@ -2939,7 +2946,7 @@ def outputs(scope: str = "indi", only_multi: bool = False):
         return {"total": 0, "returned": 0, "capped": False, "rows": []}
     _cols = ("chave_canonica, artifact, categoria, areas, qtd_produtores, "
              "qtd_consumidores, terminal, modernizada_auto, escopo_indi")
-    _order = " ORDER BY qtd_consumidores DESC, artifact"
+    _order = " ORDER BY qtd_consumidores DESC NULLS LAST, artifact"
     try:
         # qtd_criadores/paths_fisicos podem não existir em tabela pré-republish: fallback em cascata.
         rows = run_sql(f"SELECT {_cols}, qtd_criadores, paths_fisicos FROM {T_OUT}{where}{_order}")
@@ -4314,7 +4321,7 @@ def indicium():
         f"n.projeto AS node_projeto, n.onda, n.ciclo_id, "
         f"(n.projeto IS NOT NULL) AS recebido "
         f"FROM {T_ESC} i LEFT JOIN {T_ND} n ON i.projeto = n.projeto AND i.projeto <> '' "
-        f"ORDER BY recebido, i.area, i.egp_dor1")
+        f"ORDER BY recebido NULLS FIRST, i.area NULLS FIRST, i.egp_dor1 NULLS FIRST")
     return {"rows": rows}
 
 
@@ -5579,7 +5586,7 @@ def lineage_areas():
         rows = run_sql(
             f"SELECT area, count(*) AS n, "
             f"sum(CASE WHEN escopo_indi THEN 1 ELSE 0 END) AS n_indi "
-            f"FROM {T_ND} GROUP BY area ORDER BY area")
+            f"FROM {T_ND} GROUP BY area ORDER BY area NULLS FIRST")
         return {"rows": rows}
     return _cache_lineage(("areas",), _produce)
 
@@ -6851,7 +6858,7 @@ def _migrados_mes(frontier):
         r = run_sql(
             f"SELECT count(DISTINCT projeto) AS n FROM {T_PIPE_AUD} "
             f"WHERE funil = 'migracao' AND campo = 'status' AND valor_novo = 'Migrado' "
-            f"AND substr(ts, 1, 7) = date_format(current_date(), 'yyyy-MM') "
+            f"AND substr(ts, 1, 7) = date_format(current_date, 'yyyy-MM') "
             f"AND projeto IN ({inl})")
         return int(r[0]["n"]) if r and r[0].get("n") is not None else 0
     except HTTPException:
@@ -8130,6 +8137,8 @@ def priorizacao(scope: str = "indi", area: str = "", deps: str = "transitive", c
     if snap is not None:
         return _com_extras(_poda_fora_da_linha_base(snap))
     payload = _compute_priorizacao(scope, area, deps, capacidade)
+    if dialeto.PG:   # Fase 1 na AWS só lê (ADR 0005): quem congela o plano é o Databricks
+        return _com_extras({**payload, "snapshot": None})
     try:
         _write_prio_snapshot(payload, "'auto'", sp=True)
     except Exception as e:
@@ -8310,7 +8319,8 @@ def _aud_monitor_sql(lim, where=""):
         f"CAST(updated_at AS STRING) AS updated_at, count(*) AS n_safras "
         f"FROM {T_AUD}{where} "
         f"GROUP BY {fam}, {cat}, campo, valor_antigo, valor_novo, updated_by, updated_at "
-        f"ORDER BY updated_at DESC LIMIT {lim}")
+        f"ORDER BY updated_at DESC, chave_canonica, campo, valor_antigo NULLS FIRST, "
+        f"valor_novo NULLS FIRST LIMIT {lim}")
 
 
 @app.get("/api/audit")
@@ -8367,7 +8377,7 @@ def audit(chave: str = "", limit: int = 200):
     for r in _safe(
         f"SELECT projeto, campo, valor_antigo, valor_novo, ator, "
         f"CAST(ts AS STRING) AS ts FROM {T_PIPE_AUD} "
-        f"ORDER BY ts DESC LIMIT {lim}"):
+        f"ORDER BY ts DESC, projeto, campo, valor_novo NULLS FIRST LIMIT {lim}"):
         merged.append({
             "fonte": "EGPs",
             "chave_canonica": r.get("projeto"),
@@ -8380,7 +8390,7 @@ def audit(chave: str = "", limit: int = 200):
 
     for r in _safe(
         f"SELECT acao, egp_dor1, projeto, ator, CAST(ts AS STRING) AS ts "
-        f"FROM {T_ESC_AUD} ORDER BY ts DESC LIMIT {lim}"):
+        f"FROM {T_ESC_AUD} ORDER BY ts DESC, egp_dor1, acao LIMIT {lim}"):
         acao = r.get("acao")
         if acao == "remove":
             va, vn = "no escopo", "removido"
@@ -8399,7 +8409,7 @@ def audit(chave: str = "", limit: int = 200):
     for r in _safe(
         f"SELECT projeto, chave_canonica, valor_antigo, valor_novo, ator, "
         f"CAST(ts AS STRING) AS ts FROM {T_LINK_AUD} "
-        f"ORDER BY ts DESC LIMIT {lim}"):
+        f"ORDER BY ts DESC, projeto, chave_canonica LIMIT {lim}"):
         merged.append({
             "fonte": "Vínculos",
             "chave_canonica": r.get("projeto"),                          # entidade no Histórico: o EGP
```

- [ ] **Step 4: Rodar e ver passar**

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q backend
```

Esperado: tudo verde (735 em 14/10). A suíte do backend cobre o lado Databricks do mesmo SQL. Os 18 casos novos rodam no Postgres.

---

## Parte C — Comparadores

### Task C1: Comparação tabela a tabela

**Files:**
- Create: `paridade/tabelas.py`, `paridade/test_tabelas.py`

- [ ] **Step 1: Teste**

```python
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from paridade import tabelas  # noqa: E402


def test_igual_mesmo_fora_de_ordem():
    r = tabelas.diferenca([("a", "1"), ("b", "2")], [("b", "2"), ("a", "1")], ("x", "y"))
    assert r["so_no_databricks"] == r["so_no_postgres"] == 0


def test_conta_repetidas_e_aponta_a_coluna_sem_mostrar_valor():
    r = tabelas.diferenca([("a", "1"), ("a", "1")], [("a", "1"), ("a", "2")], ("x", "y"))
    assert (r["so_no_databricks"], r["so_no_postgres"]) == (1, 1)
    assert r["colunas_que_diferem"] == ["y"]
    assert "1" not in repr(r["colunas_que_diferem"])
```

- [ ] **Step 2: Rodar e ver falhar** (`ImportError: cannot import name 'tabelas' from 'paridade'`).

- [ ] **Step 3: Implementar**

```python
# -*- coding: utf-8 -*-
"""Compara, tabela a tabela, o espelho no Postgres com o Databricks — ADR 0005, Fase 1.

Vem antes da comparação por rota (paridade.compara): prova que a cópia é fiel célula a
célula, NO FORMATO QUE O APP RECEBE — o Databricks em JSON_ARRAY, como o run_sql do app, e o
Postgres pela view compat formatada por db_pg.texto. A comparação é de multiconjunto (o
Delta não tem ordem). Não imprime valor nenhum (há e-mail e texto livre): só contagens e o
nome das colunas que diferem.

Rode logo depois de uma sincronização: o que alguém editar no app do Databricks entre a
sincronização e a comparação aparece como diferença (rode de novo para confirmar).

Uso (a partir de egps_analysis/app):
  DATABRICKS_CONFIG_PROFILE=<perfil> PG_DSN=postgresql://... \\
    python -m paridade.tabelas --warehouse <id> [--origem bv_dev_db.monitoramento_sas] [--tabela sas_x]
"""
import argparse
import collections
import os
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import db_pg  # noqa: E402
from sync import espelho, leitor  # noqa: E402


def diferenca(antigo, novo, colunas):
    """antigo/novo: listas de tuplas (texto). Devolve o resumo sem valores."""
    a, b = collections.Counter(antigo), collections.Counter(novo)
    so_a, so_b = a - b, b - a
    cols = set()
    for x in so_a:                     # coluna que difere entre a linha que sobrou de cada lado
        for y in so_b:                 # e a mais parecida do outro lado
            dif = [c for c, p, q in zip(colunas, x, y) if p != q]
            if len(dif) <= max(1, len(colunas) // 3):
                cols.update(dif)
                break
    return {"linhas_databricks": len(antigo), "linhas_postgres": len(novo),
            "so_no_databricks": sum(so_a.values()), "so_no_postgres": sum(so_b.values()),
            "colunas_que_diferem": sorted(cols)}


def le_postgres(conn, tabela):
    cols = espelho.colunas(tabela)
    return [tuple(db_pg.texto(v) for v in r)
            for r in conn.execute(f"SELECT {', '.join(cols)} FROM compat.{tabela}")]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compara o espelho com o Databricks, tabela a tabela")
    ap.add_argument("--warehouse", default=os.environ.get("DATABRICKS_WAREHOUSE_ID"))
    ap.add_argument("--origem", default="bv_dev_db.monitoramento_sas")
    ap.add_argument("--tabela", action="append")
    args = ap.parse_args(argv)
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    iguais, total = 0, 0
    with psycopg.connect(os.environ.get("PG_DSN") or "") as conn:
        for t in args.tabela or espelho.TABELAS:
            cols = espelho.colunas(t)
            antigo = [tuple(r[c] for c in cols)
                      for r in leitor.le_tabela(w, args.warehouse, f"{args.origem}.{t}", cols)]
            r = diferenca(antigo, le_postgres(conn, t), cols)
            igual = r["so_no_databricks"] == r["so_no_postgres"] == 0
            iguais, total = iguais + igual, total + 1
            print(f"[tabelas] {'IGUAL' if igual else 'DIFERE'} {t}: {r}", flush=True)
    print(f"[tabelas] {iguais}/{total} tabelas iguais")
    sys.exit(0 if iguais == total else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar e ver passar.** Esperado: `2 passed`.

### Task C2: Comparação de rotas — ordem, diferenças por desenho, mesmo erro, amostras

**Files:**
- Modify: `paridade/compara.py`, `paridade/test_compara.py`
- Create: `paridade/amostras.py`

- [ ] **Step 1: Testes**

```diff
--- a/egps_analysis/app/paridade/test_compara.py
+++ b/egps_analysis/app/paridade/test_compara.py
@@ -42,3 +42,37 @@ def test_rotas_get_ignora_parametro_de_caminho_e_metodo_de_escrita():
     app = NS(routes=[NS(path="/api/a", methods={"GET"}), NS(path="/api/b/{id}", methods={"GET"}),
                      NS(path="/api/c", methods={"PATCH"}), NS(path="/static", methods={"GET"})])
     assert c.rotas_get(app) == ["/api/a"]
+
+
+def test_lista_sem_ordem_na_origem_compara_como_multiconjunto():
+    livres = (("$.blocked", "set"),)
+    assert c.diferencas({"blocked": ["a", "b"]}, {"blocked": ["b", "a"]}, livres=livres) == []
+    assert c.diferencas({"blocked": ["a", "b"]}, {"blocked": ["b", "c"]}, livres=livres) \
+        == [("$.blocked[multiconjunto]", 2, 2)]
+    assert c.diferencas({"outra": ["a", "b"]}, {"outra": ["b", "a"]}, livres=livres) != []
+
+
+def test_diferenca_por_desenho_sai_a_parte_e_rota_fora_nao_e_buscada():
+    vistos = []
+
+    def busca(base, rota):
+        vistos.append(rota)
+        return {"table": base, "ok": True}
+
+    rel = c.compara("http://antigo", "http://novo", ["/api/health", "/api/prioridades"], busca=busca)
+    assert rel["/api/health"]["igual"] and rel["/api/health"]["aceitas"][0][0] == "$.table"
+    assert rel["/api/prioridades"]["fora"] and "/api/prioridades" not in vistos
+
+
+def test_mesmo_erro_http_nos_dois_lados_e_igual_e_erro_de_um_lado_so_nao():
+    import urllib.error
+
+    def busca(base, rota):
+        if rota == "/api/precisa-param" or base == "http://novo":
+            raise urllib.error.HTTPError(base + rota, 422 if rota == "/api/precisa-param" else 502,
+                                         "x", {}, None)
+        return {"ok": True}
+
+    rel = c.compara("http://antigo", "http://novo", ["/api/precisa-param", "/api/so-novo-quebra"], busca=busca)
+    assert rel["/api/precisa-param"] == {"igual": True, "mesmo_erro": 422}
+    assert "erro" in rel["/api/so-novo-quebra"]
```

- [ ] **Step 2: Rodar e ver falhar** (`TypeError: diferencas() got an unexpected keyword argument 'livres'`).

- [ ] **Step 3: Implementar**

```diff
--- a/egps_analysis/app/paridade/compara.py
+++ b/egps_analysis/app/paridade/compara.py
@@ -12,14 +12,44 @@ Uso: python -m paridade.compara --antigo http://localhost:8000 --novo http://loc
 """
 import argparse
 import datetime
+import fnmatch
 import json
 import re
 import sys
+import urllib.error
+import urllib.parse
 import urllib.request
 
 _INSTANTE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
 _NUMERO = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")
 
+# Listas SEM ordem definida na origem — a ordem muda até entre dois processos do MESMO app,
+# então ordem diferente aqui não é diferença: compara como multiconjunto. Cada entrada diz
+# por quê; lista com ORDER BY nunca entra aqui.
+ORDEM_LIVRE = {
+    "/api/lineage/graph": (("$.blocked", "set do Python"), ("$.dep_of.*", "set do Python")),
+    "/api/inputs-egps": (("$.rows", "SQL sem ORDER BY (export CSV)"),),
+    "/api/outputs-egps": (("$.rows", "SQL sem ORDER BY (export CSV)"),),
+}
+# Diferenças POR DESENHO entre o app do Databricks e o da AWS (ADR 0005), com o motivo.
+ACEITAS = {
+    "/api/health": (("$.table", "nome qualificado do schema"), ("$.warehouse", "não há warehouse na AWS")),
+    "/api/config": (("$.scope", "nome qualificado do schema"),
+                    ("$.sincronizado_em", "só existe na AWS"),
+                    ("$.somente_leitura", "AWS em modo leitura")),
+    "/api/me": (("$.papel", "papel só existe no Postgres"),),
+}
+# Rotas que ficam de fora de propósito.
+FORA = {"/api/prioridades": "sas_egp_prioridades não migra (spec): rota sem tela"}
+
+
+def _base(rota):
+    return urllib.parse.urlsplit(rota).path
+
+
+def _casa(caminho, padroes):
+    return next((m for p, m in padroes if fnmatch.fnmatchcase(caminho, p)), None)
+
 
 def normaliza(v):
     if isinstance(v, dict):
@@ -45,8 +75,9 @@ def normaliza(v):
     return v
 
 
-def diferencas(a, b, caminho="$", limite=50):
-    """Lista de (caminho, antigo, novo) — no máximo `limite` itens."""
+def diferencas(a, b, caminho="$", limite=50, livres=()):
+    """Lista de (caminho, antigo, novo) — no máximo `limite` itens. `livres`: padrões
+    (fnmatch, com motivo) de listas comparadas como multiconjunto (ver ORDEM_LIVRE)."""
     saida = []
 
     def anda(x, y, c):
@@ -55,6 +86,10 @@ def diferencas(a, b, caminho="$", limite=50):
         if isinstance(x, dict) and isinstance(y, dict):
             for k in sorted(set(x) | set(y)):
                 anda(x.get(k, "<ausente>"), y.get(k, "<ausente>"), f"{c}.{k}")
+        elif isinstance(x, list) and isinstance(y, list) and _casa(c, livres):
+            chave = lambda v: json.dumps(v, sort_keys=True, default=str)  # noqa: E731
+            if sorted(map(chave, x)) != sorted(map(chave, y)):
+                saida.append((f"{c}[multiconjunto]", len(x), len(y)))
         elif isinstance(x, list) and isinstance(y, list):
             if len(x) != len(y):
                 saida.append((f"{c}[len]", len(x), len(y)))
@@ -90,17 +125,42 @@ def _busca(base, rota):
         return json.loads(r.read().decode("utf-8"))
 
 
+def _resposta(busca, base, rota):
+    """("ok", json) ou ("http", status) — erro HTTP é comportamento a comparar, não falha."""
+    try:
+        return ("ok", busca(base, rota))
+    except urllib.error.HTTPError as e:
+        return ("http", e.code)
+
+
 def compara(antigo, novo, rotas, busca=_busca):
     relatorio = {}
     for rota in rotas:
+        base = _base(rota)
+        if base in FORA:
+            relatorio[rota] = {"igual": True, "fora": FORA[base]}
+            continue
         try:
-            a, b = normaliza(busca(antigo, rota)), normaliza(busca(novo, rota))
+            ra, rb = _resposta(busca, antigo, rota), _resposta(busca, novo, rota)
+            if ra[0] == rb[0] == "http":
+                if ra[1] != rb[1]:
+                    raise RuntimeError(f"HTTP {ra[1]} no antigo x HTTP {rb[1]} no novo")
+                # mesmo erro nos dois (ex.: 422 de rota que exige parâmetro): mesmo comportamento
+                relatorio[rota] = {"igual": True, "mesmo_erro": ra[1]}
+                continue
+            if "http" in (ra[0], rb[0]):
+                raise RuntimeError(f"antigo {ra[1] if ra[0] == 'http' else 'ok'} x "
+                                   f"novo {rb[1] if rb[0] == 'http' else 'ok'}")
+            a, b = normaliza(ra[1]), normaliza(rb[1])
         except Exception as e:  # noqa: BLE001 — erro de rota é resultado, não para o resto
             relatorio[rota] = {"erro": f"{type(e).__name__}: {e}"}
             continue
-        dif = diferencas(a, b)
+        dif = diferencas(a, b, livres=ORDEM_LIVRE.get(base, ()))
+        aceitas = [list(d) + [_casa(d[0], ACEITAS.get(base, ()))]
+                   for d in dif if _casa(d[0], ACEITAS.get(base, ()))]
+        dif = [d for d in dif if not _casa(d[0], ACEITAS.get(base, ()))]
         relatorio[rota] = {"igual": not dif, "so_ordem": bool(dif) and so_ordem(a, b),
-                           "diferencas": [list(d) for d in dif]}
+                           "diferencas": [list(d) for d in dif], "aceitas": aceitas}
     return relatorio
 
 
@@ -110,6 +170,8 @@ def main(argv=None):
     ap.add_argument("--novo", required=True)
     ap.add_argument("--saida", required=True)
     ap.add_argument("--rota", action="append", help="rota GET (repita); padrão: todas")
+    ap.add_argument("--amostras", action="store_true",
+                    help="inclui as rotas com parâmetro (paridade.amostras; precisa de PG_DSN)")
     args = ap.parse_args(argv)
     if args.rota:
         rotas = args.rota
@@ -117,6 +179,10 @@ def main(argv=None):
         sys.path.insert(0, "backend")
         from backend import main as app_main  # import tardio: só para listar as rotas
         rotas = rotas_get(app_main.app)
+    if args.amostras:
+        import os
+        from paridade import amostras
+        rotas = rotas + amostras.rotas(os.environ["PG_DSN"])
     rel = compara(args.antigo, args.novo, rotas)
     with open(args.saida, "w", encoding="utf-8") as f:
         json.dump(rel, f, ensure_ascii=False, indent=2, default=str)
```

```python
# -*- coding: utf-8 -*-
"""Rotas GET com parâmetro, com valores de amostra tirados do próprio espelho (ADR 0005).

As rotas sem parâmetro (paridade.compara.rotas_get) não exercitam as que pedem `chave`,
`projeto` etc. nem os filtros que mudam o SQL (área, recorte). Aqui sai uma lista fixa de
rotas, com amostras ESCOLHIDAS DE FORMA DETERMINÍSTICA (ORDER BY), para a comparação
rodar igual duas vezes seguidas.
"""
import urllib.parse

import psycopg

_q = urllib.parse.quote


def rotas(dsn):
    with psycopg.connect(dsn) as c:
        c.execute("SET search_path = compat, derivado, pg_catalog, public")

        def um(sql, n=1):
            return [r[0] for r in c.execute(sql + f" LIMIT {n}")]

        area = um("SELECT area FROM sas_lineage_nodes WHERE escopo_indi GROUP BY area ORDER BY count(*) DESC, area")
        egps = (um("SELECT projeto FROM sas_lineage_nodes WHERE escopo_indi ORDER BY n_inputs DESC, projeto", 2)
                + um("SELECT projeto FROM sas_egp_pipeline WHERE egp_sucessor IS NOT NULL ORDER BY projeto")
                + um("SELECT projeto FROM sas_lineage_nodes WHERE NOT escopo_indi ORDER BY n_inputs DESC, projeto"))
        inputs = (um("SELECT chave_canonica FROM sas_inputs_monitor WHERE categoria = 'tabela' AND NOT orfao "
                     "ORDER BY qtd_projetos DESC, chave_canonica", 2)
                  + um("SELECT chave_canonica FROM sas_inputs_monitor WHERE categoria = 'arquivo' AND NOT orfao "
                       "ORDER BY qtd_projetos DESC, chave_canonica")
                  + um("SELECT chave_canonica FROM sas_inputs_monitor WHERE NOT orfao AND artifact ~ '_20[0-9]{4}' "
                       "ORDER BY qtd_projetos DESC, chave_canonica"))      # safra: caminho da família
        outputs = (um("SELECT chave_canonica FROM sas_outputs_monitor WHERE qtd_produtores > 1 "
                      "ORDER BY qtd_produtores DESC, chave_canonica")
                   + um("SELECT chave_canonica FROM sas_output_producer_choice ORDER BY chave_canonica"))
        nos = um("SELECT projeto_alvo FROM sas_lineage_edges GROUP BY projeto_alvo ORDER BY count(*) DESC, projeto_alvo")
        gestao = [("egp", x) for x in um("SELECT entity_id FROM sas_gestao_status WHERE entity = 'egp' "
                                          "GROUP BY entity_id ORDER BY count(*) DESC, entity_id")]
        gestao += [("input", x) for x in um("SELECT entity_id FROM sas_gestao_status WHERE entity = 'input' "
                                             "GROUP BY entity_id ORDER BY count(*) DESC, entity_id")]
        versoes = um("SELECT versao_id FROM sas_egp_atualizados ORDER BY versao_id", 2)
    saida = []
    saida += [f"/api/egp?projeto={_q(p)}" for p in egps]
    saida += [f"/api/input?chave={_q(k)}" for k in inputs]
    saida += [f"/api/audit?chave={_q(k)}" for k in inputs[:2]]
    saida += [f"/api/output?chave={_q(k)}" for k in outputs]
    saida += [f"/api/lineage/neighbors?node={_q(n)}&dir={d}" for n in nos for d in ("up", "down")]
    saida += [f"/api/gestao/status?entity={e}&id={_q(i)}" for e, i in gestao]
    saida += [f"/api/egp-atualizado?versao_id={_q(v)}" for v in versoes]
    for a in area:                              # filtros que mudam o SQL
        saida += [f"/api/metrics?scope=indi&area={_q(a)}",
                  f"/api/inputs?scope=indi&area={_q(a)}&categoria=tabela",
                  f"/api/inputs-egps?scope=indi&area={_q(a)}",
                  f"/api/scope-egps?scope=indi_deps&area={_q(a)}"]
    for s in ("indi_deps", "base"):
        saida += [f"/api/inputs?scope={s}", f"/api/outputs?scope={s}", f"/api/egp-readiness?scope={s}",
                  f"/api/scope-egps?scope={s}", f"/api/egp-input-units?scope={s}"]
    saida += ["/api/gestao/rows?entity=input", "/api/responsaveis-bv?incluir_inativos=true",
              "/api/analistas?incluir_inativos=true"]
    return saida
```

- [ ] **Step 4: Rodar e ver passar.** Esperado: `.venv/bin/python -m pytest -q paridade` → `11 passed` (com os 2 de `test_tabelas`).

---

## Parte D — Front sem controles de escrita

### Task D1: A regra e o hook

**Files:**
- Create: `frontend/src/escrita.ts`, `frontend/src/usePodeEscrever.ts`, `frontend/escrita.test.mts`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`

- [ ] **Step 1: Teste da regra**

```typescript
import assert from "node:assert/strict";
import { podeEscrever } from "./src/escrita.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

const LEITURA = { somente_leitura: true };
const ESCRITA = { somente_leitura: false };

check("AWS em modo leitura: ninguém vê escrita, nem gestão/admin", () => {
  assert.equal(podeEscrever(LEITURA, { user: "a@x", papel: "gestao" }), false);
  assert.equal(podeEscrever(LEITURA, { user: "a@x", papel: "admin" }), false);
});
check("leitor não vê escrita mesmo com o app gravável", () => {
  assert.equal(podeEscrever(ESCRITA, { user: "a@x", papel: "leitor" }), false);
});
check("gestão e admin com o app gravável veem", () => {
  assert.equal(podeEscrever(ESCRITA, { user: "a@x", papel: "gestao" }), true);
  assert.equal(podeEscrever(ESCRITA, { user: "a@x", papel: "admin" }), true);
});
check("Databricks: /api/me sem papel e config sem somente_leitura → como antes", () => {
  assert.equal(podeEscrever({}, { user: "a@x" }), true);
  assert.equal(podeEscrever({}, { user: null }), true);
});
check("antes de config/me chegarem não oferece escrita", () => {
  assert.equal(podeEscrever(undefined, { user: "a@x" }), false);
  assert.equal(podeEscrever(ESCRITA, undefined), false);
});
check("/api/me falhou: vale só o modo do app", () => {
  assert.equal(podeEscrever(ESCRITA, undefined, true), true);
  assert.equal(podeEscrever(LEITURA, undefined, true), false);
});
console.log(`${pass} ok`);
```

- [ ] **Step 2: Rodar e ver falhar** (a partir de `frontend/`): `node --experimental-strip-types escrita.test.mts` → `Cannot find module './src/escrita.ts'`.

- [ ] **Step 3: Regra e hook**

```typescript
// Quem vê controle de escrita (ADR 0005, Fase 1). Puro — testável sob node (escrita.test.mts);
// o hook que lê o cache do React Query mora em usePodeEscrever.ts.
//
// Na AWS o app de prod roda em modo leitura (`somente_leitura`) e o papel `leitor` não grava
// nunca: o backend recusa a escrita com 403, então a tela nem oferece o controle. No
// Databricks `somente_leitura` é false e `/api/me` não traz papel — tudo fica como antes.
export type MeResposta = { user: string | null; papel?: string | null };

export function podeEscrever(
  cfg: { somente_leitura?: boolean } | null | undefined,
  me: MeResposta | null | undefined,
  meFalhou = false,
): boolean {
  if (!cfg) return false;                // config ainda não chegou: não oferece escrita
  if (cfg.somente_leitura) return false;
  if (meFalhou) return true;             // sem /api/me vale só o modo do app (o backend ainda barra)
  if (!me) return false;
  return me.papel !== "leitor";
}
```

```typescript
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { podeEscrever } from "./escrita";

// Uma regra para a tela inteira: o componente que tem controle de escrita pergunta aqui.
// Lê as mesmas queryKeys (["config"], ["me"]) que o App semeia, sem requisição a mais.
export function usePodeEscrever(): boolean {
  const cfg = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me() });
  return podeEscrever(cfg.data, me.data, me.isError);
}
```

- [ ] **Step 4: Tipar o papel e semear o cache** (o hook lê `["config"]` e `["me"]` sem requisição a mais)

```diff
--- a/egps_analysis/app/frontend/src/api.ts
+++ b/egps_analysis/app/frontend/src/api.ts
@@ -8,6 +8,7 @@ import type {
   EgpsAtualizadosResponse, EgpAtualizadoDetail, ResponsaveisBvPayload, SanFragilidade,
   AguardandoCorpusPayload, EgpsSemVinculoPayload, EgpsExtras, EgpsNovosPayload,
 } from "./types";
+import type { MeResposta } from "./escrita";
 
 // `status` vai junto no Error (mensagem inalterada) p/ o retry global do React Query
 // distinguir 4xx (definitivo, não repete) de falha transitória — ver App.tsx.
@@ -38,7 +39,7 @@ function tempoFiltroInputParams(f: TempoFiltroInput): URLSearchParams {
 }
 
 export const api = {
-  me: () => fetch("api/me").then(json<{ user: string | null }>),
+  me: () => fetch("api/me").then(json<MeResposta>),
   config: () => fetch("api/config").then(json<AppConfig>),
   metrics: (scope: string, area: string[] = []) => {
     const p = new URLSearchParams();
```

```diff
--- a/egps_analysis/app/frontend/src/App.tsx
+++ b/egps_analysis/app/frontend/src/App.tsx
@@ -145,10 +145,13 @@ export function App() {
   }, []);
 
   useEffect(() => {
-    api.config().then(setCfg).catch((e: { status?: number }) => {
-      if (e?.status === 403) setSemAcesso(true);
-    });
-    api.me().then((r) => setUser(r.user)).catch(() => {});
+    // Semeia o cache: usePodeEscrever (controles de escrita) lê ["config"] e ["me"] sem
+    // fazer a mesma requisição de novo.
+    api.config().then((c) => { queryClient.setQueryData(["config"], c); setCfg(c); })
+      .catch((e: { status?: number }) => {
+        if (e?.status === 403) setSemAcesso(true);
+      });
+    api.me().then((r) => { queryClient.setQueryData(["me"], r); setUser(r.user); }).catch(() => {});
   }, []);
 
   // Prefetch das demais abas: aquece o cache em background quando cfg chega (precisa do
```

- [ ] **Step 5: Rodar e ver passar.** Esperado: `6 ok`.

### Task D2: Os componentes

Regra de aplicação:
- **Botão de ação some** quando `!pode`: Adicionar, Remover, ✕, ↺, Recalcular, Fechar como…, + Comentário, Vincular, Desfazer, "ainda é dependência", escolha de produtor.
- **Campo que mostra valor fica desabilitado** (`disabled`), e o valor continua legível. Onde o componente não aceita `disabled`, mostra o texto.
- **Componente que já tem `readOnly`:** passa a ler `readOnly || !pode`, sem mudar quem o chama.
- **"↻ Recalcular" da Priorização some também.** Ele é um POST que não grava, mas o backend recusa todo método de escrita no modo leitura.

- [ ] **`frontend/src/components/EgpDetailPanel.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx
+++ b/egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx
@@ -7,6 +7,7 @@ import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
 import { api } from "../api";
 import type { EgpDetail, EgpInput, OutputPipelineRow, OutputRow, ReadinessRow } from "../types";
 import { RespBvInput } from "./RespBvInput";
+import { usePodeEscrever } from "../usePodeEscrever";
 import { PIPELINE_PROJETO, PHANTOM_ETAPAS_MIGRACAO, opcoesStatusEgp, STATUS_HELP, SEG,
   PIPELINE_INPUT, STATUS_INPUT, confirmStatusTerminal, statusTrocaLabel } from "../pipeline";
 import { sugereFecharAntecessor, STATUS_FECHAMENTO } from "../vinculo";
@@ -96,6 +97,7 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
   const det = egpQ.data ?? null;
   const cfgQ = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
   const isGestao = !!cfgQ.data?.is_gestao;
+  const pode = usePodeEscrever();
 
   // Outputs produzidos por este EGP — reusa duas queries já cacheadas na aba Outputs (base scope):
   //   outputs        → OutputRow[] com produtor_escolhido/qtd_produtores/terminal/…
@@ -420,7 +422,7 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
                 <div className="c-etapa">
                   {/* etapa espelhada do sucessor (§3.2.7): o backend já recusa a escrita;
                       aqui só não se oferece o que vai ser recusado, igual à aba EGPs. */}
-                  <select value={cur.etapa ?? ""} disabled={vincRow?.etapa_editavel === false}
+                  <select value={cur.etapa ?? ""} disabled={vincRow?.etapa_editavel === false || !pode}
                     title={vincRow?.etapa_editavel === false
                       ? `Etapa espelhada de "${vincRow.sucessor}" — edite no EGP sucessor`
                       : undefined}
@@ -433,7 +435,7 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
                   </select>
                 </div>
                 <div className="c-status">
-                  <select value={cur.status ?? ""} disabled={!cur.etapa} title={STATUS_HELP}
+                  <select value={cur.status ?? ""} disabled={!cur.etapa || !pode} title={STATUS_HELP}
                     style={cur.status ? { background: SEG[cur.status]?.bg, color: SEG[cur.status]?.fg } : undefined}
                     onChange={(e) => { const v = e.target.value;
                       if (!confirmStatusTerminal(v, shortName(projeto))) return;
@@ -456,7 +458,7 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
                     onSave={(v) => pipeMut.mutate({ jira_id: v })} />
                 </div>
                 <div>
-                  <select value={cur.responsavel ?? ""} title="Responsável pela migração deste EGP"
+                  <select value={cur.responsavel ?? ""} title="Responsável pela migração deste EGP" disabled={!pode}
                     onChange={(e) => pipeMut.mutate({ responsavel: e.target.value })}>
                     <option value="">—</option>
                     {cur.responsavel && !analistas.some((a) => a.email === cur.responsavel) && (
@@ -488,7 +490,7 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
              recebimentos e só serve para ver o diff antigo x novo.
           Ficam na mesma seção, nesta ordem, cada uma dizendo o que é. */}
       <h3>Versão atualizada</h3>
-      <VinculoSucessorPanel projeto={projeto} row={pipeRow} isGestao={isGestao} onOpenEgp={onOpenEgp} />
+      <VinculoSucessorPanel projeto={projeto} row={pipeRow} isGestao={isGestao && pode} onOpenEgp={onOpenEgp} />
 
       {/* Substituído: o app SUGERE fechar o antecessor e a gestão aplica com 1 clique.
           Classificar nunca muda status sozinho (spec §3.5.21) — o backend só grava o
@@ -499,12 +501,14 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
             Substituído por <b>{shortName(pipeRow!.sucessor!)}</b> — etapa, mês, JIRA e
             responsável já foram copiados para lá. Fechar este EGP é decisão da gestão.
           </span>
-          <button className="link-btn" onClick={() => {
-            if (!confirmStatusTerminal(STATUS_FECHAMENTO, shortName(projeto))) return;
-            pipeMut.mutate({ status: STATUS_FECHAMENTO });
-          }}>
-            Fechar como “{STATUS_FECHAMENTO}”
-          </button>
+          {pode && (
+            <button className="link-btn" onClick={() => {
+              if (!confirmStatusTerminal(STATUS_FECHAMENTO, shortName(projeto))) return;
+              pipeMut.mutate({ status: STATUS_FECHAMENTO });
+            }}>
+              Fechar como “{STATUS_FECHAMENTO}”
+            </button>
+          )}
         </div>
       )}
 
@@ -518,10 +522,10 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
         versão já tiver entrado no corpus, ela vira a sugestão de sucessor no bloco acima.
       </div>
       <div className="egp-atu-section">
-        {pipeRow ? (
+        {pipeRow ? (pode ? (
           <AtualizadoLinkButton row={pipeRow} options={atualizadosOptions}
             onLink={(v) => atuMut.mutate(v)} />
-        ) : <span className="muted">carregando…</span>}
+        ) : <span>{pipeRow.atualizado_link_nome ?? "—"}</span>) : <span className="muted">carregando…</span>}
         {atuMut.isError && <span className="error">Falha ao salvar: {String(atuMut.error)}</span>}
       </div>
       {pipeRow?.atualizado_link_versao_id && (
@@ -600,13 +604,13 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
             // Broken row: só o toggle de vínculo é interativo — status/responsável/observação/último
             // status ficam trancados p/ evitar que esta view mute algo que este EGP declarou não usar.
             const glyphTitle = broken
-              ? (isGestao
+              ? (isGestao && pode
                 ? "Vínculo quebrado — não conta para modernização deste EGP. Clique para restaurar."
                 : "Vínculo quebrado (só gestão pode alterar)")
-              : (isGestao
+              : (isGestao && pode
                 ? "Vínculo ativo. Clique para quebrar (este EGP declara não depender deste input)."
                 : "Vínculo ativo");
-            const glyph = isGestao ? (
+            const glyph = isGestao && pode ? (
               <button className="rd-vinc-btn" onClick={() => toggleLink(i)}
                 disabled={linkMut.isPending} title={glyphTitle}>
                 {broken ? "⛓️‍💥" : "🔗"}
@@ -648,7 +652,7 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
                 </div>
                 <div><span className={`pill ${i.modernizada_auto === "Disponível" ? "ok" : "todo"}`}>{i.modernizada_auto}</span></div>
                 <div className="c-etapa">
-                  <select value={effEtapa(i.etapa, i.modernizada_auto)} disabled={broken || !!travaDerivada(i)}
+                  <select value={effEtapa(i.etapa, i.modernizada_auto)} disabled={broken || !!travaDerivada(i) || !pode}
                     title={broken ? "Vínculo quebrado — restaure para editar (não deveria mexer na etapa por aqui)" : travaDerivada(i)}
                     onChange={(e) => onPatch(i.chave_canonica, { etapa: e.target.value })}>
                     {PIPELINE_INPUT.map((s) => <option key={s} value={s}>{s}</option>)}
@@ -658,7 +662,7 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
                   {(() => {
                     const effSt = effStatusInput(i.status, i.etapa, i.modernizada_auto);
                     return (
-                      <select value={effSt} disabled={broken || !!travaDerivada(i)}
+                      <select value={effSt} disabled={broken || !!travaDerivada(i) || !pode}
                         style={{ background: SEG[effSt]?.bg, color: SEG[effSt]?.fg }}
                         title={broken ? "Vínculo quebrado — restaure para editar (não deveria mexer no status por aqui)" : travaDerivada(i)}
                         onChange={(e) => onPatch(i.chave_canonica, { status: e.target.value })}>
@@ -667,10 +671,10 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
                     );
                   })()}
                 </div>
-                <div><input defaultValue={i.responsavel ?? ""} placeholder="—" disabled={broken}
+                <div><input defaultValue={i.responsavel ?? ""} placeholder="—" disabled={broken || !pode}
                   title={broken ? "Vínculo quebrado — restaure para editar" : undefined}
                   onBlur={(e) => { const v = e.target.value; if (v !== (i.responsavel ?? "")) onPatch(i.chave_canonica, { responsavel: v }); }} /></div>
-                <div><input defaultValue={i.observacao ?? ""} placeholder="—" disabled={broken}
+                <div><input defaultValue={i.observacao ?? ""} placeholder="—" disabled={broken || !pode}
                   title={broken ? "Vínculo quebrado — restaure para editar" : undefined}
                   onBlur={(e) => { const v = e.target.value; if (v !== (i.observacao ?? "")) onPatch(i.chave_canonica, { observacao: v }); }} /></div>
                 {(() => {
@@ -702,13 +706,13 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
           <div className="egp-trow egp-pw-row">
             <div>
               <button type="button" className={`gm-toggle-btn gm-toggle-btn-sm${preworkingVal ? " on" : ""}`}
-                disabled={pwMut.isPending} title="Questionário de pré-working específico do EGP — clique para alternar"
+                disabled={pwMut.isPending || !pode} title="Questionário de pré-working específico do EGP — clique para alternar"
                 onClick={() => pwMut.mutate({ preworking: !preworkingVal })}>
                 {preworkingVal ? "✓ Preenchido" : "○ Não preenchido"}
               </button>
             </div>
             <div>
-              <input type="date" className="gm-out-date" value={pwDataInput} disabled={pwMut.isPending}
+              <input type="date" className="gm-out-date" value={pwDataInput} disabled={pwMut.isPending || !pode}
                 title="Data de referência do pré-working — 100% manual"
                 onChange={(e) => setPwDataInput(e.target.value)}
                 onBlur={() => {
@@ -754,7 +758,7 @@ export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
                         {isTruthy(row.terminal) ? "Terminal" : "Intermediário"}
                       </span>
                     </div>
-                    <OutputManualCell manual={outPipeMap.get(row.chave_canonica)} disabled={outPipeMut.isPending}
+                    <OutputManualCell manual={outPipeMap.get(row.chave_canonica)} disabled={outPipeMut.isPending || !pode}
                       onToggle={(recebido) => outPipeMut.mutate({ chave_canonica: row.chave_canonica, recebido })}
                       onDataBlur={(recebido_data) => outPipeMut.mutate({ chave_canonica: row.chave_canonica, recebido_data })}
                       onCargaFria={(carga_fria) => outPipeMut.mutate({ chave_canonica: row.chave_canonica, carga_fria })} />
```

- [ ] **`frontend/src/components/GestaoMigracao.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/GestaoMigracao.tsx
+++ b/egps_analysis/app/frontend/src/components/GestaoMigracao.tsx
@@ -20,6 +20,7 @@ import { mesTag, useMesPlan } from "../mesPlan";
 import { STATUS_PROJETO } from "../pipeline";
 import { useSubareas } from "../useSubareas";
 import { subareasDe, ordenarSubareas } from "../subareas";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 // Concluído p/ o GRÁFICO: EGP = migrado/despriorizado (removido/despriorizado SEMPRE
 // contam — esforço entregue mesmo se descartado). Input = etapa Modernizado OU status
@@ -75,6 +76,7 @@ const gestaoAccessor = (r: GestaoRow, k: GestaoSortKey): string | number | null
 
 export function GestaoMigracao() {
   const qc = useQueryClient();
+  const pode = usePodeEscrever();
   const [entity, setEntity] = useState<EntityType>("egp");
   const [busca, setBusca] = useState("");
   const [etapasSel, setEtapasSel] = useState<Set<string>>(new Set());
@@ -558,7 +560,7 @@ export function GestaoMigracao() {
         <GestaoKanban entity={entity} rows={sorted} readiness={readinessMap} preworking={preworkingMap}
           respLabelOf={nomeDe} onOpenCard={setPanelId}
           colunasVisiveis={colunasKanbanSel} pctCategorias={pctCategoriasSel}
-          onToggleBV={(id, comBv) => setBV.mutate({ id, comBv })} />
+          onToggleBV={pode ? (id, comBv) => setBV.mutate({ id, comBv }) : undefined} />
       ) : (
       <div className="rsm-card">
         <table className="rsm-tbl gm-tbl">
@@ -587,7 +589,7 @@ export function GestaoMigracao() {
               <tr key={r.id}>
                 <td>
                   <label className="gm-bv-toggle" title={comBvAtual(r) ? "Com o BV — clique p/ trazer p/ nós" : "Conosco — clique p/ entregar ao BV"}>
-                    <input type="checkbox" checked={comBvAtual(r)}
+                    <input type="checkbox" checked={comBvAtual(r)} disabled={!pode}
                       onChange={(e) => setBV.mutate({ id: r.id, comBv: e.target.checked })} />
                     <span className="gm-bv-track"><span className="gm-bv-thumb" /></span>
                   </label>
@@ -603,21 +605,21 @@ export function GestaoMigracao() {
                 <td>{r.etapa ?? "—"}</td>
                 {entity === "input" && <td>{r.status ?? "—"}</td>}
                 <td>
-                  <button className="gm-date" title="Editar (abre confirmação)"
+                  <button className="gm-date" title="Editar (abre confirmação)" disabled={!pode}
                     onClick={() => setDateEdit({ id: r.id, nome: r.nome, campo: "inicio", atual: r.inicioMigracao })}>
                     {fmtBR(r.inicioMigracao)}
                   </button>
                 </td>
                 {entity === "egp" && (
                   <td>
-                    <button className="gm-date" title="Editar (abre confirmação)"
+                    <button className="gm-date" title="Editar (abre confirmação)" disabled={!pode}
                       onClick={() => setDateEdit({ id: r.id, nome: r.nome, campo: "fimConversao", atual: r.fimConversao })}>
                       {fmtBR(r.fimConversao)}
                     </button>
                   </td>
                 )}
                 <td>
-                  <button className="gm-date" title="Editar (abre confirmação)"
+                  <button className="gm-date" title="Editar (abre confirmação)" disabled={!pode}
                     onClick={() => setDateEdit({ id: r.id, nome: r.nome, campo: "fim", atual: r.fimMigracao })}>
                     {fmtBR(r.fimMigracao)}
                   </button>
```

- [ ] **`frontend/src/components/GestaoStatusHistory.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/GestaoStatusHistory.tsx
+++ b/egps_analysis/app/frontend/src/components/GestaoStatusHistory.tsx
@@ -4,6 +4,7 @@ import { gestaoApi, usuariosGestao, type EntityType, type GestaoRow } from "../g
 import { fmtBR, fmtTsBR } from "../diasUteis";
 import { api } from "../api";
 import { AddCommentModal } from "./GestaoStatusPanel";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 // Último status + histórico de comentários da Gestão (entity/id) + "+ Adicionar
 // Comentário" + Validação BV (só admins) — embutível em qualquer modal de detalhe.
@@ -27,6 +28,7 @@ export function GestaoStatusHistory({ entity, id }: { entity: EntityType; id: st
   const cfgQ = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
   const isGestao = !!cfgQ.data?.is_gestao;
   const isAdmin = !!cfgQ.data?.is_admin;
+  const pode = usePodeEscrever();
   const nomeDe = (email: string) => users.find((u) => u.email === email)?.nome ?? email;
   const invalidateRows = () => qc.invalidateQueries({ queryKey: ["gestao", entity] });
 
@@ -63,13 +65,15 @@ export function GestaoStatusHistory({ entity, id }: { entity: EntityType; id: st
               {[...gRow.bvEventos].reverse().map((ev) => (
                 <div className="gm-bv-ev" key={ev.id}>
                   <span>{fmtBR(ev.data)} · {ev.comBv ? "Com BV" : "Conosco"}{ev.autor ? ` · ${nomeDe(ev.autor)}` : ""}</span>
-                  <button className="gm-bv-del" title="Remover este evento (correção)"
-                    onClick={() => delBV.mutate(ev.id)} disabled={delBV.isPending}>✕</button>
+                  {pode && (
+                    <button className="gm-bv-del" title="Remover este evento (correção)"
+                      onClick={() => delBV.mutate(ev.id)} disabled={delBV.isPending}>✕</button>
+                  )}
                 </div>
               ))}
             </div>
           )}
-          <div className="gm-bv-corr">
+          {pode && <div className="gm-bv-corr">
             <select value={corrOn ? "on" : "off"} onChange={(e) => setCorrOn(e.target.value === "on")}>
               <option value="on">Com BV</option>
               <option value="off">Conosco</option>
@@ -79,13 +83,13 @@ export function GestaoStatusHistory({ entity, id }: { entity: EntityType; id: st
               onClick={() => { addBV.mutate({ comBv: corrOn, data: corrData }); setCorrData(""); }}>
               + evento na data
             </button>
-          </div>
+          </div>}
         </>
       )}
 
       {/* botão perto do Último status (decisão do develop 2026-08: comentar é sempre em
           relação ao mais recente — sem rolar pelo histórico inteiro) */}
-      {isGestao && (
+      {isGestao && pode && (
         <button className="theme-btn gm-add-btn" onClick={() => setModal(true)}>
           + Adicionar Comentário
         </button>
```

- [ ] **`frontend/src/components/GestaoStatusPanel.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/GestaoStatusPanel.tsx
+++ b/egps_analysis/app/frontend/src/components/GestaoStatusPanel.tsx
@@ -27,6 +27,7 @@ import { pendenciaInputParaEgp, respBvOf } from "./GestaoKanban";
 import { tabelaModernizada } from "../tabelaCorresp";
 import { useSubareas } from "../useSubareas";
 import { subareasDe } from "../subareas";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 interface Props {
   entity: EntityType;
@@ -57,7 +58,9 @@ interface Props {
 // `data` do status vem em UTC (current_timestamp() do warehouse) -> exibe em SP.
 const fmtTs = (iso: string) => fmtTsBR(iso);
 
-export function GestaoStatusPanel({ entity, row, allRows, users, onClose, hideResponsavel, readOnly, onOpenEgp, onOpenInput }: Props) {
+export function GestaoStatusPanel({ entity, row, allRows, users, onClose, hideResponsavel, readOnly: readOnlyProp, onOpenEgp, onOpenInput }: Props) {
+  const pode = usePodeEscrever();
+  const readOnly = readOnlyProp || !pode;
   const qc = useQueryClient();
   const [modal, setModal] = useState(false);
   const { mapa: mapaSub } = useSubareas();
@@ -520,7 +523,7 @@ export function GestaoStatusPanel({ entity, row, allRows, users, onClose, hideRe
             comentário é sempre em relação ao MAIS RECENTE — ficar perto dele, sem precisar
             rolar por Validação BV + Histórico inteiro, agiliza o fluxo comum de "só bater o
             olho no último e já comentar de novo". */}
-        {isGestao && (
+        {isGestao && pode && (
           <button className="theme-btn gm-add-btn" onClick={() => setModal(true)}>
             + Adicionar Comentário
           </button>
@@ -536,13 +539,15 @@ export function GestaoStatusPanel({ entity, row, allRows, users, onClose, hideRe
                 {[...row.bvEventos].reverse().map((ev) => (
                   <div className="gm-bv-ev" key={ev.id}>
                     <span>{fmtBR(ev.data)} · {ev.comBv ? "Com BV" : "Conosco"}{ev.autor ? ` · ${nomeDe(ev.autor)}` : ""}</span>
-                    <button className="gm-bv-del" title="Remover este evento (correção)"
-                      onClick={() => delBV.mutate(ev.id)} disabled={delBV.isPending}>✕</button>
+                    {pode && (
+                      <button className="gm-bv-del" title="Remover este evento (correção)"
+                        onClick={() => delBV.mutate(ev.id)} disabled={delBV.isPending}>✕</button>
+                    )}
                   </div>
                 ))}
               </div>
             )}
-            <div className="gm-bv-corr">
+            {pode && <div className="gm-bv-corr">
               <select value={corrOn ? "on" : "off"} onChange={(e) => setCorrOn(e.target.value === "on")}>
                 <option value="on">Com BV</option>
                 <option value="off">Conosco</option>
@@ -552,7 +557,7 @@ export function GestaoStatusPanel({ entity, row, allRows, users, onClose, hideRe
                 onClick={() => { addBV.mutate({ comBv: corrOn, data: corrData }); setCorrData(""); }}>
                 + evento na data
               </button>
-            </div>
+            </div>}
           </>
         )}
 
```

- [ ] **`frontend/src/components/GestaoView.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/GestaoView.tsx
+++ b/egps_analysis/app/frontend/src/components/GestaoView.tsx
@@ -5,6 +5,7 @@ import { GestaoMigracao } from "./GestaoMigracao";
 import type { Analista, EgpNovoRow, ResponsavelBv } from "../types";
 import { PAPEIS } from "../organograma";
 import { useSubareas } from "../useSubareas";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 const isAtivo = (v: boolean | string) => v === true || v === "true";
 
@@ -19,7 +20,7 @@ const isAtivo = (v: boolean | string) => v === true || v === "true";
  *
  * Adota valor novo do servidor apenas quando não há edição pendente aqui, para um refetch
  * disparado pela edição de OUTRA linha não apagar o que está sendo digitado nesta. */
-function CelulaSubarea({ valor, onSalvar }: { valor: string; onSalvar: (v: string) => void }) {
+function CelulaSubarea({ valor, onSalvar, disabled }: { valor: string; onSalvar: (v: string) => void; disabled?: boolean }) {
   const [texto, setTexto] = useState(valor);
   const [visto, setVisto] = useState(valor);
   if (valor !== visto) {
@@ -27,7 +28,7 @@ function CelulaSubarea({ valor, onSalvar }: { valor: string; onSalvar: (v: strin
     if (texto === visto) setTexto(valor);   // só adota se o usuário não mexeu
   }
   return (
-    <input value={texto} list="subareas-bv" placeholder="—"
+    <input value={texto} list="subareas-bv" placeholder="—" disabled={disabled}
       title="Área interna do BV desta pessoa"
       onChange={(e) => setTexto(e.target.value)}
       onBlur={() => { const v = texto.trim(); if (v !== valor) onSalvar(v); }} />
@@ -38,6 +39,7 @@ function CelulaSubarea({ valor, onSalvar }: { valor: string; onSalvar: (v: strin
 // bv_users — o App já esconde a aba de quem não é do grupo; o backend reforça (403) nas escritas.
 export function GestaoView() {
   const qc = useQueryClient();
+  const pode = usePodeEscrever();
   // inclui inativos: gestores precisam ver/reativar quem foi desativado (dropdowns só veem ativos)
   const q = useQuery({ queryKey: ["analistas", "all"], queryFn: () => api.analistas(true) });
   const [email, setEmail] = useState("");
@@ -153,17 +155,19 @@ export function GestaoView() {
         Declarar <b>não mexe no total congelado</b>; só soma no contador <b>(+N extra)</b> ao lado dele.
       </p>
 
-      <div className="rsm-card">
-        <div className="gestao-add">
-          <input type="text" list="corpus-egps-novos" placeholder="projeto do corpus (Área__Nome)"
-            value={novoProj} onChange={(e) => setNovoProj(e.target.value)}
-            onKeyDown={(e) => { if (e.key === "Enter") addNovo(); }} />
-          <datalist id="corpus-egps-novos">
-            {projetosCorpus.map((p) => <option key={p} value={p} />)}
-          </datalist>
-          <button className="theme-btn" onClick={addNovo} disabled={patchNovo.isPending}>+ Declarar</button>
+      {pode && (
+        <div className="rsm-card">
+          <div className="gestao-add">
+            <input type="text" list="corpus-egps-novos" placeholder="projeto do corpus (Área__Nome)"
+              value={novoProj} onChange={(e) => setNovoProj(e.target.value)}
+              onKeyDown={(e) => { if (e.key === "Enter") addNovo(); }} />
+            <datalist id="corpus-egps-novos">
+              {projetosCorpus.map((p) => <option key={p} value={p} />)}
+            </datalist>
+            <button className="theme-btn" onClick={addNovo} disabled={patchNovo.isPending}>+ Declarar</button>
+          </div>
         </div>
-      </div>
+      )}
 
       {qNovos.error && <div className="error">{String(qNovos.error)}</div>}
       <div className="rsm-card">
@@ -189,10 +193,12 @@ export function GestaoView() {
                       : <span>declarado novo</span>}
                 </td>
                 <td>
-                  <button className="theme-btn" disabled={patchNovo.isPending}
-                    onClick={() => patchNovo.mutate({ projeto: n.projeto, acao: "remover" })}>
-                    Remover
-                  </button>
+                  {pode && (
+                    <button className="theme-btn" disabled={patchNovo.isPending}
+                      onClick={() => patchNovo.mutate({ projeto: n.projeto, acao: "remover" })}>
+                      Remover
+                    </button>
+                  )}
                 </td>
               </tr>
             ))}
@@ -211,18 +217,20 @@ export function GestaoView() {
         aparece como <b>Sem sub-área</b> nas demais abas.
       </p>
 
-      <div className="rsm-card">
-        <div className="gestao-add">
-          <input type="text" placeholder="nome (como está no EGP)" value={bvNome}
-            onChange={(e) => setBvNome(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") addBv(); }} />
-          <input type="text" list="subareas-bv" placeholder="sub-área" value={bvSub}
-            onChange={(e) => setBvSub(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") addBv(); }} />
-          <datalist id="subareas-bv">
-            {subareasCadastradas.map((s) => <option key={s} value={s} />)}
-          </datalist>
-          <button className="theme-btn" onClick={addBv} disabled={upsertBv.isPending}>+ Adicionar</button>
+      {pode && (
+        <div className="rsm-card">
+          <div className="gestao-add">
+            <input type="text" placeholder="nome (como está no EGP)" value={bvNome}
+              onChange={(e) => setBvNome(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") addBv(); }} />
+            <input type="text" list="subareas-bv" placeholder="sub-área" value={bvSub}
+              onChange={(e) => setBvSub(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") addBv(); }} />
+            <datalist id="subareas-bv">
+              {subareasCadastradas.map((s) => <option key={s} value={s} />)}
+            </datalist>
+            <button className="theme-btn" onClick={addBv} disabled={upsertBv.isPending}>+ Adicionar</button>
+          </div>
         </div>
-      </div>
+      )}
 
       {qBv.error && <div className="error">{String(qBv.error)}</div>}
       <div className="rsm-card">
@@ -235,11 +243,11 @@ export function GestaoView() {
               <tr key={b.nome_key} className={isAtivo(b.ativo) ? undefined : "zero"}>
                 <td>{b.nome}</td>
                 <td>
-                  <CelulaSubarea valor={b.subarea ?? ""}
+                  <CelulaSubarea valor={b.subarea ?? ""} disabled={!pode}
                     onSalvar={(v) => upsertBv.mutate({ nome: b.nome, subarea: v })} />
                 </td>
                 <td>
-                  <input type="checkbox" checked={isAtivo(b.ativo)}
+                  <input type="checkbox" checked={isAtivo(b.ativo)} disabled={!pode}
                     title={isAtivo(b.ativo) ? "Ativo — desmarque para desativar" : "Inativo — marque para reativar"}
                     onChange={(e) => upsertBv.mutate({ nome: b.nome, ativo: e.target.checked })} />
                 </td>
@@ -258,28 +266,30 @@ export function GestaoView() {
         Aba restrita ao grupo <b>bv_users</b>.
       </p>
 
-      <div className="rsm-card">
-        <div className="gestao-add">
-          <input type="email" placeholder="email@indicium.tech" value={email}
-            onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
-          <input type="text" placeholder="nome (opcional)" value={nome}
-            onChange={(e) => setNome(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
-          <select value={papel} onChange={(e) => setPapel(e.target.value)} title="Cargo (define a coluna no organograma da Home)">
-            <option value="">papel (organograma)…</option>
-            {PAPEIS.map((p) => <option key={p} value={p}>{p}</option>)}
-          </select>
-          <label className="chk" title="Exibir esta pessoa no organograma da aba Home">
-            <input type="checkbox" checked={organograma} onChange={(e) => setOrganograma(e.target.checked)} />
-            organograma
-          </label>
-          <button className="theme-btn" onClick={add} disabled={upsert.isPending}>+ Adicionar</button>
-          <button className="ghost" onClick={() => sync.mutate()} disabled={sync.isPending}
-            title="Importa membros do grupo bv_users (best-effort; se indisponível, cadastre manual)">
-            {sync.isPending ? "Sincronizando…" : "⟳ Sincronizar do grupo"}
-          </button>
+      {pode && (
+        <div className="rsm-card">
+          <div className="gestao-add">
+            <input type="email" placeholder="email@indicium.tech" value={email}
+              onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
+            <input type="text" placeholder="nome (opcional)" value={nome}
+              onChange={(e) => setNome(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
+            <select value={papel} onChange={(e) => setPapel(e.target.value)} title="Cargo (define a coluna no organograma da Home)">
+              <option value="">papel (organograma)…</option>
+              {PAPEIS.map((p) => <option key={p} value={p}>{p}</option>)}
+            </select>
+            <label className="chk" title="Exibir esta pessoa no organograma da aba Home">
+              <input type="checkbox" checked={organograma} onChange={(e) => setOrganograma(e.target.checked)} />
+              organograma
+            </label>
+            <button className="theme-btn" onClick={add} disabled={upsert.isPending}>+ Adicionar</button>
+            <button className="ghost" onClick={() => sync.mutate()} disabled={sync.isPending}
+              title="Importa membros do grupo bv_users (best-effort; se indisponível, cadastre manual)">
+              {sync.isPending ? "Sincronizando…" : "⟳ Sincronizar do grupo"}
+            </button>
+          </div>
+          {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
         </div>
-        {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
-      </div>
+      )}
 
       {q.error && <div className="error">{String(q.error)}</div>}
       <div className="rsm-card">
@@ -291,24 +301,24 @@ export function GestaoView() {
             {rows.map((a) => (
               <tr key={a.email} className={isAtivo(a.ativo) ? undefined : "zero"}>
                 <td>
-                  <input defaultValue={a.nome ?? ""} placeholder="—"
+                  <input defaultValue={a.nome ?? ""} placeholder="—" disabled={!pode}
                     onBlur={(e) => { const v = e.target.value.trim(); if (v !== (a.nome ?? "")) upsert.mutate({ email: a.email, nome: v }); }} />
                 </td>
                 <td>{a.email}</td>
                 <td>
-                  <select value={a.papel ?? ""} title="Cargo (define a coluna no organograma)"
+                  <select value={a.papel ?? ""} title="Cargo (define a coluna no organograma)" disabled={!pode}
                     onChange={(e) => upsert.mutate({ email: a.email, papel: e.target.value })}>
                     <option value="">—</option>
                     {PAPEIS.map((p) => <option key={p} value={p}>{p}</option>)}
                   </select>
                 </td>
                 <td>
-                  <input type="checkbox" checked={!!a.organograma}
+                  <input type="checkbox" checked={!!a.organograma} disabled={!pode}
                     title="Exibir no organograma da aba Home"
                     onChange={(e) => upsert.mutate({ email: a.email, organograma: e.target.checked })} />
                 </td>
                 <td>
-                  <input type="checkbox" checked={isAtivo(a.ativo)}
+                  <input type="checkbox" checked={isAtivo(a.ativo)} disabled={!pode}
                     title={isAtivo(a.ativo) ? "Ativo — desmarque para desativar" : "Inativo — marque para reativar"}
                     onChange={(e) => upsert.mutate({ email: a.email, ativo: e.target.checked })} />
                 </td>
```

- [ ] **`frontend/src/components/IndiciumView.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/IndiciumView.tsx
+++ b/egps_analysis/app/frontend/src/components/IndiciumView.tsx
@@ -6,6 +6,7 @@ import { useTableSort } from "../useTableSort";
 import { csvDownload, csvFromColumns, csvBool, csvDate, type CsvColumn } from "../csv";
 import { mesTag, useMesPlan } from "../mesPlan";
 import { pathFor, spaLinkClick } from "../routes";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 // exibe o nome curto (sem o prefixo `area__`), igual à aba EGPs (shortName). O egp_dor1/projeto
 // guardado continua com o prefixo canônico — é ele que liga a entrada ao nó real (Recebido/cross-nav).
@@ -31,6 +32,7 @@ const accessor = (r: IndiciumRow, k: SortKey): string | number => {
 
 export function IndiciumView({ onOpenEgp }: { onOpenEgp: (projeto: string) => void }) {
   const qc = useQueryClient();
+  const pode = usePodeEscrever();
   const { mesOf } = useMesPlan();
   const q1 = useQuery({ queryKey: ["indicium"], queryFn: api.indicium });
   const nodesQ = useQuery({ queryKey: ["nodes-all"], queryFn: () => api.lineageSearch("", "", "", 5000) });
@@ -176,12 +178,16 @@ export function IndiciumView({ onOpenEgp }: { onOpenEgp: (projeto: string) => vo
   return (
     <div className="readiness">
       <div className="filters">
-        <input list="esc-egps" placeholder="adicionar EGP (nome)…" value={newEgp}
-          onChange={(e) => { setNewEgp(e.target.value); if (dupErr) setDupErr(null); }} onKeyDown={(e) => e.key === "Enter" && doAdd()} style={{ minWidth: 260 }} />
-        <datalist id="esc-egps">{sugg.map((p) => <option key={p} value={p} />)}</datalist>
-        <input placeholder="área (auto se mapeado)" value={newArea} onChange={(e) => setNewArea(e.target.value)} style={{ minWidth: 130 }} />
-        <button className="btn-add" onClick={doAdd} disabled={!newEgp.trim() || addMut.isPending}>+ Adicionar</button>
-        <span className="sep" />
+        {pode && (
+          <>
+            <input list="esc-egps" placeholder="adicionar EGP (nome)…" value={newEgp}
+              onChange={(e) => { setNewEgp(e.target.value); if (dupErr) setDupErr(null); }} onKeyDown={(e) => e.key === "Enter" && doAdd()} style={{ minWidth: 260 }} />
+            <datalist id="esc-egps">{sugg.map((p) => <option key={p} value={p} />)}</datalist>
+            <input placeholder="área (auto se mapeado)" value={newArea} onChange={(e) => setNewArea(e.target.value)} style={{ minWidth: 130 }} />
+            <button className="btn-add" onClick={doAdd} disabled={!newEgp.trim() || addMut.isPending}>+ Adicionar</button>
+            <span className="sep" />
+          </>
+        )}
         <select value={area} onChange={(e) => setArea(e.target.value)}>
           <option value="">todas as áreas</option>
           {areasList.map((a) => <option key={a} value={a}>{a}</option>)}
@@ -242,11 +248,11 @@ export function IndiciumView({ onOpenEgp }: { onOpenEgp: (projeto: string) => vo
                 <div><span className={`pill ${rec ? "ok" : "todo"}`}>{rec ? "Recebido" : "Não recebido"}</span></div>
                 <div className={Number(r.ciclo_id) > 0 ? "cyc-txt" : ""}>{rec ? mesTag(mesOf.get(r.projeto)) + (Number(r.ciclo_id) > 0 ? " ⟳" : "") : "—"}</div>
                 <div>
-                  {ativo
+                  {pode && (ativo
                     ? <button className="row-x" title="desativar do escopo (fica guardado p/ reativar)"
                         onClick={(e) => { e.stopPropagation(); if (confirm(`Desativar "${shortName(r.egp_dor1)}" do escopo? Fica guardado — dá pra reativar depois.`)) delMut.mutate(r.id); }}>✕</button>
                     : <button className="row-x" title="reativar no escopo"
-                        onClick={(e) => { e.stopPropagation(); reactMut.mutate(r.id); }}>↺</button>}
+                        onClick={(e) => { e.stopPropagation(); reactMut.mutate(r.id); }}>↺</button>)}
                 </div>
               </div>
             );
```

- [ ] **`frontend/src/components/InputDetailPanel.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/InputDetailPanel.tsx
+++ b/egps_analysis/app/frontend/src/components/InputDetailPanel.tsx
@@ -9,6 +9,7 @@ import { GestaoStatusHistory } from "./GestaoStatusHistory";
 import { mesTag, useMesPlan } from "../mesPlan";
 import { PreworkingChecklist } from "./PreworkingChecklist";
 import { pathFor, spaLinkClick } from "../routes";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
 const isIndi = (v: string | boolean | null) => v === true || v === "true";
@@ -173,7 +174,8 @@ export function InputDetailPanel({ row, onOpenEgp, onPatch, analistas }: Props)
   const pendentes = safras.filter((sf) => !sf.resolvido).length;
   const periodo = usage.data?.periodo;
   const isGestao = !!cfgQ.data?.is_gestao;
-  const hist = (audit.data?.rows ?? []).filter((h) => h.campo !== "create");
+  const pode = usePodeEscrever();
+  const hist =(audit.data?.rows ?? []).filter((h) => h.campo !== "create");
   const brokenCount = egps.filter((e) => e.link_broken).length;
   const activeCount = egps.length - brokenCount;
   // ordenados por recorte (escopo → dep → ex → fora) e, dentro dele, quebrados por último.
@@ -307,7 +309,7 @@ export function InputDetailPanel({ row, onOpenEgp, onPatch, analistas }: Props)
                 Ingerida desde
               </span>
               <span>
-                <IngeridaEditor atual={periodo.ingerida?.desde ?? ""} disabled={ingMut.isPending}
+                <IngeridaEditor atual={periodo.ingerida?.desde ?? ""} disabled={ingMut.isPending || !pode}
                   onSave={(v) => ingMut.mutate({ desde: v })} />
                 {periodo.ingerida?.ingerida_em && (
                   <span className="muted" style={{ marginLeft: 6 }}>
@@ -348,7 +350,7 @@ export function InputDetailPanel({ row, onOpenEgp, onPatch, analistas }: Props)
                   {p.projeto === periodo.maximo_projeto ? "▲ " : ""}{shortName(p.projeto)}
                 </span>
                 <span className="de-tags">
-                  {isGestao ? (
+                  {isGestao && pode ? (
                     <PeriodoEditor par={p} disabled={periodoMut.isPending}
                       onSave={(tipo, valor) => periodoMut.mutate({ projeto: p.projeto, tipo, valor })} />
                   ) : (
```

- [ ] **`frontend/src/components/InputsTable.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/InputsTable.tsx
+++ b/egps_analysis/app/frontend/src/components/InputsTable.tsx
@@ -8,6 +8,7 @@ import { InputDetailPanel } from "./InputDetailPanel";
 import { confirmStatusTerminal } from "../pipeline";
 import { DetailModal } from "./DetailModal";
 import { pathFor, spaLinkClick } from "../routes";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 export type InputSortKey =
   | "artifact" | "categoria" | "origem" | "areas" | "source_types" | "qtd_projetos"
@@ -55,6 +56,7 @@ function isOrfao(r: InputRow): boolean {
 
 export function InputsTable({ rows, loading, onPatch, onSort, indicator, onOpenEgp, analistas, blockStats, gestaoById, preworkingById, onBodyScroll, onClearFilters, abrir, onAbriu, onOpenChange }: Props) {
   const parentRef = useRef<HTMLDivElement>(null);
+  const pode = usePodeEscrever();
   const analistaEmails = new Set(analistas.map((a) => a.email));
   // Detalhe do input em MODAL centrado (um por vez) — substituiu o expand inline
   // (.rd-expand-detail): em notebook o inline virava scroll aninhado (pedido 2026-08-28).
@@ -232,7 +234,7 @@ export function InputsTable({ rows, loading, onPatch, onSort, indicator, onOpenE
                   <div className="c-etapa">
                     <select
                       value={effEtapa(r.etapa, r.modernizada_auto)}
-                      disabled={!!travaDerivada(r)} title={travaDerivada(r)}
+                      disabled={!pode || !!travaDerivada(r)} title={travaDerivada(r)}
                       onChange={(e) => { const v = e.target.value;
                         if (!confirmEscritaFamilia(r, "etapa")) return;
                         onPatch(r.chave_canonica, { etapa: v }); }}
@@ -249,7 +251,7 @@ export function InputsTable({ rows, loading, onPatch, onSort, indicator, onOpenE
                         <select
                           value={effSt}
                           style={{ background: SEG[effSt]?.bg, color: SEG[effSt]?.fg }}
-                          disabled={!!travaDerivada(r)} title={travaDerivada(r)}
+                          disabled={!pode || !!travaDerivada(r)} title={travaDerivada(r)}
                           onChange={(e) => { const v = e.target.value;
                             if (!confirmStatusTerminal(v, r.artifact)) return;
                             if (!confirmEscritaFamilia(r, `status "${v}"`)) return;
@@ -264,7 +266,7 @@ export function InputsTable({ rows, loading, onPatch, onSort, indicator, onOpenE
                   </div>
                   <div className="c-resp">
                     <select
-                      value={r.responsavel ?? ""}
+                      value={r.responsavel ?? ""} disabled={!pode}
                       onChange={(e) => onPatch(r.chave_canonica, { responsavel: e.target.value })}
                       title="Responsável pela ingestão deste input"
                     >
@@ -280,7 +282,7 @@ export function InputsTable({ rows, loading, onPatch, onSort, indicator, onOpenE
                   <div className="c-obs">
                     <input
                       defaultValue={r.observacao ?? ""}
-                      placeholder="—"
+                      placeholder="—" disabled={!pode}
                       onBlur={(e) => {
                         const v = e.target.value.trim();
                         if (v !== (r.observacao ?? "")) onPatch(r.chave_canonica, { observacao: v });
@@ -346,7 +348,7 @@ export function InputsTable({ rows, loading, onPatch, onSort, indicator, onOpenE
       {openRow && (
         <DetailModal title={openRow.nome_exibicao ?? openRow.artifact}
           onClose={() => { setOpenChave(null); onOpenChange?.(null); }}>
-          <InputDetailPanel row={openRow} onOpenEgp={onOpenEgp} onPatch={onPatch} analistas={analistas} />
+          <InputDetailPanel row={openRow} onOpenEgp={onOpenEgp} onPatch={pode ? onPatch : undefined} analistas={analistas} />
         </DetailModal>
       )}
     </div>
```

- [ ] **`frontend/src/components/JiraIdInput.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/JiraIdInput.tsx
+++ b/egps_analysis/app/frontend/src/components/JiraIdInput.tsx
@@ -1,4 +1,5 @@
 import { useEffect, useRef, useState } from "react";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 // Regex do Jira ID — espelhe se mudar em backend/main.py:JIRA_ID_RE.
 // ^[A-Z][A-Z0-9]+-\d+$ cobre PROJ-123, ABC1-42, X1Y2-9.
@@ -15,6 +16,10 @@ export function JiraIdInput({ value, onSave, className }:
   const inputRef = useRef<HTMLInputElement>(null);
   useEffect(() => { setDraft(value ?? ""); }, [value]);
   useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);
+  const pode = usePodeEscrever();
+
+  // Sem escrita: só o valor, sem ✎ nem input.
+  if (!pode) return <span className="jira-value">{value ?? "—"}</span>;
 
   // Trava: value definido & não editando → só leitura + botão ✎.
   if (value && !editing) {
```

- [ ] **`frontend/src/components/OutputsDrawer.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/OutputsDrawer.tsx
+++ b/egps_analysis/app/frontend/src/components/OutputsDrawer.tsx
@@ -3,6 +3,7 @@ import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
 import { api } from "../api";
 import type { OutputRow } from "../types";
 import { pathFor, spaLinkClick } from "../routes";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
 const isIndi = (v: string | boolean | null | undefined) => v === true || v === "true";
@@ -50,6 +51,7 @@ export function OutputsDrawer({ row, onClose, onOpenEgp }: Props) {
     onSettled: invalidate,
   });
   const busy = setMut.isPending || clearMut.isPending;
+  const pode = usePodeEscrever();
 
   return (
     <>
@@ -83,7 +85,7 @@ export function OutputsDrawer({ row, onClose, onOpenEgp }: Props) {
         {ambiguo && (
           <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
             Selecione o produtor <b>correto</b> — as dependências dos demais são podadas do grafo (na hora).
-            {escolhido && (
+            {escolhido && pode && (
               <button className="linklike" style={{ marginLeft: 8 }} disabled={busy}
                 onClick={() => clearMut.mutate()}>limpar escolha</button>
             )}
@@ -97,7 +99,7 @@ export function OutputsDrawer({ row, onClose, onOpenEgp }: Props) {
             const pruned = ambiguo && !!escolhido && !chosen;
             return (
               <div key={e.projeto} style={{ display: "flex", alignItems: "center", gap: 6, opacity: pruned ? 0.45 : 1 }}>
-                {ambiguo && !e.apenas_contribui && (
+                {ambiguo && !e.apenas_contribui && pode && (
                   <input type="radio" name={`prod-${row.chave_canonica}`} checked={chosen}
                     disabled={busy} onChange={() => setMut.mutate(e.projeto)}
                     title="marcar como produtor correto" style={{ flex: "0 0 auto" }} />
```

- [ ] **`frontend/src/components/PreworkingChecklist.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/PreworkingChecklist.tsx
+++ b/egps_analysis/app/frontend/src/components/PreworkingChecklist.tsx
@@ -5,6 +5,7 @@ import { fmtTsBR } from "../diasUteis";
 import type { PreworkingRow } from "../types";
 import { PREWORKING_FREQUENCIA, PREWORKING_TIPO_CARGA, PREWORKING_POS_PROC, PREWORKING_DADOS_SENSIVEIS } from "../pipeline";
 import { preworkingPercentual, preworkingDuracaoDias } from "../inputs";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 interface Props {
   chave: string;
@@ -20,7 +21,9 @@ interface Props {
 // Inputs) p/ ser reusado também no GestaoStatusPanel (side panel do Kanban de Inputs, pedido
 // 2026-08): mesmo componente, 2 pontos de entrada, queryKey ["preworking"] compartilhada
 // (cache dedupa fetch entre os dois).
-export function PreworkingChecklist({ chave, readOnly, onAutoAvancado }: Props) {
+export function PreworkingChecklist({ chave, readOnly: readOnlyProp, onAutoAvancado }: Props) {
+  const pode = usePodeEscrever();
+  const readOnly = readOnlyProp || !pode;
   const qc = useQueryClient();
   const pwkKey = ["preworking"] as const;
   const pwkQ = useQuery({ queryKey: pwkKey, queryFn: () => api.preworkingRows() });
```

- [ ] **`frontend/src/components/ReadinessView.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/ReadinessView.tsx
+++ b/egps_analysis/app/frontend/src/components/ReadinessView.tsx
@@ -12,6 +12,7 @@ import { DetailModal } from "./DetailModal";
 import { STATUS_PROJETO, opcoesStatusEgp, SEG, STATUS_HELP, PIPELINE_PROJETO, PHANTOM_ETAPAS_MIGRACAO,
   confirmStatusTerminal, contaNoTotalEgp, TIPO_VINCULO_LABEL, TIPO_VINCULO_HELP } from "../pipeline";
 import { JiraIdInput } from "./JiraIdInput";
+import { usePodeEscrever } from "../usePodeEscrever";
 import { MultiSelect } from "./MultiSelect";
 import { RangeFilter } from "./RangeFilter";
 import {
@@ -104,6 +105,7 @@ const extraTitle = (r: ReadinessRow) =>
 
 export function ReadinessView({ cfg, egpToOpen, onEgpOpened, onOpenInput }: Props) {
   const qc = useQueryClient();
+  const pode = usePodeEscrever();
   const pipeMut = useMutation({
     mutationFn: (v: { projeto: string; etapa?: string; status?: string; responsavel?: string; responsavel_bv?: string | null; jira_id?: string | null; preworking?: boolean; preworking_data?: string | null }) => api.egpPipeline(v),
     onMutate: async (v) => {
@@ -870,7 +872,7 @@ export function ReadinessView({ cfg, egpToOpen, onEgpOpened, onOpenInput }: Prop
                           da ingestão que não cobre o que ele lê. Reabre a aresta; o EGP volta
                           a ser dependência viva. Só onde faz sentido oferecer: ex-dep
                           "resolvida por ingestão", ou uma já mantida (para desfazer). */}
-                      {(r.ex_motivo === "resolvida por ingestão" || r.dep_mantida) && (
+                      {(r.ex_motivo === "resolvida por ingestão" || r.dep_mantida) && pode && (
                         <button className={`dep-keep-btn${r.dep_mantida ? " on" : ""}`}
                           disabled={depMut.isPending}
                           title={r.dep_mantida
@@ -921,7 +923,7 @@ export function ReadinessView({ cfg, egpToOpen, onEgpOpened, onOpenInput }: Prop
                     ) : ""}
                   </div>
                   <div className="rd-etapa" onClick={(e) => e.stopPropagation()}>
-                    <select value={r.etapa} disabled={r.etapa_editavel === false}
+                    <select value={r.etapa} disabled={r.etapa_editavel === false || !pode}
                       title={r.etapa_editavel === false
                         ? `Etapa espelhada de "${r.sucessor}" — edite no EGP sucessor`
                         : undefined}
@@ -934,7 +936,7 @@ export function ReadinessView({ cfg, egpToOpen, onEgpOpened, onOpenInput }: Prop
                     </select>
                   </div>
                   <div className="rd-status" onClick={(e) => e.stopPropagation()}>
-                    <select value={r.status} title={STATUS_HELP}
+                    <select value={r.status} title={STATUS_HELP} disabled={!pode}
                       style={{ background: SEG[r.status]?.bg, color: SEG[r.status]?.fg }}
                       onChange={(e) => { const v = e.target.value;
                         if (!confirmStatusTerminal(v, shortName(r.projeto))) return;
@@ -953,7 +955,7 @@ export function ReadinessView({ cfg, egpToOpen, onEgpOpened, onOpenInput }: Prop
                       ? "Confirme o vínculo com uma versão atualizada no detalhe do EGP (seção \"Versão atualizada\") antes de classificar o tipo"
                       : TIPO_VINCULO_HELP}>
                     {r.egp_atualizado_key ? (
-                      <select value={r.atualizado_link_tipo_vinculo ?? ""}
+                      <select value={r.atualizado_link_tipo_vinculo ?? ""} disabled={!pode}
                         onChange={(e) => {
                           const projeto = r.projeto;
                           // destaca + rola até a linha: a tabela reordena no refetch e sem
@@ -973,7 +975,7 @@ export function ReadinessView({ cfg, egpToOpen, onEgpOpened, onOpenInput }: Prop
                     ) : <span className="de-meta">—</span>}
                   </div>
                   <div className="rd-resp" onClick={(e) => e.stopPropagation()}>
-                    <select value={r.responsavel ?? ""} title="Responsável pela migração deste EGP"
+                    <select value={r.responsavel ?? ""} title="Responsável pela migração deste EGP" disabled={!pode}
                       onChange={(e) => pipeMut.mutate({ projeto: r.projeto, responsavel: e.target.value })}>
                       <option value="">—</option>
                       {r.responsavel && !analistaEmails.has(r.responsavel) && (
```

- [ ] **`frontend/src/components/RespBvInput.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/RespBvInput.tsx
+++ b/egps_analysis/app/frontend/src/components/RespBvInput.tsx
@@ -1,5 +1,6 @@
 import { useEffect, useId, useState } from "react";
 import { useSubareas } from "../useSubareas";
+import { usePodeEscrever } from "../usePodeEscrever";
 
 // Input de texto com commit no blur/Enter — responsável do lado BV (sas_egp_pipeline).
 // Extraído de ReadinessView p/ ser compartilhado com o modal de detalhe (EgpDetailPanel).
@@ -10,6 +11,7 @@ export function RespBvInput({ value, onSave }: { value: string | null; onSave: (
   const [draft, setDraft] = useState(value ?? "");
   const { nomes } = useSubareas();
   const listId = useId();
+  const pode = usePodeEscrever();
   useEffect(() => { setDraft(value ?? ""); }, [value]);
   const commit = (v: string) => {
     const t = v.trim();
@@ -18,7 +20,7 @@ export function RespBvInput({ value, onSave }: { value: string | null; onSave: (
   };
   return (
     <>
-      <input type="text" placeholder="—" value={draft} list={listId}
+      <input type="text" placeholder="—" value={draft} list={listId} disabled={!pode}
         title="Responsável do lado BV por este EGP (sugestões vêm do cadastro da Gestão)"
         onChange={(e) => setDraft(e.target.value)}
         onBlur={(e) => commit(e.target.value)}
```

- [ ] **`frontend/src/components/WavesView.tsx`**

```diff
--- a/egps_analysis/app/frontend/src/components/WavesView.tsx
+++ b/egps_analysis/app/frontend/src/components/WavesView.tsx
@@ -5,6 +5,7 @@ import { SEG } from "../pipeline";
 import { csvBool, csvDate, csvDownload, csvFromColumns, egpShort } from "../csv";
 import { pathFor, spaLinkClick } from "../routes";
 import { fmtTsBR } from "../diasUteis";
+import { usePodeEscrever } from "../usePodeEscrever";
 import type { AppConfig, PrioMes, PrioEgp, PriorizacaoPayload } from "../types";
 
 // Aba "Priorização": plano de ingestão por CAPACIDADE, recorte FIXO (Indicium + dependências,
@@ -43,6 +44,7 @@ export function WavesView({ cfg, onOpenEgp }: Props) {
   const [open, setOpen] = useState<Set<number>>(new Set([1]));
   const isGestao = !!cfg?.is_gestao;
   const isAdmin = !!cfg?.is_admin;
+  const pode = usePodeEscrever();
   const [preview, setPreview] = useState<PriorizacaoPayload | null>(null);
 
   const q = useQuery({
@@ -157,7 +159,7 @@ export function WavesView({ cfg, onOpenEgp }: Props) {
       <div className="filters">
         <span className="prio-fixed">
           Recorte fixo: <b>Indicium + dependências</b> · todas as áreas ·{" "}
-          {isGestao
+          {isGestao && pode
             ? <CapControl cap={effCap} busy={busy} onSave={setCapLocal} />
             : <b>{cap}</b>}{" "}
           inputs/mês · prazo <b>dez/2026</b>
@@ -176,10 +178,13 @@ export function WavesView({ cfg, onOpenEgp }: Props) {
             📌 fixado em {fmtTsBR(snap.snapshot.saved_at, false)} por {(snap.snapshot.saved_by || "").split("@")[0]}
           </span>
         )}
-        <button className="ghost" onClick={() => recompute.mutate()} disabled={busy}
-          title="Recalcula o plano ao vivo com as edições locais (não salva) para pré-visualizar">
-          {recompute.isPending ? "recalculando…" : "↻ Recalcular"}
-        </button>
+        {/* POST /preview não grava, mas o modo leitura recusa todo POST */}
+        {pode && (
+          <button className="ghost" onClick={() => recompute.mutate()} disabled={busy}
+            title="Recalcula o plano ao vivo com as edições locais (não salva) para pré-visualizar">
+            {recompute.isPending ? "recalculando…" : "↻ Recalcular"}
+          </button>
+        )}
         <button
           className="ghost csv-btn"
           onClick={exportCsv}
@@ -196,7 +201,7 @@ export function WavesView({ cfg, onOpenEgp }: Props) {
             ? <span><b>Pré-visualização não salva</b>{movedCount ? ` · ${movedCount} EGP(s) mudariam de mês vs. o snapshot` : " · igual ao snapshot atual"}.</span>
             : <span><b>Alterações não aplicadas</b>{realPins.length ? ` · ${realPins.length} pin(s)` : ""}{capChanged ? " · capacidade" : ""} — clique em <b>Recalcular</b> para pré-visualizar.</span>}
           <button className="ghost" onClick={discard} disabled={busy}>Descartar</button>
-          {isAdmin
+          {isAdmin && pode
             ? <button className="theme-btn" onClick={() => saveSnap.mutate()} disabled={busy}
                 title="Persiste os pins/capacidade e fixa o novo snapshot para todos">
                 {saveSnap.isPending ? "Salvando…" : "Salvar prioridade"}
@@ -301,7 +306,7 @@ export function WavesView({ cfg, onOpenEgp }: Props) {
                       <div className="pe-cell num">{e.fan_out > 0 ? e.fan_out : "—"}</div>
                       <div className="pe-cell" title={e.responsavel ?? ""}>{nomeDe(e.responsavel)}</div>
                       <div className="pe-cell">
-                        {isGestao
+                        {isGestao && pode
                           ? <MoveControl cur={ep} nMeses={nMeses} busy={busy}
                               onMove={(mes) => setPin(e.projeto, mes)} />
                           : (ep != null ? "📌" : "")}
```


- [ ] **Verificar** (a partir de `frontend/`): `npx tsc -b --noEmit` (ou o que o `npm run build` usa), `npm run build` e cada `*.test.mts` com `node --experimental-strip-types`. Esperado: tudo verde.

---

## Parte E — Comparação completa, local (antes da AWS)

É o procedimento que deu 33/33 e 82/82 em 14/10. Ele roda **antes** de qualquer subida, e de novo a cada mudança de SQL nas rotas.

### Task E1: Espelho de prod × Databricks de prod, tabela a tabela

- [ ] Banco local novo e sincronização de prod (o Databricks só é lido):

```bash
env PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_1b .venv/bin/python -m db.migra --cria-banco
```

```bash
env DATABRICKS_CONFIG_PROFILE=bv DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_1b .venv/bin/python -m sync.sincroniza
```

Esperado: `[sync] OK {... 'espelho': {33 tabelas} ...}`.

- [ ] Logo em seguida (o que alguém editar no app entre os dois passos aparece como diferença):

```bash
env DATABRICKS_CONFIG_PROFILE=bv PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_1b .venv/bin/python -m paridade.tabelas --warehouse 5922c26f81f1bbdd
```

Esperado: `[tabelas] 33/33 tabelas iguais`.

### Task E2: App do Databricks × app do Postgres, rota a rota (os dois lendo o dev)

- [ ] Banco local carregado do schema **de dev**, com a mesma sincronização:

```bash
env PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_1b_dev .venv/bin/python -m db.migra --cria-banco
```

```bash
env DATABRICKS_CONFIG_PROFILE=bv DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd ORIGEM_SCHEMA=bv_dev_db.monitoramento_sas_dev PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_1b_dev .venv/bin/python -m sync.sincroniza
```

- [ ] O seu usuário no banco local com o mesmo papel que você tem no Databricks (`admin`, para `is_admin` bater):

```bash
docker exec pg17-monitoramento psql -U postgres -d monitoramento_1b_dev -c "INSERT INTO cadastro.usuario (email, nome, papel) VALUES ('<seu e-mail @indicium.ai>', '<nome>', 'admin') ON CONFLICT (email) DO UPDATE SET papel = 'admin', ativo = true"
```

- [ ] Os dois apps, cada um como tarefa de fundo (o mesmo código, `FAMILIAS_SAFRA=1` como em prod):

```bash
env DATABRICKS_CONFIG_PROFILE=bv DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd PUBLISH_CATALOG=bv_dev_db PUBLISH_SCHEMA=monitoramento_sas_dev FAMILIAS_SAFRA=1 APP_PORT=8010 .venv/bin/python backend/main.py
```

```bash
env DB_BACKEND=postgres IDENTIDADE=dev DEV_USUARIO=<seu e-mail @indicium.ai> SOMENTE_LEITURA=1 PUBLISH_SCHEMA=compat PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_1b_dev FAMILIAS_SAFRA=1 APP_PORT=8011 .venv/bin/python backend/main.py
```

- [ ] Comparação, com as amostras:

```bash
env PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_1b_dev .venv/bin/python -m paridade.compara --antigo http://127.0.0.1:8010 --novo http://127.0.0.1:8011 --amostras --saida /tmp/paridade-1b.json
```

Esperado: `[paridade] 82/82 rotas iguais`. No relatório:
- **`aceitas`:** só `$.scope`, `$.sincronizado_em`, `$.somente_leitura`, `$.table`, `$.warehouse` e `$.papel`;
- **`mesmo_erro`:** só as 6 rotas que exigem parâmetro chamadas sem ele (com parâmetro, elas estão entre as amostras);
- **`fora`:** só `/api/prioridades`.

Se alguma rota diferir, a diferença é de dialeto. Corrija na forma que roda nos dois bancos, com um caso novo em `test_sql_portavel_pg.py`, e rode de novo.

- [ ] Pare os dois apps e apague os bancos locais com dado do BV:

```bash
docker exec pg17-monitoramento psql -U postgres -c "DROP DATABASE monitoramento_1b WITH (FORCE)"
```

```bash
docker exec pg17-monitoramento psql -U postgres -c "DROP DATABASE monitoramento_1b_dev WITH (FORCE)"
```

---

## Parte F — Subida na AWS (depois do apply da F2 do 1a)

Pré-requisitos:
- F1 e F2 do 1a aplicadas;
- o segredo `databricks-sync` criado com o token pessoal (a F5 foi substituída em 15/10, ver a Task F5 do 1a);
- deploy do CI (G2 do 1a) ligado.

### Task F1: Ensaio na training

- [ ] Com o código do 1b, rode o ensaio do 1a (`IPS='["<seu ip>/32"]' DEV_USUARIO=<seu e-mail> bash treino/sobe_treino.sh`). Esperado:
  - **migrações:** `[migra] aplicada 0005_legado_espelho.sql`;
  - **massa sintética:** carregada;
  - **fumaça:** 5/5.
  - **No navegador:** o Resumo aparece sem os erros `compat.sas_lineage_nodes`/`sas_resumo_inputs` de 14/10. Os números são os da massa sintética.

### Task F2: Migração 0005 no dev e na prod (com consentimento)

- [ ] Depois do deploy da imagem do 1b, uma tarefa avulsa por banco, como na H1 do 1a (`python -m db.migra`, sem `--cria-banco`). Esperado: `[migra] aplicada 0005_legado_espelho.sql`.

### Task F3: Sincronização e comparação de tabelas **na AWS** (com consentimento)

- [ ] Dispare a sincronização fora do agendamento (H3 do 1a) e confira no log `[sync] OK` com as 33 tabelas do espelho.
- [ ] Logo depois, a comparação de tabelas, rodando na própria tarefa da sincronização (ela tem a conta de serviço do Databricks e o acesso ao RDS):

```bash
aws ecs run-task --profile indicium --cluster tf-indicium-ecs --launch-type FARGATE --task-definition monitoramento-sas-sync --network-configuration "awsvpcConfiguration={subnets=[<public_1>,<public_2>],securityGroups=[<monitoramento-sas-sync-sg>,<monitoramento-sas-db-client-sg>],assignPublicIp=ENABLED}" --overrides '{"containerOverrides":[{"name":"sync","command":["python","-m","paridade.tabelas"]}]}'
```

Esperado no log: `[tabelas] 33/33 tabelas iguais`. Junto com a Task E2 (mesmo código, comparação rota a rota), isso fecha a paridade da prod. Registre o resultado na spec.

### Task F4: Dev em modo leitura até a Fase 2

Na Fase 1 nenhuma escrita funciona no Postgres: as views de `compat` leem o espelho, e o papel do app só tem `SELECT`. Com `somente_leitura = "0"`, o dev da AWS mostraria controles que respondem 502.
- [ ] Na F2 (`ambientes.dev.somente_leitura`), troque para `"1"` antes do merge, se ela ainda não tiver sido aplicada. Se já tiver, faça uma PR pequena. Volta a `"0"` quando a Fase 2 ligar a escrita.

---

## Parte G — Abrir ao BV

**Depende do login.** O Google segue pendente da PR `gcloud/monitoramento-sas-auth`; a alternativa é o Cognito, que foi testado na bancada. Sem login, o BV não entra.

### Task G1: Cadastro do BV como leitor (com consentimento)

- [ ] A lista de e-mails do BV vem do usuário (quem hoje entra no app do Databricks pelo grupo do BV). No banco de prod, como na H2 do 1a:

```sql
SELECT set_config('app.usuario', '<seu e-mail>', false);
INSERT INTO cadastro.usuario (email, nome, papel) VALUES
  ('<e-mail @bv.com.br>', '<nome>', 'leitor')
ON CONFLICT (email) DO UPDATE SET papel = 'leitor', ativo = true;
```

Repita a linha `VALUES` para cada pessoa. E-mail em minúsculas, que é a regra do `CHECK`.

### Task G2: Critério do JIT

O JIT volta (spec, Fase 1, item 7) quando, **todos** conferidos e registrados na spec:
- [ ] o login de uma conta `@bv.com.br` funcionou no endereço novo;
- [ ] a comparação fechou: Task E2 com 82/82 e Task F3 com 33/33;
- [ ] o BV está cadastrado como leitor (G1);
- [ ] pelo menos uma pessoa do BV já entrou no endereço novo.

### Task G3: Comunicação

- [ ] Avise o BV do endereço novo e de que lá é só leitura; quem edita continua usando o app do Databricks até a Fase 2. Texto e canal a cargo do usuário (nada é enviado por este plano).

---

## Parte H — Fechamento do 1b

- [ ] Registre na spec: a decisão do espelho, o resultado das comparações (E1, E2, F3) e as diferenças aceitas.
- [ ] Suíte inteira verde com `PG_TEST_OBRIGATORIO=1` (backend, db, sync, paridade, treino) e o front (`tsc`, build, `*.test.mts`).
- [ ] Escreva o **plano 2** a partir da `main` do momento. Insumos:
  - o relatório do agente de schema, com o de-para para o schema novo;
  - o inventário de prod de 14/10 (formatos, caminhos `familia::`, órfãos);
  - a lista de escritas do front (`.mutate(` por componente).

## Saída do 1b

- O app na AWS mostra, rota a rota, o mesmo que o app do Databricks. A prova está registrada: 33/33 tabelas e 82/82 rotas.
- Quem não pode gravar não vê controle de escrita.
- Falta, para o JIT, o login e o cadastro do BV: a Parte G, que depende da decisão sobre o login.
