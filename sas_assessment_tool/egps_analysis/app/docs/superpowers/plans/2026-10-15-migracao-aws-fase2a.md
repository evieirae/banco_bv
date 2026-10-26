# Migração AWS — Fase 2a: escrita no Postgres sobre o espelho — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Toda rota de escrita do app grava no Postgres, no espelho `legado`, pelas views `compat`. O resultado é o mesmo do Databricks, e o comportamento do app de prod de hoje não muda.

**Architecture:** Na decisão de 15/10/2026, o espelho virou a fonte. As escritas mudam só de dialeto:
- quem e quando gravam saem de `_ator()` e `AGORA`, no lugar de `current_user()` e `current_timestamp()`;
- a coluna-alvo do `SET` perde o `t.`;
- DDL só roda fora do Postgres.

O Postgres 17 aceita INSERT, UPDATE, DELETE e MERGE nas views simples de `compat` e grava no `legado`. O papel `app_escrita` só grava nas 33 views que o app grava. O MESMO código continua servindo o app do Databricks.

**Tech Stack:** FastAPI, psycopg 3, Postgres 17, Databricks SQL (Spark/Delta), pytest, React + TypeScript.

---

## A decisão (15/10/2026)

O usuário decidiu cinco pontos (spec, Fases, "Decisão de 15/10"; ADR 0005, atualização):
- **(A) O espelho vira a fonte.** Na virada, a sincronização para, e o app e o publish passam a escrever nas mesmas tabelas do `legado`. O de-para com correções vira a Fase 3, se ainda valer a pena.
- **A virada é num momento só.**
- **O publish entra no app** (planos 2b e 2d).
- **O botão "Sincronizar grupo" sai.**
- **Não há data alvo.**

Este plano é o 2a: a escrita. O publish no app é o 2b, a virada é o 2c, e o pipeline inteiro no app é o 2d.

## O que já rodou (15/10/2026, num rascunho a partir da ponta da `feat/aws-migration-phase1b`)

- **Espelho completo.** A sincronização de um clone do dev deu 40 de 40 tabelas iguais célula a célula (cerca de 105 mil linhas), contando as 7 novas.
- **Escritas no Postgres.** São 22 testes contra um Postgres de verdade: um por rota de escrita, com o app em modo Postgres num subprocesso, mais as duas escritas dentro de GET. Os 3 guardas acusam o código de antes do porte (161 linhas de dialeto e 6 DDL soltos) e passam no código portado.
- **Prova contra o Databricks,** num schema descartável clonado do dev, autorizado e apagado no fim:
  - das 26 escritas do roteiro, 25 foram aceitas nos dois lados. A 26ª tinha um `jira_id` fora do formato e foi recusada com o mesmo 400 pelos dois; o roteiro foi corrigido;
  - depois do roteiro, 40 de 40 tabelas iguais, com o horário gravado e o id gerado comparados pela classe do valor.
- **Suíte:** 855 testes em Python, os 13 arquivos de teste do front e o build.
- **Achados no caminho:**
  - O tradutor tirava o `t.` de um `ON` quando um comentário com "UPDATE SET" abria o trecho. Agora ele só conta `SET` dentro de f-string.
  - O `CREATE TABLE` do contador diário de sanitização ficava solto, e o erro dele era engolido. Isso só aparece com a escrita ligada, e virou guarda.
  - As duas escritas dentro de GET que a Fase 1 desligou no Postgres precisam voltar quando a escrita está ligada.
  - O `current_user()` do Databricks devolve `@indicium.ai`. Na prova, o app Postgres roda com esse e-mail, para o autor bater.
  - O audit do snapshot da priorização grava a hora em `valor_novo`, então a máscara do comparador vale para instante em qualquer coluna.

## Escopo deste plano

- **Dentro:**
  - as 7 tabelas que faltavam no espelho;
  - o SQL de todas as rotas de escrita traduzido;
  - o papel `app_escrita`;
  - as escritas dentro de GET, que voltam quando a escrita está ligada;
  - a saída do "Sincronizar grupo";
  - o roteiro fixo de escritas, com o comparador em modo escritas;
  - o dev da AWS virando laboratório de escrita.
- **Fora:**
  - o publish no app (2b);
  - a virada, a saída do Genie e da rotina de consulta, e o desligamento do Databricks (2c);
  - extractor e orchestrator na AWS (2d);
  - o de-para para o schema novo (Fase 3);
  - transação por requisição. Hoje o Databricks também não tem; o publish (2b) é que roda numa transação.

## Regras (não negociáveis)

- **Deploy e escrita em prod ou dev**, no Databricks ou na AWS, só com o consentimento explícito do usuário a cada vez.
- **Nada de commit ou push sem o usuário pedir.** Nunca `Co-Authored-By`. Branch em inglês, commit em português.
- **O app local só lê o Databricks DEV.** A prova do Spark (Parte D) escreve só num schema DESCARTÁVEL, clonado do dev e apagado no fim.
- **Dado do BV nunca entra na conta training.** O banco local carregado do clone é apagado no fim.
- **`curl` não é usado** (política da organização): use `urllib`.
- **Antes de rodar os testes,** ligue o Postgres local: `docker start pg17-monitoramento` (porta 55432).

## Mapa de arquivos (`egps_analysis/app/`)

| Arquivo | O que muda |
|---|---|
| `sync/espelho_tabelas.py` | +7 tabelas (40) |
| `sync/test_espelho.py` | as 7 saem de `FORA_DO_ESPELHO`; teste de privilégios do legado |
| `db/migrations/0006_legado_espelho_completo.sql` | novo: as 7 no `legado` + views `compat` + grants |
| `db/migrations/0007_escrita_app.sql` | novo: papel `app_escrita` (grava nas 33 views do app) e `compat.uuid()` |
| `backend/main.py` | `AGORA`/`_ator()`; SQL de escrita traduzido; DDL só fora do Postgres; escritas em GET com a escrita ligada; rota `sync-grupo` sai |
| `backend/egps_atualizados.py` | recebe `ator`/`agora` do main |
| `backend/test_escritas_pg.py` | novo: cada rota de escrita contra um Postgres de verdade (app num subprocesso) |
| `backend/test_escritas_portadas.py` | novo: guardas (rota sem teste, dialeto do Databricks, DDL sem proteção) |
| `backend/test_ponte_tipo_vinculo.py`, `backend/test_egp_pipeline_patch_parcial.py` | o texto do SQL esperado sem `t.` |
| `frontend/src/components/GestaoView.tsx`, `frontend/src/api.ts`, `README.md` | "Sincronizar grupo" sai |
| `paridade/tabelas.py`, `paridade/test_tabelas.py` | modo `--escritas` (máscara de carimbo e id gerado) |
| `paridade/escritas.py` | novo: roteiro fixo de escritas nos dois apps |
| `docs/superpowers/specs/2026-10-14-migracao-aws-design.md`, `/docs/adr/0005-app-sai-do-databricks.md` | decisão de 15/10 |

## Preparação (uma vez)

- [ ] Crie a branch a partir da 1b (nome em inglês):

```bash
git -C <worktree> switch -c feat/aws-migration-phase2a feat/aws-migration-phase1b
```

- [ ] Postgres local e suíte verde antes de começar (a partir de `egps_analysis/app`):

```bash
docker start pg17-monitoramento
PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres PG_TEST_OBRIGATORIO=1 .venv/bin/python -m pytest -q -p no:cacheprovider backend db sync paridade treino
```

Esperado: tudo passa.

---

## Parte A — Espelho completo

### Task A1: As 7 tabelas que as escritas e o publish usam

As escritas e o publish leem ou gravam 7 tabelas que a 0005 deixou de fora:
- os audits de vínculo mantido, período, ingestão de família e EGPs atualizados;
- `sas_resumo_proj`, que o recálculo do escopo lê;
- `sas_pipeline_metrics`;
- `sas_input_alias_canonico`, que a reaplicação de identidade lê.

Sem elas, esses históricos começariam vazios na AWS depois da virada. Colunas e tipos vêm do `information_schema` de prod (15/10).

**Files:**
- Modify: `sync/espelho_tabelas.py`, `sync/test_espelho.py`
- Create: `db/migrations/0006_legado_espelho_completo.sql`

- [ ] **Step 1: Testes.** As 7 saem de `FORA_DO_ESPELHO` e entram na lista. O teste novo confere os privilégios papel a papel: o padrão do `legado` só dá SELECT, e o INSERT/DELETE da sincronização vem tabela a tabela.

```diff
--- a/egps_analysis/app/sync/test_espelho.py
+++ b/egps_analysis/app/sync/test_espelho.py
@@ -30,12 +30,6 @@ FORA_DO_ESPELHO = {
     "sas_consulta_egp_dia": "idem",
     "sas_consulta_input": "idem",
     "sas_consulta_input_dia": "idem",
-    "sas_pipeline_metrics": "nenhuma rota GET lê; só o publish escreve",
-    "sas_resumo_proj": "só o recompute de escopo (escrita) lê",
-    "sas_egp_dep_mantida_audit": "só escrita",
-    "sas_egp_input_periodo_audit": "só escrita",
-    "sas_familia_ingestao_audit": "só escrita",
-    "sas_egp_atualizados_audit": "só escrita (PATCH da aba aposentada)",
 }
 
 
@@ -174,6 +168,22 @@ def test_so_a_sincronizacao_regrava_o_legado(banco):
             adm.execute(f"DROP ROLE {papel}")
 
 
+@precisa_pg
+def test_toda_tabela_do_legado_tem_os_privilegios_da_sincronizacao(banco):
+    """Confere, papel a papel, os privilégios de que app e sincronização precisam em cada tabela do
+    espelho. O padrão do legado só dá SELECT; INSERT/DELETE vem tabela a tabela, e o esquecido só
+    apareceria na AWS. A mensagem diz qual papel, privilégio e objeto faltou."""
+    import psycopg
+    with psycopg.connect(banco) as c:
+        for t in espelho.TABELAS:
+            for papel, objeto, priv in (("app_leitura", f"compat.{t}", "SELECT"),
+                                        ("app_leitura", f"legado.{t}", "SELECT"),
+                                        ("sincronizador", f"legado.{t}", "SELECT"),
+                                        ("sincronizador", f"legado.{t}", "INSERT"),
+                                        ("sincronizador", f"legado.{t}", "DELETE")):
+                ok = c.execute("SELECT has_table_privilege(%s, %s, %s)", (papel, objeto, priv)).fetchone()[0]
+                assert ok, f"{papel} sem {priv} em {objeto}"
+
+
 @precisa_pg
 def test_funcoes_do_spark_que_faltavam(banco):
     import psycopg
```

```diff
--- a/egps_analysis/app/sync/espelho_tabelas.py
+++ b/egps_analysis/app/sync/espelho_tabelas.py
@@ -1,7 +1,9 @@
 # -*- coding: utf-8 -*-
-"""Colunas e tipos Delta das 33 tabelas espelhadas, na ordem do DESCRIBE de prod (14/10/2026).
+"""Colunas e tipos Delta das 40 tabelas espelhadas, na ordem do DESCRIBE de prod.
 
-Gerado a partir do schema real (`DESCRIBE TABLE` em bv_dev_db.monitoramento_sas) e revisado.
+Gerado a partir do schema real (`DESCRIBE TABLE` em bv_dev_db.monitoramento_sas) e revisado:
+33 em 14/10/2026 (o que as rotas GET leem) e 7 em 15/10/2026 (o que as escritas e o publish
+leem ou gravam e ainda não vinha — Fase 2, o espelho vira a fonte na virada).
 Coluna nova numa tabela espelhada entra AQUI e na migração do schema `legado`, na mesma PR;
 o teste test_espelho.test_legado_bate_com_a_lista confere as duas.
 """
@@ -392,4 +394,70 @@ TABELAS = {
         ("updated_by", "string"),
         ("updated_at", "string"),
     ),
+    # ---- 15/10/2026: escritas e publish (Fase 2) ----
+    "sas_egp_atualizados_audit": (
+        ("id", "string"),
+        ("egp_key", "string"),
+        ("campo", "string"),
+        ("valor_antigo", "string"),
+        ("valor_novo", "string"),
+        ("autor", "string"),
+        ("ts", "timestamp"),
+    ),
+    "sas_egp_dep_mantida_audit": (
+        ("id", "string"),
+        ("projeto", "string"),
+        ("chave_canonica", "string"),
+        ("campo", "string"),
+        ("valor_antigo", "string"),
+        ("valor_novo", "string"),
+        ("ator", "string"),
+        ("ts", "timestamp"),
+    ),
+    "sas_egp_input_periodo_audit": (
+        ("id", "string"),
+        ("projeto", "string"),
+        ("categoria", "string"),
+        ("familia", "string"),
+        ("campo", "string"),
+        ("valor_antigo", "string"),
+        ("valor_novo", "string"),
+        ("ator", "string"),
+        ("ts", "timestamp"),
+    ),
+    "sas_familia_ingestao_audit": (
+        ("id", "string"),
+        ("categoria", "string"),
+        ("familia", "string"),
+        ("campo", "string"),
+        ("valor_antigo", "string"),
+        ("valor_novo", "string"),
+        ("ator", "string"),
+        ("ts", "timestamp"),
+    ),
+    "sas_input_alias_canonico": (
+        ("chave_canonica", "string"),
+        ("chave_canonica_alvo", "string"),
+        ("membro", "string"),
+        ("lib", "string"),
+        ("lib_canonica", "string"),
+        ("path_fisico", "string"),
+        ("n_egps", "int"),
+        ("eh_canonico", "boolean"),
+        ("origem_decisao", "string"),
+        ("motivo", "string"),
+        ("ativo", "boolean"),
+        ("updated_by", "string"),
+        ("updated_at", "timestamp"),
+    ),
+    "sas_pipeline_metrics": (
+        ("captured_at", "timestamp"),
+        ("escopo", "string"),
+        ("metric", "string"),
+        ("valor", "bigint"),
+    ),
+    "sas_resumo_proj": (
+        ("chave_canonica", "string"),
+        ("projeto", "string"),
+    ),
 }
```

- [ ] **Step 2: Rode e veja falhar.**

```bash
PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q -p no:cacheprovider sync/test_espelho.py
```

Esperado: 4 falhas, com `relation "legado.sas_egp_atualizados_audit" does not exist` ou a lista de colunas vazia.

- [ ] **Step 3: A migração 0006,** gerada da própria lista, no molde da 0005:

```sql
-- Espelho completo (Fase 2, 15/10/2026): as 7 tabelas que as escritas e o publish leem ou
-- gravam e que a 0005 deixou de fora. Na virada o espelho vira a FONTE (app e publish passam a
-- escrever nele): sem estas, quatro históricos (vínculo mantido, período, ingestão de família,
-- EGPs atualizados) e as tabelas do publish (resumo por projeto, métricas, alias canônico)
-- começariam vazios na AWS. Mesmo molde da 0005: colunas e tipos do Delta, sem PK/FK/NOT NULL,
-- e a view compat só lê do legado.

CREATE TABLE legado.sas_egp_atualizados_audit (
  id text,
  egp_key text,
  campo text,
  valor_antigo text,
  valor_novo text,
  autor text,
  ts timestamp
);

CREATE TABLE legado.sas_egp_dep_mantida_audit (
  id text,
  projeto text,
  chave_canonica text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts timestamp
);

CREATE TABLE legado.sas_egp_input_periodo_audit (
  id text,
  projeto text,
  categoria text,
  familia text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts timestamp
);

CREATE TABLE legado.sas_familia_ingestao_audit (
  id text,
  categoria text,
  familia text,
  campo text,
  valor_antigo text,
  valor_novo text,
  ator text,
  ts timestamp
);

CREATE TABLE legado.sas_input_alias_canonico (
  chave_canonica text,
  chave_canonica_alvo text,
  membro text,
  lib text,
  lib_canonica text,
  path_fisico text,
  n_egps integer,
  eh_canonico boolean,
  origem_decisao text,
  motivo text,
  ativo boolean,
  updated_by text,
  updated_at timestamp
);

CREATE TABLE legado.sas_pipeline_metrics (
  captured_at timestamp,
  escopo text,
  metric text,
  valor bigint
);

CREATE TABLE legado.sas_resumo_proj (
  chave_canonica text,
  projeto text
);

CREATE VIEW compat.sas_egp_atualizados_audit AS SELECT id, egp_key, campo, valor_antigo, valor_novo, autor, ts FROM legado.sas_egp_atualizados_audit;

CREATE VIEW compat.sas_egp_dep_mantida_audit AS SELECT id, projeto, chave_canonica, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_egp_dep_mantida_audit;

CREATE VIEW compat.sas_egp_input_periodo_audit AS SELECT id, projeto, categoria, familia, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_egp_input_periodo_audit;

CREATE VIEW compat.sas_familia_ingestao_audit AS SELECT id, categoria, familia, campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_familia_ingestao_audit;

CREATE VIEW compat.sas_input_alias_canonico AS SELECT chave_canonica, chave_canonica_alvo, membro, lib, lib_canonica, path_fisico, n_egps, eh_canonico, origem_decisao, motivo, ativo, updated_by, updated_at FROM legado.sas_input_alias_canonico;

CREATE VIEW compat.sas_pipeline_metrics AS SELECT captured_at, escopo, metric, valor FROM legado.sas_pipeline_metrics;

CREATE VIEW compat.sas_resumo_proj AS SELECT chave_canonica, projeto FROM legado.sas_resumo_proj;

-- O privilégio padrão do legado (0005) só dá SELECT; o INSERT/DELETE da sincronização foi dado
-- às tabelas que existiam na 0005. Tabela nova precisa dele explícito: sem isto a sincronização
-- não grava as novas. O SELECT fica explícito também. As views compat já nascem legíveis pela 0004.
GRANT SELECT ON legado.sas_egp_atualizados_audit, legado.sas_egp_dep_mantida_audit, legado.sas_egp_input_periodo_audit, legado.sas_familia_ingestao_audit, legado.sas_input_alias_canonico, legado.sas_pipeline_metrics, legado.sas_resumo_proj TO app_leitura, sincronizador;
GRANT INSERT, DELETE ON legado.sas_egp_atualizados_audit, legado.sas_egp_dep_mantida_audit, legado.sas_egp_input_periodo_audit, legado.sas_familia_ingestao_audit, legado.sas_input_alias_canonico, legado.sas_pipeline_metrics, legado.sas_resumo_proj TO sincronizador;
```

- [ ] **Step 4: Rode `sync` e `db`.** Esperado: tudo passa.

- [ ] **Step 5: Commit** (só se pedido): `feat(app): espelho completo, com as 7 tabelas das escritas e do publish`.

---

## Parte B — Escrita no Postgres

> **Ordem de execução (15/10):** faça a Task C1 (a rota `sync-grupo` sai) ANTES da B2. Sem isso, o guarda de cobertura da B2 acusa a rota, que não tem teste. Feita antes, a C1 aplica só a remoção (os hunks de tradução do diff dela são da B2), e as contagens da B2 caem: 157 linhas de dialeto em vez de 161, 139 trocas do tradutor em vez de 143, 4 alvos de SET montados em Python em vez de 5.

### Task B1: Papel `app_escrita`, `uuid()` e o harness de teste

O app grava pelas mesmas views `compat` que lê. Provado no Postgres 17.11: um papel com
privilégio só na view grava pela view, inclusive com `MERGE`, e não lê o `legado` direto.
`app_escrita` herda `app_leitura` e grava só nas 33 views que o backend grava. As 7 que só o
publish grava ficam para o papel do publish, no plano 2b.

**Files:**
- Create: `db/migrations/0007_escrita_app.sql`
- Create: `backend/test_escritas_pg.py`

- [ ] **Step 1: Os testes das escritas.**
  - O harness sobe o app de verdade em modo Postgres num subprocesso, porque `FQ` e as tabelas `T_*` são fixadas no import do `main` e o modo não troca dentro do pytest.
  - O banco de teste recebe a massa sintética do ensaio (300 inputs, 40 EGPs, 26 no escopo) e um admin.
  - Há uma rota de escrita por teste. Cada teste confere a linha gravada, o autor, o formato do horário em coluna texto e a auditoria.
  - Há também os dois testes de escrita dentro de GET, e o teste de que `app_escrita` grava EXATAMENTE nas tabelas que o backend grava, extraídas do próprio código.

```python
# -*- coding: utf-8 -*-
"""Escritas no Postgres (Fase 2, ADR 0005): o espelho vira a fonte, e cada rota de escrita
grava no legado pelas views compat, com o papel app_escrita.

O app roda de verdade, em modo Postgres, num subprocesso: FQ e as tabelas T_* são fixadas no
import do main, então o modo não troca dentro do processo do pytest. O banco é um só para o
módulo e cada teste grava em chaves próprias, com três estados que são do banco inteiro: o
snapshot da priorização (linha única id='current' — o teste do GET apaga antes de ler, para
não depender da ordem), o contador diário da fragilidade (uma linha por dia) e o recálculo do
escopo, que regrava escopo_indi e o funil de todos (nenhum outro teste confere esses campos)."""
import datetime
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import migra  # noqa: E402
from sync import sintetico  # noqa: E402
from sync.espelho_tabelas import TABELAS  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
pytestmark = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")
APP = pathlib.Path(__file__).resolve().parent.parent
ADMIN = "admin.teste@indicium.ai"
# Instante gravado em coluna texto: o formato do Spark, sem fuso ('2026-10-15 19:27:07.090031').
INSTANTE_TEXTO = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(\.\d{1,6})?")


@pytest.fixture(scope="module")
def banco():
    import psycopg
    nome = "t_escr_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    try:
        dsn = f"{DSN.rpartition('/')[0]}/{nome}"
        migra.aplica(dsn, saida=lambda *_: None)
        with psycopg.connect(dsn) as c:   # a massa do ensaio: 300 inputs, 40 EGPs, 26 no escopo
            sintetico.carrega_sintetico(c)
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("SELECT set_config('app.usuario', %s, false)", (ADMIN,))
            c.execute("INSERT INTO cadastro.usuario (email, nome, papel) VALUES (%s, 'Admin Teste', 'admin')",
                      (ADMIN,))
        yield dsn
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app(banco, tmp_path_factory):
    porta = _porta_livre()
    log = tmp_path_factory.mktemp("app") / "app.log"
    # A porta vai nas duas variáveis: DATABRICKS_APP_PORT tem precedência no main. A rotina de
    # consulta fica desligada (é do Databricks e subiria uma thread no servidor).
    env = {**os.environ, "DB_BACKEND": "postgres", "PG_DSN": banco, "PUBLISH_SCHEMA": "compat",
           "IDENTIDADE": "dev", "DEV_USUARIO": ADMIN, "PG_PAPEL": "app_escrita",
           "SOMENTE_LEITURA": "0", "APP_PORT": str(porta), "DATABRICKS_APP_PORT": str(porta),
           "CONSULTA_SNAPSHOT": "0", "FAMILIAS_SAFRA": "1"}
    with open(log, "w", encoding="utf-8") as saida:
        proc = subprocess.Popen([sys.executable, "backend/main.py"], cwd=APP, env=env,
                                stdout=saida, stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{porta}"
        for _ in range(150):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1)
                break
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError("o app não subiu:\n" + log.read_text(encoding="utf-8"))
                time.sleep(0.2)
        else:
            proc.kill()
            proc.wait()
            raise RuntimeError("o app não respondeu em 30 s:\n" + log.read_text(encoding="utf-8"))
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def chama(app, metodo, rota, corpo=None):
    """(status, json ou texto do erro)."""
    dados = None if corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(app + rota, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def linhas(banco, sql, params=None):
    import psycopg
    with psycopg.connect(banco) as c:
        return c.execute(sql, params).fetchall()


def grava(banco, sql, params=None):
    import psycopg
    with psycopg.connect(banco, autocommit=True) as c:
        c.execute(sql, params)


# ------------------------------------------------------------------ papel do app
# Gravadas pelo backend mas que não migram: sas_egp_prioridades (spec: rotas sem tela) e as
# da rotina de consulta (só Databricks; somem na virada — gravadas via variável `tabela`).
NAO_MIGRAM = {"sas_egp_prioridades"}


def _tabelas_que_o_backend_grava():
    main = (APP / "backend" / "main.py").read_text(encoding="utf-8")
    atu = (APP / "backend" / "egps_atualizados.py").read_text(encoding="utf-8")
    mapa = dict(re.findall(r'^(T_[A-Z0-9_]+) = f"\{FQ\}\.(sas_[a-z0-9_]+)"', main, re.M))
    mapa.update(re.findall(r'^\s+(t_[a-z_]+) = f"\{fq\}\.(sas_[a-z0-9_]+)"', atu, re.M))
    alvos, sem_mapa = set(), set()
    for fonte in (main, atu):
        for nome in re.findall(r"(?:INSERT INTO|UPDATE|MERGE INTO|DELETE FROM)\s+\{([A-Za-z_][A-Za-z0-9_]*)\}", fonte):
            (alvos.add(mapa[nome]) if nome in mapa else sem_mapa.add(nome))
        alvos |= set(re.findall(r"(?:INSERT INTO|UPDATE|MERGE INTO|DELETE FROM)\s+\{FQ\}\.(sas_[a-z0-9_]+)", fonte))
    # `tabela` é a rotina de consulta (INSERT INTO {tabela}_dia, ao lado do INSERT OVERWRITE),
    # que sai no 2c; qualquer outro nome é escrita que este teste não sabe a que tabela vai.
    assert sem_mapa <= {"tabela"}, f"escrita em tabela que o teste não resolve: {sorted(sem_mapa - {'tabela'})}"
    return alvos - NAO_MIGRAM


def test_app_escrita_grava_exatamente_o_que_o_backend_grava(banco):
    """Menos que isso quebra uma rota na hora de gravar; mais que isso deixa o app gravar no
    que é só do publish (arestas da linhagem, versão e I/O dos EGPs atualizados, alias,
    métricas, resumo por projeto). Varre o banco inteiro, não só as views compat: um GRANT
    amplo no legado também acusa."""
    grava_app = _tabelas_que_o_backend_grava()
    assert len(grava_app) >= 30                  # o padrão ainda acha as escritas (sanidade)
    assert grava_app <= set(TABELAS), sorted(grava_app - set(TABELAS))
    com_privilegio = {n for (n,) in linhas(banco, """
        SELECT nsp.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace nsp ON nsp.oid = c.relnamespace
        WHERE nsp.nspname NOT IN ('pg_catalog', 'information_schema') AND c.relkind IN ('r', 'v', 'p', 'f', 'm')
          AND (has_table_privilege('app_escrita', c.oid, 'INSERT') OR has_table_privilege('app_escrita', c.oid, 'UPDATE')
               OR has_table_privilege('app_escrita', c.oid, 'DELETE'))""")}
    assert com_privilegio == {f"compat.{t}" for t in grava_app}, (sorted(com_privilegio), sorted(grava_app))


# ------------------------------------------------------------------ Gestão: cadastros
def test_responsavel_bv_cria_e_edita_com_autoria(app, banco):
    st, r = chama(app, "POST", "/api/responsaveis-bv", {"nome": "Fulana Responsável", "subarea": "Cobrança"})
    assert st == 200, r
    st, r = chama(app, "POST", "/api/responsaveis-bv", {"nome": "Fulana Responsável", "ativo": False})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT nome, subarea, ativo, created_by, updated_by, created_at, updated_at "
                           "FROM legado.sas_responsaveis_bv WHERE nome = 'Fulana Responsável'")
    assert row[:5] == ("Fulana Responsável", "Cobrança", False, ADMIN, ADMIN)
    assert INSTANTE_TEXTO.fullmatch(row[5]) and INSTANTE_TEXTO.fullmatch(row[6]), row


def test_analista_cria_desativa_e_canoniza_o_email(app, banco):
    st, r = chama(app, "POST", "/api/analistas", {"email": "Ana.Teste@indicium.tech", "nome": "Ana Teste"})
    assert st == 200 and r["email"] == "ana.teste@indicium.ai", r
    email = "ana.teste@indicium.ai"
    st, r = chama(app, "DELETE", f"/api/analistas/{email}")
    assert st == 200, r
    (row,) = linhas(banco, "SELECT nome, ativo, created_by, updated_by, created_at, updated_at "
                           "FROM legado.sas_analistas WHERE email = 'ana.teste@indicium.ai'")
    assert row[:4] == ("Ana Teste", False, ADMIN, ADMIN), row
    assert INSTANTE_TEXTO.fullmatch(row[4]) and INSTANTE_TEXTO.fullmatch(row[5]), row


# ------------------------------------------------------------------ Inputs
def test_input_grava_campo_humano_e_audita(app, banco):
    chave = "tabela::LIB0.TAB_0000"
    st, r = chama(app, "PATCH", "/api/inputs", {"chave_canonica": chave, "responsavel": "Fulano",
                                                "observacao": "conferido"})
    assert st == 200 and r["responsavel"] == "Fulano", r
    (row,) = linhas(banco, "SELECT responsavel, observacao, updated_by, updated_at FROM legado.sas_inputs_monitor "
                           "WHERE chave_canonica = %s", (chave,))
    assert row[:3] == ("Fulano", "conferido", ADMIN) and row[3] is not None, row
    aud = linhas(banco, "SELECT campo, valor_novo, updated_by, updated_at IS NOT NULL FROM legado.sas_inputs_audit "
                        "WHERE chave_canonica = %s ORDER BY campo", (chave,))
    assert aud == [("observacao", "conferido", ADMIN, True), ("responsavel", "Fulano", ADMIN, True)], aud


def test_preworking_grava_checklist(app, banco):
    chave = "arquivo::ARQ_0001.CSV"
    st, r = chama(app, "PATCH", "/api/inputs/preworking", {"chave_canonica": chave, "frequencia": "Diária",
                                                           "recebido": "true", "data_recebimento": "2026-10-01"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT frequencia, recebido, data_recebimento, updated_by, updated_at "
                           "FROM legado.sas_inputs_preworking WHERE chave_canonica = %s", (chave,))
    assert row[:4] == ("Diária", "true", "2026-10-01", ADMIN) and INSTANTE_TEXTO.fullmatch(row[4]), row
    aud = linhas(banco, "SELECT campo, valor_novo, updated_by, updated_at IS NOT NULL FROM legado.sas_inputs_audit "
                        "WHERE chave_canonica = %s ORDER BY campo", (chave,))
    assert aud == [("preworking.data_recebimento", "2026-10-01", ADMIN, True),
                   ("preworking.frequencia", "Diária", ADMIN, True),
                   ("preworking.recebido", "true", ADMIN, True)], aud


def test_familia_ingestao_grava_e_audita(app, banco):
    st, r = chama(app, "PATCH", "/api/familia-ingestao", {"categoria": "tabela", "familia": "LIB1.TAB",
                                                          "desde": "202601", "ingerida_em": "2026-10-01"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT desde, ingerida_em, updated_by FROM legado.sas_familia_ingestao "
                           "WHERE categoria = 'tabela' AND familia = 'LIB1.TAB'")
    assert row == ("202601", "2026-10-01", ADMIN), row
    aud = linhas(banco, "SELECT campo, valor_antigo, valor_novo, ator, ts IS NOT NULL "
                        "FROM legado.sas_familia_ingestao_audit WHERE familia = 'LIB1.TAB'")
    assert aud == [("desde", "", "202601", ADMIN, True)], aud


# ------------------------------------------------------------------ EGPs
EGP = "Cobranças__EGP_TREINO_000"


def _um_input_do(banco, projeto):
    return linhas(banco, "SELECT chave_canonica FROM legado.sas_egp_inputs WHERE projeto = %s "
                         "ORDER BY chave_canonica LIMIT 1", (projeto,))[0][0]


def test_pipeline_do_egp_grava_campos_e_audita(app, banco):
    st, r = chama(app, "PATCH", "/api/egp-pipeline", {"projeto": EGP, "responsavel": "Fulano", "jira_id": "BV-123"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT responsavel, jira_id, updated_by, updated_at FROM legado.sas_egp_pipeline "
                           "WHERE projeto = %s", (EGP,))
    assert row[:3] == ("Fulano", "BV-123", ADMIN) and INSTANTE_TEXTO.fullmatch(row[3]), row
    aud = linhas(banco, "SELECT campo, ator, ts FROM legado.sas_pipeline_audit WHERE projeto = %s", (EGP,))
    assert {"responsavel", "jira_id"} <= {a[0] for a in aud}, aud
    assert all(a[1] == ADMIN and INSTANTE_TEXTO.fullmatch(a[2]) for a in aud), aud


def test_vinculo_copia_o_trabalho_para_o_sucessor(app, banco):
    antigo, sucessor = "Riscos__EGP_TREINO_001", "Jurídico__EGP_TREINO_002"
    assert chama(app, "PATCH", "/api/egp-pipeline", {"projeto": antigo, "responsavel": "Beltrano"})[0] == 200
    st, r = chama(app, "PATCH", "/api/egp-pipeline", {"projeto": antigo, "egp_vinculo_tipo": "Substituído",
                                                      "egp_sucessor": sucessor})
    assert st == 200, r
    (v,) = linhas(banco, "SELECT egp_vinculo_tipo, egp_sucessor FROM legado.sas_egp_pipeline WHERE projeto = %s",
                  (antigo,))
    assert v == ("Substituído", sucessor), v
    (s,) = linhas(banco, "SELECT responsavel, updated_by FROM legado.sas_egp_pipeline WHERE projeto = %s", (sucessor,))
    assert s == ("Beltrano", ADMIN), s


def test_leitura_dispensada_do_input_no_egp(app, banco):
    chave = _um_input_do(banco, EGP)
    st, r = chama(app, "PATCH", "/api/egp-input-link", {"projeto": EGP, "chave_canonica": chave, "link_broken": True})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT link_broken, updated_by FROM legado.sas_egp_input_link "
                           "WHERE projeto = %s AND chave_canonica = %s", (EGP, chave))
    assert row == (True, ADMIN), row
    aud = linhas(banco, "SELECT chave_canonica, campo, ator, ts IS NOT NULL FROM legado.sas_egp_input_link_audit "
                        "WHERE projeto = %s", (EGP,))
    assert aud == [(chave, "link_broken", ADMIN, True)], aud


def test_periodo_da_familia_no_egp(app, banco):
    st, r = chama(app, "PATCH", "/api/familia-periodo", {"projeto": EGP, "categoria": "tabela", "familia": "LIB2.TAB",
                                                         "tipo": "desde", "valor": "202601"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT tipo, valor, updated_by FROM legado.sas_egp_input_periodo "
                           "WHERE projeto = %s AND familia = 'LIB2.TAB'", (EGP,))
    assert row == ("desde", "202601", ADMIN), row
    aud = linhas(banco, "SELECT campo, valor_novo, ator, ts IS NOT NULL FROM legado.sas_egp_input_periodo_audit "
                        "WHERE projeto = %s", (EGP,))
    assert aud == [("periodo", "desde:202601", ADMIN, True)], aud


def test_ainda_e_dependencia_grava_por_par_e_audita(app, banco):
    produtor = "Riscos__EGP_TREINO_007"
    consumidor, chave, art = linhas(banco, "SELECT e.projeto, e.chave_canonica, i.artifact FROM legado.sas_egp_inputs e "
                                           "JOIN legado.sas_inputs_monitor i USING (chave_canonica) "
                                           "WHERE e.projeto <> %s AND i.categoria = 'tabela' ORDER BY 1, 2 LIMIT 1",
                                    (produtor,))[0]
    grava(banco, "INSERT INTO legado.sas_lineage_edges (projeto_alvo, depende_do, via_tabelas) VALUES (%s, %s, %s)",
          (consumidor, produtor, art))
    st, r = chama(app, "PATCH", "/api/egp-dep-mantida", {"produtor": produtor, "mantida": True, "motivo": "falta coluna"})
    assert st == 200 and r["fan_out"]["alteracoes"] == 1, r
    (row,) = linhas(banco, "SELECT motivo, updated_by FROM legado.sas_egp_dep_mantida "
                           "WHERE projeto = %s AND chave_canonica = %s", (consumidor, chave))
    assert row == ("falta coluna", ADMIN), row
    aud = linhas(banco, "SELECT chave_canonica, campo, valor_antigo, valor_novo, ator, ts IS NOT NULL "
                        "FROM legado.sas_egp_dep_mantida_audit WHERE projeto = %s", (consumidor,))
    assert aud == [(chave, "dep_mantida", "false", "true", ADMIN, True)], aud


def test_egp_novo_declarado_vai_para_a_config(app, banco):
    st, r = chama(app, "PATCH", "/api/egps-novos", {"projeto": "Jurídico__EGP_TREINO_029", "acao": "declarar"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT valor, updated_by, updated_at FROM legado.sas_app_config WHERE chave = 'egps_novos'")
    assert "Jurídico__EGP_TREINO_029" in row[0] and row[1] == ADMIN and INSTANTE_TEXTO.fullmatch(row[2]), row
    (aud,) = linhas(banco, "SELECT valor_novo, ator, ts FROM legado.sas_pipeline_audit "
                           "WHERE projeto = '(config)' AND campo = 'egps_novos'")
    assert "Jurídico__EGP_TREINO_029" in aud[0] and aud[1] == ADMIN and INSTANTE_TEXTO.fullmatch(aud[2]), aud


def test_egp_atualizado_grava_tipo_de_vinculo_e_audita(app, banco):
    grava(banco, "INSERT INTO legado.sas_egp_atualizados (versao_id, egp_key, nome, area) "
                 "VALUES ('v1', 'Riscos__EGP_NOVO', 'EGP NOVO', 'Riscos')")
    st, r = chama(app, "PATCH", "/api/egp-atualizado-pipeline", {"egp_key": "Riscos__EGP_NOVO",
                                                                 "tipo_vinculo": "substituicao"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT tipo_vinculo, updated_by FROM legado.sas_egp_atualizados_pipeline "
                           "WHERE egp_key = 'Riscos__EGP_NOVO'")
    assert row == ("substituicao", ADMIN), row
    (aud,) = linhas(banco, "SELECT campo, valor_novo, autor, length(id), ts IS NOT NULL "
                           "FROM legado.sas_egp_atualizados_audit WHERE egp_key = 'Riscos__EGP_NOVO'")
    assert aud == ("tipo_vinculo", "substituicao", ADMIN, 36, True), aud


# ------------------------------------------------------------------ Outputs
def test_pipeline_do_output(app, banco):
    st, r = chama(app, "PATCH", "/api/output-pipeline", {"chave_canonica": "tabela::SAIDA.X", "recebido": True,
                                                         "recebido_data": "2026-10-01"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT recebido, recebido_data, updated_by, updated_at FROM legado.sas_outputs_pipeline "
                           "WHERE chave_canonica = 'tabela::SAIDA.X'")
    assert row[:3] == ("true", "2026-10-01", ADMIN) and INSTANTE_TEXTO.fullmatch(row[3]), row


def test_produtor_escolhido_grava_e_apaga(app, banco):
    chave = "tabela::SAIDA.Y"
    for p in ("Cobranças__EGP_TREINO_003", "Riscos__EGP_TREINO_004"):
        grava(banco, "INSERT INTO legado.sas_egp_outputs (projeto, area, chave_canonica, artifact, categoria) "
                     "VALUES (%s, %s, %s, 'SAIDA.Y', 'tabela')", (p, p.split("__")[0], chave))
    grava(banco, "INSERT INTO legado.sas_outputs_monitor (chave_canonica, artifact, categoria, qtd_produtores) "
                 "VALUES (%s, 'SAIDA.Y', 'tabela', 2)", (chave,))
    st, r = chama(app, "POST", "/api/output-producer", {"chave_canonica": chave,
                                                        "projeto_escolhido": "Riscos__EGP_TREINO_004"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT projeto_escolhido, chosen_by, chosen_at FROM legado.sas_output_producer_choice "
                           "WHERE chave_canonica = %s", (chave,))
    assert row[:2] == ("Riscos__EGP_TREINO_004", ADMIN) and INSTANTE_TEXTO.fullmatch(row[2]), row
    st, r = chama(app, "DELETE", "/api/output-producer?chave=" + urllib.parse.quote(chave))
    assert st == 200, r
    assert linhas(banco, "SELECT count(*) FROM legado.sas_output_producer_choice WHERE chave_canonica = %s",
                  (chave,))[0][0] == 0


# ------------------------------------------------------------------ Escopo
def test_escopo_inclui_desativa_e_reativa_recalculando(app, banco):
    projeto = "Riscos__EGP_TREINO_028"
    assert linhas(banco, "SELECT escopo_indi FROM legado.sas_lineage_nodes WHERE projeto = %s", (projeto,)) == [(False,)]
    st, r = chama(app, "POST", "/api/escopo", {"egp_dor1": "EGP_TREINO_028", "area": "Riscos", "projeto": projeto})
    assert st == 200, r
    (rid, por, em) = linhas(banco, "SELECT id, created_by, created_at FROM legado.sas_escopo WHERE projeto = %s",
                            (projeto,))[0]
    assert por == ADMIN and INSTANTE_TEXTO.fullmatch(em), (por, em)
    assert linhas(banco, "SELECT escopo_indi FROM legado.sas_lineage_nodes WHERE projeto = %s", (projeto,)) == [(True,)]
    assert chama(app, "DELETE", f"/api/escopo/{rid}")[0] == 200
    assert linhas(banco, "SELECT escopo_indi FROM legado.sas_lineage_nodes WHERE projeto = %s", (projeto,)) == [(False,)]
    assert chama(app, "POST", f"/api/escopo/{rid}/ativar")[0] == 200
    assert linhas(banco, "SELECT escopo_indi FROM legado.sas_lineage_nodes WHERE projeto = %s", (projeto,)) == [(True,)]
    aud = linhas(banco, "SELECT acao, ator, ts FROM legado.sas_escopo_audit WHERE projeto = %s ORDER BY ts", (projeto,))
    assert [a[:2] for a in aud] == [("add", ADMIN), ("desativar", ADMIN), ("reativar", ADMIN)], aud
    assert all(INSTANTE_TEXTO.fullmatch(a[2]) for a in aud), aud


# ------------------------------------------------------------------ escritas dentro de GET
# Na Fase 1 a AWS só lia e quem gravava era o Databricks; com a escrita ligada (Fase 2) as
# duas voltam a valer também no Postgres — senão a série diária e a semente param na virada.
def test_get_da_fragilidade_grava_o_contador_do_dia(app, banco):
    st, r = chama(app, "GET", "/api/inputs/fragilidade")
    assert st == 200, r
    assert linhas(banco, "SELECT count(*) FROM legado.sas_app_config WHERE chave LIKE 'san_contadores::%'")[0][0] == 1


def test_get_da_priorizacao_sem_snapshot_grava_a_semente(app, banco):
    grava(banco, "DELETE FROM legado.sas_priorizacao_snapshot")   # sem snapshot, qualquer que seja a ordem
    st, r = chama(app, "GET", "/api/priorizacao")
    assert st == 200, r
    assert linhas(banco, "SELECT saved_by FROM legado.sas_priorizacao_snapshot WHERE id = 'current'") == [("auto",)]


# ------------------------------------------------------------------ Priorização
def test_snapshot_da_priorizacao(app, banco):
    fixado = "Riscos__EGP_TREINO_010"
    st, r = chama(app, "POST", "/api/priorizacao/snapshot", {"pins": {fixado: 3}, "capacidade": 5})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT capacidade, saved_by, saved_at FROM legado.sas_priorizacao_snapshot "
                           "WHERE id = 'current'")
    assert row[:2] == (5, ADMIN) and INSTANTE_TEXTO.fullmatch(row[2]), row
    (pin,) = linhas(banco, "SELECT mes_prioridade, updated_by, updated_at FROM legado.sas_egp_pipeline "
                           "WHERE projeto = %s", (fixado,))
    assert pin[:2] == (3, ADMIN) and INSTANTE_TEXTO.fullmatch(pin[2]), pin
    (cap,) = linhas(banco, "SELECT valor, updated_by, updated_at FROM legado.sas_app_config "
                           "WHERE chave = 'prio_capacidade'")
    assert cap[:2] == ("5", ADMIN) and INSTANTE_TEXTO.fullmatch(cap[2]), cap
    aud = linhas(banco, "SELECT projeto, campo, valor_novo, ator, ts FROM legado.sas_pipeline_audit "
                        "WHERE (projeto = '(config)' AND campo IN ('capacidade_mes', 'priorizacao_snapshot')) "
                        "OR (projeto = %s AND campo = 'mes_prioridade') ORDER BY campo", (fixado,))
    assert [a[:2] for a in aud] == [("(config)", "capacidade_mes"), (fixado, "mes_prioridade"),
                                    ("(config)", "priorizacao_snapshot")], aud
    assert aud[0][2] == "5" and aud[1][2] == "3" and INSTANTE_TEXTO.fullmatch(aud[2][2]), aud   # a hora do snapshot
    assert all(a[3] == ADMIN and INSTANTE_TEXTO.fullmatch(a[4]) for a in aud), aud


# ------------------------------------------------------------------ Gestão
def test_gestao_status_comentario(app, banco):
    st, r = chama(app, "POST", "/api/gestao/status", {"entity": "egp", "id": EGP, "autor": "Fulano", "texto": "andando"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT autor, criado_por, texto, ts FROM legado.sas_gestao_status "
                           "WHERE entity_id = %s AND texto = 'andando'", (EGP,))
    assert row[:3] == ("Fulano", ADMIN, "andando") and INSTANTE_TEXTO.fullmatch(row[3]), row


def test_gestao_com_bv_grava_hoje_e_apaga(app, banco):
    def hoje_sp():
        return datetime.datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()

    antes = hoje_sp()
    st, r = chama(app, "POST", "/api/gestao/bv", {"entity": "egp", "id": EGP, "comBv": True})
    depois = hoje_sp()
    assert st == 200, r
    (bid, data, autor, ts) = linhas(banco, "SELECT id, data, autor, ts FROM legado.sas_gestao_bv WHERE entity_id = %s",
                                    (EGP,))[0]
    # sem data no corpo, vale HOJE em São Paulo (o dia pode virar durante a chamada)
    assert data in (antes, depois) and autor == ADMIN and INSTANTE_TEXTO.fullmatch(ts), (data, antes, autor, ts)
    assert chama(app, "DELETE", f"/api/gestao/bv?id={bid}")[0] == 200
    assert linhas(banco, "SELECT count(*) FROM legado.sas_gestao_bv WHERE id = %s", (bid,))[0][0] == 0
    aud = linhas(banco, "SELECT valor_antigo, valor_novo, ator, ts FROM legado.sas_pipeline_audit "
                        "WHERE projeto = %s AND campo = 'ComBV' ORDER BY ts", (EGP,))
    assert [a[:3] for a in aud] == [("-", "Com BV", ADMIN), ("Com BV", "DELETADO", ADMIN)], aud
    assert all(INSTANTE_TEXTO.fullmatch(a[3]) for a in aud), aud


def test_gestao_revisao_e_datas(app, banco):
    assert chama(app, "POST", "/api/gestao/revisao", {"id": EGP, "delta": 1})[0] == 200
    assert chama(app, "PATCH", "/api/gestao/datas", {"entity": "egp", "id": EGP, "campo": "inicio",
                                                     "valor": "2026-10-01"})[0] == 200
    (rev,) = linhas(banco, "SELECT contador, updated_by, updated_at FROM legado.sas_gestao_revisao "
                           "WHERE entity_id = %s", (EGP,))
    assert rev[:2] == (1, ADMIN) and INSTANTE_TEXTO.fullmatch(rev[2]), rev
    (dat,) = linhas(banco, "SELECT inicio, updated_by, updated_at FROM legado.sas_gestao_datas "
                           "WHERE entity_id = %s", (EGP,))
    assert dat[:2] == ("2026-10-01", ADMIN) and INSTANTE_TEXTO.fullmatch(dat[2]), dat
    aud = linhas(banco, "SELECT campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_pipeline_audit "
                        "WHERE projeto = %s AND campo IN ('RevisaoRegras', 'inicio') ORDER BY campo", (EGP,))
    assert [a[:4] for a in aud] == [("RevisaoRegras", "0", "1", ADMIN), ("inicio", "", "2026-10-01", ADMIN)], aud
    assert all(INSTANTE_TEXTO.fullmatch(a[4]) for a in aud), aud
```

- [ ] **Step 2: Rode e veja falhar.**

```bash
PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres .venv/bin/python -m pytest -q -p no:cacheprovider backend/test_escritas_pg.py -x
```

Esperado: `502 ... couldn't get a connection after 30.00 sec`. O pool não abre conexão, porque o `SET ROLE app_escrita` falha: o papel ainda não existe.

- [ ] **Step 3: A migração 0007:**

```sql
-- Escrita do app no Postgres (Fase 2, decisão de 15/10/2026): o espelho `legado` vira a FONTE.
-- O app grava pelas MESMAS views compat que lê: são views simples de uma tabela só, e o
-- Postgres aceita INSERT/UPDATE/DELETE/MERGE nelas, gravando no legado. Assim o SQL de escrita
-- muda só de dialeto, não de tabela.
--
-- app_escrita = app_leitura + escrita nas 33 views que o backend grava — entre elas os nós da
-- linhagem e as tabelas de input/output do corpus (o recálculo do escopo marca escopo_indi) e o
-- funil/auditoria dos EGPs atualizados (tipo_vinculo). As 7 que só o publish grava — as arestas
-- da linhagem, a versão recebida e o I/O dos EGPs atualizados (sas_egp_atualizados, _inputs,
-- _outputs), o alias canônico, as métricas e o resumo por projeto — ficam para o papel do
-- publish (plano 2b). Na Fase 1 o app segue com app_leitura e nada disto é usado.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_escrita') THEN
    CREATE ROLE app_escrita NOLOGIN;
  END IF;
END $$;

GRANT app_leitura TO app_escrita;

GRANT INSERT, UPDATE, DELETE ON
  compat.sas_analistas,
  compat.sas_app_config,
  compat.sas_egp_atualizados_audit,
  compat.sas_egp_atualizados_pipeline,
  compat.sas_egp_dep_mantida,
  compat.sas_egp_dep_mantida_audit,
  compat.sas_egp_input_link,
  compat.sas_egp_input_link_audit,
  compat.sas_egp_input_periodo,
  compat.sas_egp_input_periodo_audit,
  compat.sas_egp_inputs,
  compat.sas_egp_outputs,
  compat.sas_egp_pipeline,
  compat.sas_escopo,
  compat.sas_escopo_audit,
  compat.sas_familia_ingestao,
  compat.sas_familia_ingestao_audit,
  compat.sas_funil_area,
  compat.sas_gestao_bv,
  compat.sas_gestao_datas,
  compat.sas_gestao_revisao,
  compat.sas_gestao_status,
  compat.sas_inputs_audit,
  compat.sas_inputs_monitor,
  compat.sas_inputs_preworking,
  compat.sas_lineage_nodes,
  compat.sas_output_producer_choice,
  compat.sas_outputs_monitor,
  compat.sas_outputs_pipeline,
  compat.sas_pipeline_audit,
  compat.sas_priorizacao_snapshot,
  compat.sas_responsaveis_bv,
  compat.sas_resumo_inputs
TO app_escrita;

-- O app entra com o usuário MESTRE e baixa a sessão para PG_PAPEL (app_escrita na Fase 2).
GRANT app_escrita TO CURRENT_USER;

-- uuid() do Spark (ids de auditoria gerados no INSERT): texto, como o Spark devolve.
CREATE FUNCTION compat.uuid() RETURNS text
LANGUAGE sql VOLATILE AS $$ SELECT gen_random_uuid()::text $$;
```

- [ ] **Step 4:** Rode de novo. O teste de privilégios passa, e as rotas falham agora com o SQL do Databricks: `current_user() ... syntax error`, `SET target columns cannot be qualified`. Isso é o trabalho da Task B2.

### Task B2: O SQL de escrita nos dois bancos

**Files:**
- Modify: `backend/main.py`, `backend/egps_atualizados.py`
- Modify: `backend/test_ponte_tipo_vinculo.py`, `backend/test_egp_pipeline_patch_parcial.py`
- Create: `backend/test_escritas_portadas.py`
- Modify: `backend/db_pg.py`, `backend/test_db_pg.py` (Step 3b: a sessão fixa o DateStyle)

O que muda, em todos os casos sem mudar o SQL que o Databricks recebe:

| Idioma do Spark | Nos dois bancos | Por quê |
|---|---|---|
| `current_user()` | `{_ator()}` | não existe no Postgres; lá, o e-mail que o middleware conferiu, como literal |
| `current_timestamp()` | `{AGORA}` | no Postgres, `localtimestamp`: numa coluna texto sai no formato do Spark (`2026-10-15 19:27:07.090031`), enquanto `current_timestamp` levaria `+00` |
| `SET t.col = ...` | `SET col = ...` | o Postgres não aceita coluna-alvo qualificada (`SET target columns cannot be qualified`); o Spark aceita as duas formas |
| `current_date()` | `current_date` | já era a forma portável das rotas GET (1b) |
| `CREATE TABLE ... USING DELTA` solto | atrás de `if not dialeto.PG:` | no Postgres o schema vem das migrações, e o papel do app não tem CREATE |
| `uuid()` | sem mudança | `compat.uuid()` (0007) |

Das escritas que acontecem dentro de um GET, a fase 1 desligou duas no Postgres: o contador
diário de sanitização e a semente da priorização. Agora elas ficam desligadas só em modo
leitura. Com a escrita ligada, o Postgres grava, senão a série e a semente param na virada.

- [ ] **Step 1: Os guardas,** que rodam sem banco e se somam aos testes da Task B1:
- rota de escrita nova sem teste no Postgres, nem motivo para não ter;
- `current_user()`, `current_timestamp()` ou `SET t.` em f-string fora dos helpers;
- DDL sem checagem de `dialeto.PG`.

Rodados contra o `main.py` de antes do porte, eles acusam 161 linhas de dialeto e 6 DDL soltos.

```python
# -*- coding: utf-8 -*-
"""Guarda do porte das escritas (Fase 2, ADR 0005), sem banco: rota de escrita nova precisa
de teste no Postgres (test_escritas_pg.py), e SQL de escrita não volta ao dialeto do
Databricks — no Postgres ele quebraria só na hora de gravar."""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m  # noqa: E402

AQUI = pathlib.Path(__file__).resolve().parent

# Rotas de escrita sem teste no Postgres, com o motivo. Rota nova entra no teste ou aqui.
FORA_DO_TESTE = {
    ("POST", "/api/priorizacao/preview"): "não grava: só calcula a prévia",
    ("POST", "/api/prioridades"): "sas_egp_prioridades não migra (spec): rotas sem tela",
    ("PATCH", "/api/prioridades/{}"): "idem",
    ("POST", "/api/prioridades/{}/move"): "idem",
    ("DELETE", "/api/prioridades/{}"): "idem",
}


def _normaliza(caminho):
    return re.sub(r"\{[^}]*\}", "{}", caminho)


def _rotas_de_escrita():
    rotas = set()
    for r in m.app.routes:
        caminho = getattr(r, "path", "")
        for metodo in getattr(r, "methods", set()) & {"POST", "PATCH", "PUT", "DELETE"}:
            if caminho.startswith("/api/"):
                rotas.add((metodo, _normaliza(caminho)))
    return rotas


def test_toda_rota_de_escrita_tem_teste_no_postgres_ou_motivo():
    fonte = (AQUI / "test_escritas_pg.py").read_text(encoding="utf-8")
    testadas = {(metodo, _normaliza(caminho)) for metodo, caminho in
                re.findall(r'chama\(app, "(POST|PATCH|PUT|DELETE)", f?"(/api/[^"?]+)', fonte)}
    rotas = _rotas_de_escrita()
    assert len(rotas) >= 25                      # o filtro ainda acha as rotas (sanidade do teste)
    assert not set(FORA_DO_TESTE) - rotas, "motivo para rota que não existe mais"
    sem_teste = rotas - testadas - set(FORA_DO_TESTE)
    assert not sem_teste, f"rota de escrita sem teste no Postgres: {sorted(sem_teste)}"


# Onde o dialeto do Databricks pode aparecer em f-string: o caminho só-Databricks da sessão
# OBO. (Nada de `register` aqui: as rotas do egps_atualizados.py são aninhadas nele, e
# liberá-lo isentava o arquivo inteiro.)
LIBERADAS = {"_sessao"}


def _ocorrencias_em_fstring(caminho, padrao):
    achadas, funcao = [], "<módulo>"
    for n, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        d = re.match(r"(?:async )?def ([A-Za-z0-9_]+)", linha)
        if d:
            funcao = d.group(1)
        if linha.lstrip().startswith("#") or funcao in LIBERADAS:
            continue
        for achado in re.finditer(padrao, linha):
            antes = linha[:achado.start()]
            if 'f"' in antes or "f'" in antes:
                achadas.append(f"{caminho.name}:{n} [{funcao}] {linha.strip()[:90]}")
    return achadas


def test_ddl_do_backend_so_roda_fora_do_postgres():
    """No Postgres o schema vem das migrações e o papel do app não tem CREATE: um CREATE/ALTER
    sem a checagem de dialeto falha só na hora de gravar, e às vezes calado (o log diário de
    sanitização engolia o erro). Vale como protegido: um `if dialeto.PG:` com `return` logo
    depois, antes do DDL na mesma função (os `_ensure_*`), ou o DDL dentro do bloco de um
    `if not dialeto.PG` a até 8 linhas acima. A polaridade conta: `if dialeto.PG:` acima (ou o
    DDL logo depois do bloco do `if not`) rodaria o DDL justamente no Postgres. A rotina de
    consulta é só do Databricks e sai na virada (plano 2c)."""
    soltos = _ddl_sem_protecao(AQUI / "main.py")
    assert not soltos, "\n".join(soltos)


def _ddl_sem_protecao(caminho):
    linhas_fonte = caminho.read_text(encoding="utf-8").splitlines()
    soltos, funcao, inicio = [], "<módulo>", 0
    for n, linha in enumerate(linhas_fonte):
        d = re.match(r"(?:async )?def ([A-Za-z0-9_]+)", linha)
        if d:
            funcao, inicio = d.group(1), n
        if re.search(r'f"(?:"")?\s*(CREATE TABLE|ALTER TABLE)', linha) and not funcao.startswith("_consulta"):
            antes = linhas_fonte[inicio:n]
            retorna_no_pg = any("if dialeto.PG:" in x and "return" in " ".join(antes[i:i + 2])
                                for i, x in enumerate(antes))
            if not retorna_no_pg and not _no_bloco_do_if_not_pg(antes[-8:], linha):
                soltos.append(f"{caminho.name}:{n + 1} [{funcao}] {linha.strip()[:80]}")
    return soltos


def _recuo(linha):
    return len(linha) - len(linha.lstrip())


def _no_bloco_do_if_not_pg(acima, linha):
    """O DDL está DENTRO de um `if not dialeto.PG` das linhas `acima`: tudo do if até o DDL
    (ele incluído) mais recuado que o if. Só estar perto do if não basta."""
    return any("if not dialeto.PG" in x
               and all(_recuo(y) > _recuo(x) for y in acima[i + 1:] + [linha] if y.strip())
               for i, x in enumerate(acima))


def test_sql_de_escrita_nao_usa_o_dialeto_do_databricks():
    """current_user()/current_timestamp()/current_date() não existem no Postgres (use
    _ator()/AGORA/current_date, sem parênteses), e lá a coluna-alvo de SET não pode vir
    qualificada (`SET t.col` -> `SET col`)."""
    padrao = r"current_user\(\)|current_timestamp\(\)|current_date\(\)|SET t\.|\bt\.\{"
    achadas = []
    for nome in ("main.py", "egps_atualizados.py"):
        achadas += _ocorrencias_em_fstring(AQUI / nome, padrao)
    assert not achadas, "\n".join(achadas)
```

- [ ] **Step 2: Rode e veja falhar.** Esperado: os guardas acusam o dialeto e o DDL, e quase todas as rotas devolvem 502 por `current_user()`, `SET t.` e `current_date()`.

- [ ] **Step 3: O tradutor.** Ele troca `current_user()` e `current_timestamp()` só dentro de f-string, e tira o `t.` só dos alvos de um `SET` que também está dentro de f-string. Um "UPDATE SET" num comentário abriria um trecho que engoliria o `ON t.chave` do MERGE seguinte, como aconteceu no rascunho. O que está fora de f-string ele só lista. Salve em `/tmp/porta_escritas.py` e rode a partir de `egps_analysis/app`:

```python
"""Porta o SQL de escrita do backend para rodar nos dois bancos (Fase 2):
  current_user()      -> {_ator()}   (só dentro de f-string)
  current_timestamp() -> {AGORA}     (só dentro de f-string)
  SET t.col = ...     -> SET col = ...  (alvo de SET em UPDATE/MERGE; o Postgres não aceita
                                         coluna-alvo qualificada; o Spark aceita as duas)
Fora de f-string (comentário, docstring, string simples) só LISTA, para revisão manual.
Uso: python porta_escritas.py <arquivo.py> [funções a pular, separadas por vírgula]"""
import re
import sys

caminho = sys.argv[1]
pula = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else set()
linhas = open(caminho, encoding="utf-8").read().split("\n")
func = "<módulo>"
fora = []
trocas = 0
for i, l in enumerate(linhas):
    m = re.match(r"(?:async )?def ([A-Za-z0-9_]+)", l)
    if m:
        func = m.group(1)
    if func in pula:
        continue
    for idioma, novo in (("current_user()", "{_ator()}"), ("current_timestamp()", "{AGORA}")):
        while idioma in l:
            pos = l.find(idioma)
            prefixo = l[:pos]
            if 'f"' in prefixo or "f'" in prefixo:
                l = l[:pos] + novo + l[pos + len(idioma):]
                trocas += 1
            else:
                fora.append((i + 1, func, l.strip()[:110]))
                break
    linhas[i] = l
texto = "\n".join(linhas)

# Alvos de SET: do SET até o próximo WHEN/WHERE/FROM do mesmo comando. Só conta SET dentro
# de f-string (na linha, depois de f" ou f'): um "UPDATE SET" em comentário abria um trecho
# que engolia o ON do MERGE seguinte (pego no egps_atualizados.py).
ALVO = re.compile(r"(?<![\w.])t\.([a-z_][a-z0-9_]*)(\s*=)(?!=)")
FIM = re.compile(r"\b(WHEN|WHERE|FROM)\b")
partes, pos, sets = [], 0, 0
for m in re.finditer(r"\bSET\b", texto):
    if m.start() < pos:
        continue
    inicio_linha = texto.rfind("\n", 0, m.start()) + 1
    antes = texto[inicio_linha:m.start()]
    if antes.lstrip().startswith("#") or ('f"' not in antes and "f'" not in antes):
        continue
    fim = FIM.search(texto, m.end())
    fim = fim.start() if fim else len(texto)
    trecho = texto[m.end():fim]
    novo, n = ALVO.subn(r"\1\2", trecho)
    sets += n
    partes.append(texto[pos:m.end()] + novo)
    pos = fim
partes.append(texto[pos:])
texto = "".join(partes)
open(caminho, "w", encoding="utf-8").write(texto)
print(f"{caminho}: {trocas} trocas de quem/quando, {sets} alvos de SET sem 't.'")
for n, f, l in fora:
    print(f"  fora de f-string: {n} [{f}] {l}")
```

```bash
python3 /tmp/porta_escritas.py backend/main.py _sessao,_run_sp,_ator,sql_lit
python3 /tmp/porta_escritas.py backend/egps_atualizados.py
```

Esperado em 15/10: 143 trocas e 67 alvos no `main.py`; 6 trocas e 3 alvos no `egps_atualizados.py`.

Antes de rodar, ponha os helpers logo depois de `sql_lit` (eles estão no diff abaixo).

Depois, à mão:
- as listas de SET que não são f-string viram `f"... = {AGORA}"` e `f"... = {_ator()}"`: o `sets += [...]` de `_patch_familia` e os `sets.append(...)` de `patch_input` e `prioridades_patch`;
- `_write_prio_snapshot(payload, "current_user()", ...)` passa `_ator()`;
- o padrão de data do "Com BV" vira f-string com `{AGORA}`;
- os 5 alvos de SET montados em lista (`f"t.{col} = "`, `f"t.{c} = s.{c}"`, `UPDATE SET t.{p.campo}`, `_COPIA_COLS`) perdem o `t.`;
- `CAST(current_date() AS STRING)` vira `current_date`;
- os 4 `CREATE TABLE IF NOT EXISTS {T_CFG}` e o `{T_CHOICE}` ganham `if not dialeto.PG:`, e `_migrate_analistas_cols` ganha o mesmo retorno dos `_ensure_*`;
- no `egps_atualizados.py`, `register` passa a receber `ator` e `agora`, e o main passa `ator=_ator, agora=AGORA`.

O resultado de referência (15/10) é este diff. Se o `main.py` tiver andado, refaça pelo tradutor e confira pelos guardas.

```diff
--- a/egps_analysis/app/backend/main.py
+++ b/egps_analysis/app/backend/main.py
@@ -737,6 +737,24 @@ def sql_lit(v):
     return dialeto.lit(v)
 
 
+# Quando e quem gravam, nos dois bancos (Fase 2, ADR 0005). No Databricks o SQL é o de sempre.
+# Postgres: `localtimestamp` (timestamp sem fuso; a sessão está em UTC), que numa coluna texto
+# sai no formato do Spark ('2026-10-15 19:27:07.090031') — current_timestamp levaria '+00'.
+AGORA = "localtimestamp" if dialeto.PG else "current_timestamp()"
+
+
+def _ator():
+    """Quem grava, como expressão SQL. Databricks: current_user() — a consulta roda como o
+    usuário (OBO). Postgres: o e-mail que o middleware conferiu (cabeçalho do ALB ou
+    DEV_USUARIO), como literal; sem ele não há escrita."""
+    if not dialeto.PG:
+        return "current_user()"
+    email = _usuario_email.get()
+    if not email:
+        raise HTTPException(401, "Login ausente ou inválido — recarregue a página.")
+    return sql_lit(email)
+
+
 def _lista_tem_algum(lista_sql, valores):
     """SQL: a lista em texto `lista_sql` ('a | b | c') tem algum dos `valores`, item a item e
     sem os espaços das pontas. Roda igual no Spark e no Postgres: sem lambda (`x -> trim(x)`)
@@ -942,6 +960,8 @@ def _require_admin():
 def _migrate_analistas_cols():
     """Colunas do organograma (add-once por processo): organograma (aparece na aba Home) e
     papel (rótulo do cargo; o grupo é derivado dele no frontend)."""
+    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
+        return True
     for col, typ in (("organograma", "BOOLEAN"), ("papel", "STRING")):
         try:
             run_sql(f"SELECT {col} FROM {T_ANALISTAS} LIMIT 0")
@@ -1032,14 +1052,14 @@ def responsaveis_bv_upsert(r: ResponsavelBv):
     run_sql(
         f"MERGE INTO {T_RESPBV} t USING (SELECT {sql_lit(key)} AS nome_key) s "
         f"ON t.nome_key = s.nome_key "
-        f"WHEN MATCHED THEN UPDATE SET t.nome = {sql_lit(nome)}, "
-        f"t.subarea = coalesce({sub_upd}, t.subarea), "
-        f"t.ativo = coalesce({ativo_upd}, t.ativo), "
-        f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET nome = {sql_lit(nome)}, "
+        f"subarea = coalesce({sub_upd}, t.subarea), "
+        f"ativo = coalesce({ativo_upd}, t.ativo), "
+        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (nome_key, nome, subarea, ativo, created_by, created_at, "
         f"updated_by, updated_at) VALUES ({sql_lit(key)}, {sql_lit(nome)}, {sub_ins}, {ativo_ins}, "
-        f"current_user(), cast(current_timestamp() AS STRING), current_user(), "
-        f"cast(current_timestamp() AS STRING))",
+        f"{_ator()}, cast({AGORA} AS STRING), {_ator()}, "
+        f"cast({AGORA} AS STRING))",
         want_rows=False)
     return {"ok": True, "nome_key": key, "nome": nome}
 
@@ -1205,7 +1225,7 @@ def analistas_upsert(a: Analista):
                               f"WHERE email = {sql_lit(legado)}")[0]["n"])
         if tem_leg and not tem_canon:
             run_sql(f"UPDATE {T_ANALISTAS} SET email = {sql_lit(email)}, "
-                    f"updated_by = current_user(), updated_at = cast(current_timestamp() AS STRING) "
+                    f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
                     f"WHERE email = {sql_lit(legado)}", want_rows=False)
         elif tem_leg and tem_canon:
             run_sql(f"DELETE FROM {T_ANALISTAS} WHERE email = {sql_lit(legado)}", want_rows=False)
@@ -1221,13 +1241,13 @@ def analistas_upsert(a: Analista):
     papel_lit = "NULL" if a.papel is None else sql_lit(a.papel.strip())
     run_sql(
         f"MERGE INTO {T_ANALISTAS} t USING (SELECT {sql_lit(email)} AS email) s ON t.email = s.email "
-        f"WHEN MATCHED THEN UPDATE SET t.nome = coalesce({nome_upd}, t.nome), "
-        f"t.ativo = coalesce({ativo_upd}, t.ativo), "
-        f"t.organograma = coalesce({org_upd}, t.organograma), t.papel = coalesce({papel_lit}, t.papel), "
-        f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET nome = coalesce({nome_upd}, t.nome), "
+        f"ativo = coalesce({ativo_upd}, t.ativo), "
+        f"organograma = coalesce({org_upd}, t.organograma), papel = coalesce({papel_lit}, t.papel), "
+        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (email, nome, ativo, organograma, papel, created_by, created_at, updated_by, updated_at) "
-        f"VALUES ({sql_lit(email)}, {sql_lit(nome_ins)}, {ativo_ins}, {org_ins}, {papel_lit}, current_user(), "
-        f"cast(current_timestamp() AS STRING), current_user(), cast(current_timestamp() AS STRING))",
+        f"VALUES ({sql_lit(email)}, {sql_lit(nome_ins)}, {ativo_ins}, {org_ins}, {papel_lit}, {_ator()}, "
+        f"cast({AGORA} AS STRING), {_ator()}, cast({AGORA} AS STRING))",
         want_rows=False)
     return {"ok": True, "email": email, "nome": nome_ins}
 
@@ -1637,9 +1605,10 @@ def _sanitizacao_derivada():
 SAN_LOG_CHAVE = "san_contadores"
 # Saída de emergência do log, sem redeploy do resto: desligar NÃO muda nenhum número
 # da fila (é o critério de aceite do ticket 15, e test_desligar_o_log_nao_muda_*).
-# Na AWS (ADR 0005, Fase 1) o app só lê: quem grava o log é o app do Databricks.
+# Na AWS em modo leitura (ADR 0005, Fase 1) quem grava o log é o app do Databricks; com a
+# escrita ligada (Fase 2, o espelho é a fonte) o Postgres grava, senão a série para na virada.
 _SAN_LOG_ON = (os.environ.get("SAN_LOG_DIARIO", "1").strip().lower() not in ("0", "false", "no")
-               and not dialeto.PG)
+               and not (dialeto.PG and SOMENTE_LEITURA))
 _san_log_dia = None   # dia já gravado por ESTE processo (a escrita é idempotente por data)
 
 
@@ -1707,15 +1676,16 @@ def _log_san_contadores(motivos, n_frageis):
     chave = f"{SAN_LOG_CHAVE}::{hoje}"            # divergir se o dia virar no meio
     valor = json.dumps(sanitizacao.contadores(motivos, n_frageis, hoje),
                        ensure_ascii=False, sort_keys=True)
-    run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
-            f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)",
-            want_rows=False)
+    if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
+        run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
+                f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)",
+                want_rows=False)
     run_sql(
         f"MERGE INTO {T_CFG} t USING (SELECT {sql_lit(chave)} AS chave) s "
         f"ON t.chave = s.chave "
         f"WHEN NOT MATCHED THEN INSERT (chave, valor, updated_by, updated_at) VALUES "
-        f"({sql_lit(chave)}, {sql_lit(valor)}, current_user(), "
-        f"cast(current_timestamp() AS STRING))", want_rows=False)
+        f"({sql_lit(chave)}, {sql_lit(valor)}, {_ator()}, "
+        f"cast({AGORA} AS STRING))", want_rows=False)
     _san_log_dia = hoje   # só depois do MERGE: falha deixa a próxima leitura tentar de novo
 
 
@@ -2851,19 +2821,19 @@ def patch_familia_ingestao(p: FamiliaIngestao):
         run_sql(
             f"MERGE INTO {T_ING} t USING (SELECT {sql_lit(p.categoria)} AS categoria, "
             f"{sql_lit(p.familia)} AS familia, {sql_lit(desde)} AS desde, "
-            f"coalesce({sql_lit(ing_em)}, CAST(current_date() AS STRING)) AS ingerida_em) s "
+            f"coalesce({sql_lit(ing_em)}, CAST(current_date AS STRING)) AS ingerida_em) s "
             f"ON t.categoria = s.categoria AND t.familia = s.familia "
-            f"WHEN MATCHED THEN UPDATE SET t.desde = s.desde, t.ingerida_em = s.ingerida_em, "
-            f"t.updated_by = current_user(), t.updated_at = current_timestamp() "
+            f"WHEN MATCHED THEN UPDATE SET desde = s.desde, ingerida_em = s.ingerida_em, "
+            f"updated_by = {_ator()}, updated_at = {AGORA} "
             f"WHEN NOT MATCHED THEN INSERT (categoria, familia, desde, ingerida_em, "
             f"updated_by, updated_at) VALUES (s.categoria, s.familia, s.desde, s.ingerida_em, "
-            f"current_user(), current_timestamp())", want_rows=False)
+            f"{_ator()}, {AGORA})", want_rows=False)
     else:
         run_sql(f"DELETE FROM {T_ING} WHERE {where}", want_rows=False)
     run_sql(f"INSERT INTO {T_ING_AUD} (id, categoria, familia, campo, valor_antigo, "
             f"valor_novo, ator, ts) VALUES ({sql_lit(uuid.uuid4().hex)}, "
             f"{sql_lit(p.categoria)}, {sql_lit(p.familia)}, 'desde', {sql_lit(antigo)}, "
-            f"{sql_lit(desde or '')}, current_user(), current_timestamp())", want_rows=False)
+            f"{sql_lit(desde or '')}, {_ator()}, {AGORA})", want_rows=False)
     _bump_gen()
     return {"ok": True, "categoria": p.categoria, "familia": p.familia, "desde": desde,
             "ingerida_em": ing_em}
@@ -3195,17 +3165,17 @@ def output_pipeline_patch(p: OutputPipe):
     run_sql(
         f"MERGE INTO {T_OUT_PIPE} t USING (SELECT {sql_lit(p.chave_canonica)} AS chave_canonica) s "
         f"ON t.chave_canonica = s.chave_canonica "
-        f"WHEN MATCHED THEN UPDATE SET t.recebido = {sql_lit(rec_new)}, t.recebido_data = {sql_lit(data_new)}, "
-        f"t.carga_fria = {sql_lit(cf_new)}, t.cf_etapa = {sql_lit(etapa_new)}, "
-        f"t.cf_status = {sql_lit(status_new)}, t.cf_responsavel = {sql_lit(resp_new)}, "
-        f"t.cf_inicio = {sql_lit(ini_new)}, t.cf_fim = {sql_lit(fim_new)}, t.cf_caminho = {sql_lit(cam_new)}, t.cf_tabela = {sql_lit(tab_new)}, "
-        f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET recebido = {sql_lit(rec_new)}, recebido_data = {sql_lit(data_new)}, "
+        f"carga_fria = {sql_lit(cf_new)}, cf_etapa = {sql_lit(etapa_new)}, "
+        f"cf_status = {sql_lit(status_new)}, cf_responsavel = {sql_lit(resp_new)}, "
+        f"cf_inicio = {sql_lit(ini_new)}, cf_fim = {sql_lit(fim_new)}, cf_caminho = {sql_lit(cam_new)}, cf_tabela = {sql_lit(tab_new)}, "
+        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (chave_canonica, recebido, recebido_data, carga_fria, cf_etapa, "
         f"cf_status, cf_responsavel, cf_inicio, cf_fim, cf_caminho, cf_tabela, updated_by, updated_at) "
         f"VALUES ({sql_lit(p.chave_canonica)}, {sql_lit(rec_new)}, {sql_lit(data_new)}, {sql_lit(cf_new)}, "
         f"{sql_lit(etapa_new)}, {sql_lit(status_new)}, {sql_lit(resp_new)}, "
-        f"{sql_lit(ini_new)}, {sql_lit(fim_new)}, {sql_lit(cam_new)}, {sql_lit(tab_new)}, current_user(), "
-        f"cast(current_timestamp() AS STRING))", want_rows=False)
+        f"{sql_lit(ini_new)}, {sql_lit(fim_new)}, {sql_lit(cam_new)}, {sql_lit(tab_new)}, {_ator()}, "
+        f"cast({AGORA} AS STRING))", want_rows=False)
     _bump_gen()   # T_OUT_PIPE alimenta n_outputs_disp da aba EGPs
     return {"ok": True, "chave_canonica": p.chave_canonica,
             "recebido": rec_new == "true", "recebido_data": data_new,
@@ -3231,11 +3201,12 @@ def set_output_producer(p: OutputProducer):
         f"SELECT DISTINCT projeto FROM {T_EGP_OUT} WHERE chave_canonica = {sql_lit(chave)}")}
     if proj not in prods:
         raise HTTPException(400, f'"{proj}" nao e produtor de {chave}')
-    run_sql(f"CREATE TABLE IF NOT EXISTS {T_CHOICE} (chave_canonica STRING, projeto_escolhido STRING, "
-            f"chosen_by STRING, chosen_at STRING) USING DELTA", want_rows=False)
+    if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
+        run_sql(f"CREATE TABLE IF NOT EXISTS {T_CHOICE} (chave_canonica STRING, projeto_escolhido STRING, "
+                f"chosen_by STRING, chosen_at STRING) USING DELTA", want_rows=False)
     run_sql(f"DELETE FROM {T_CHOICE} WHERE chave_canonica = {sql_lit(chave)}", want_rows=False)
     run_sql(f"INSERT INTO {T_CHOICE} (chave_canonica, projeto_escolhido, chosen_by, chosen_at) "
-            f"VALUES ({sql_lit(chave)}, {sql_lit(proj)}, current_user(), cast(current_timestamp() AS STRING))",
+            f"VALUES ({sql_lit(chave)}, {sql_lit(proj)}, {_ator()}, cast({AGORA} AS STRING))",
             want_rows=False)
     _lineage_gen += 1
     _lineage_cache.clear()
@@ -3335,13 +3306,13 @@ def _patch_familia(p, cat, nome):
     if not audits:
         raise HTTPException(400, "nada para atualizar (todas as safras já têm esses valores)")
     sets = [f"{c} = {sql_lit(v)}" for c, v in novos.items() if enviados[c]]
-    sets += ["updated_at = current_timestamp()", "updated_by = current_user()"]
+    sets += [f"updated_at = {AGORA}", f"updated_by = {_ator()}"]
     chaves_in = ", ".join(sql_lit(m["chave_canonica"]) for m in alvo)
     run_sql(f"UPDATE {T_IN} SET {', '.join(sets)} "
             f"WHERE chave_canonica IN ({chaves_in})", want_rows=False)
     vals = ",\n".join(
         f"({sql_lit(ch)}, {sql_lit(c)}, {sql_lit(va)}, {sql_lit(vn)}, "
-        f"current_user(), current_timestamp())" for ch, c, va, vn in audits)
+        f"{_ator()}, {AGORA})" for ch, c, va, vn in audits)
     run_sql(f"INSERT INTO {T_AUD} (chave_canonica, campo, valor_antigo, valor_novo, "
             f"updated_by, updated_at) VALUES\n{vals}", want_rows=False)
     # devolve a LINHA DE FAMÍLIA recalculada (o front faz merge por chave): reagrega os
@@ -3421,14 +3392,14 @@ def patch_input(p: Patch):
         audits.append((campo, _norm(old.get(campo)), _norm(novo)))
     if not sets:
         raise HTTPException(400, "nada para atualizar (valores idênticos)")
-    sets.append("updated_at = current_timestamp()")
-    sets.append("updated_by = current_user()")
+    sets.append(f"updated_at = {AGORA}")
+    sets.append(f"updated_by = {_ator()}")
     run_sql(f"UPDATE {T_IN} SET {', '.join(sets)} WHERE chave_canonica = {sql_lit(p.chave_canonica)}",
             want_rows=False)
     if audits:
         vals = ",\n".join(
             f"({sql_lit(p.chave_canonica)}, {sql_lit(c)}, {sql_lit(va)}, {sql_lit(vn)}, "
-            f"current_user(), current_timestamp())" for c, va, vn in audits)
+            f"{_ator()}, {AGORA})" for c, va, vn in audits)
         run_sql(f"INSERT INTO {T_AUD} (chave_canonica, campo, valor_antigo, valor_novo, "
                 f"updated_by, updated_at) VALUES\n{vals}", want_rows=False)
     # edit humano mudou T_IN (etapa/status/responsavel/observacao) -> invalida o cache do
@@ -3509,18 +3480,18 @@ def patch_familia_periodo(p: FamiliaPeriodo):
             f"{sql_lit(tipo)} AS tipo, {sql_lit(valor)} AS valor) s "
             f"ON t.projeto = s.projeto AND t.categoria = s.categoria "
             f"AND t.familia = s.familia "
-            f"WHEN MATCHED THEN UPDATE SET t.tipo = s.tipo, t.valor = s.valor, "
-            f"t.updated_by = current_user(), t.updated_at = current_timestamp() "
+            f"WHEN MATCHED THEN UPDATE SET tipo = s.tipo, valor = s.valor, "
+            f"updated_by = {_ator()}, updated_at = {AGORA} "
             f"WHEN NOT MATCHED THEN INSERT (projeto, categoria, familia, tipo, valor, "
             f"updated_by, updated_at) VALUES (s.projeto, s.categoria, s.familia, s.tipo, "
-            f"s.valor, current_user(), current_timestamp())", want_rows=False)
+            f"s.valor, {_ator()}, {AGORA})", want_rows=False)
     else:
         run_sql(f"DELETE FROM {T_PER} WHERE {where}", want_rows=False)
     run_sql(f"INSERT INTO {T_PER_AUD} (id, projeto, categoria, familia, campo, "
             f"valor_antigo, valor_novo, ator, ts) VALUES ({sql_lit(uuid.uuid4().hex)}, "
             f"{sql_lit(p.projeto)}, {sql_lit(p.categoria)}, {sql_lit(p.familia)}, "
-            f"'periodo', {sql_lit(antigo)}, {sql_lit(novo)}, current_user(), "
-            f"current_timestamp())", want_rows=False)
+            f"'periodo', {sql_lit(antigo)}, {sql_lit(novo)}, {_ator()}, "
+            f"{AGORA})", want_rows=False)
     _bump_gen()   # invalida o cache do declarado (e o payload do detalhe)
     return {"ok": True, "projeto": p.projeto, "categoria": p.categoria,
             "familia": p.familia, "tipo": tipo or None, "valor": valor,
@@ -3550,11 +3521,11 @@ def _link_escreve(projeto, chave, novo):
             f"MERGE INTO {T_LINK} t USING (SELECT {sql_lit(projeto)} AS projeto, "
             f"{sql_lit(chave)} AS chave_canonica) s "
             f"ON t.projeto = s.projeto AND t.chave_canonica = s.chave_canonica "
-            f"WHEN MATCHED THEN UPDATE SET t.link_broken = true, "
-            f"t.updated_by = current_user(), t.updated_at = current_timestamp() "
+            f"WHEN MATCHED THEN UPDATE SET link_broken = true, "
+            f"updated_by = {_ator()}, updated_at = {AGORA} "
             f"WHEN NOT MATCHED THEN INSERT (projeto, chave_canonica, link_broken, "
             f"updated_by, updated_at) VALUES ({sql_lit(projeto)}, "
-            f"{sql_lit(chave)}, true, current_user(), current_timestamp())",
+            f"{sql_lit(chave)}, true, {_ator()}, {AGORA})",
             want_rows=False)
     else:
         run_sql(
@@ -3564,8 +3535,8 @@ def _link_escreve(projeto, chave, novo):
         f"INSERT INTO {T_LINK_AUD} (id, projeto, chave_canonica, campo, valor_antigo, "
         f"valor_novo, ator, ts) VALUES ({sql_lit(uuid.uuid4().hex)}, "
         f"{sql_lit(projeto)}, {sql_lit(chave)}, 'link_broken', "
-        f"{sql_lit(_norm(old))}, {sql_lit(_norm(novo))}, current_user(), "
-        f"current_timestamp())", want_rows=False)
+        f"{sql_lit(_norm(old))}, {sql_lit(_norm(novo))}, {_ator()}, "
+        f"{AGORA})", want_rows=False)
     return True
 
 
@@ -3633,11 +3604,11 @@ def _depm_escreve(projeto, chave, novo, motivo=None):
             f"MERGE INTO {T_DEPM} t USING (SELECT {sql_lit(projeto)} AS projeto, "
             f"{sql_lit(chave)} AS chave_canonica) s "
             f"ON t.projeto = s.projeto AND t.chave_canonica = s.chave_canonica "
-            f"WHEN MATCHED THEN UPDATE SET t.motivo = {sql_lit(motivo)}, "
-            f"t.updated_by = current_user(), t.updated_at = current_timestamp() "
+            f"WHEN MATCHED THEN UPDATE SET motivo = {sql_lit(motivo)}, "
+            f"updated_by = {_ator()}, updated_at = {AGORA} "
             f"WHEN NOT MATCHED THEN INSERT (projeto, chave_canonica, motivo, updated_by, "
             f"updated_at) VALUES ({sql_lit(projeto)}, {sql_lit(chave)}, "
-            f"{sql_lit(motivo)}, current_user(), current_timestamp())", want_rows=False)
+            f"{sql_lit(motivo)}, {_ator()}, {AGORA})", want_rows=False)
     else:
         run_sql(f"DELETE FROM {T_DEPM} WHERE projeto = {sql_lit(projeto)} "
                 f"AND chave_canonica = {sql_lit(chave)}", want_rows=False)
@@ -3645,7 +3616,7 @@ def _depm_escreve(projeto, chave, novo, motivo=None):
         f"INSERT INTO {T_DEPM_AUD} (id, projeto, chave_canonica, campo, valor_antigo, "
         f"valor_novo, ator, ts) VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(projeto)}, "
         f"{sql_lit(chave)}, 'dep_mantida', {sql_lit('true' if old else 'false')}, "
-        f"{sql_lit('true' if novo else 'false')}, current_user(), current_timestamp())",
+        f"{sql_lit('true' if novo else 'false')}, {_ator()}, {AGORA})",
         want_rows=False)
     return True
 
@@ -4410,7 +4381,7 @@ def _esc_audit(acao, egp, projeto):
     run_sql(
         f"INSERT INTO {T_ESC_AUD} (id, acao, egp_dor1, projeto, ator, ts) VALUES "
         f"({sql_lit(uuid.uuid4().hex)}, {sql_lit(acao)}, {sql_lit(egp)}, {sql_lit(projeto)}, "
-        f"current_user(), cast(current_timestamp() AS STRING))", want_rows=False)
+        f"{_ator()}, cast({AGORA} AS STRING))", want_rows=False)
 
 
 _escopo_ativo_ok = False
@@ -4577,7 +4548,7 @@ def escopo_add(p: EscopoAdd):
     run_sql(
         f"INSERT INTO {T_ESC} (id, egp_dor1, area, status_extracao, projeto, origem, ativo, created_by, created_at) "
         f"VALUES ({sql_lit(rid)}, {sql_lit(egp)}, {sql_lit(area)}, {sql_lit(classif)}, {sql_lit(projeto)}, "
-        f"'manual', true, current_user(), cast(current_timestamp() AS STRING))", want_rows=False)
+        f"'manual', true, {_ator()}, cast({AGORA} AS STRING))", want_rows=False)
     _esc_audit("add", egp, projeto)
     recompute_escopo()
     return {"ok": True, "id": rid}
@@ -5141,21 +5112,22 @@ def _grava_egps_novos(lista, antes):
     preenchidos (a linha semeada por script em 29/09 deixou os dois NULL — ver ticket 24)
     e um evento em `sas_pipeline_audit` no projeto sentinela `'(config)'`."""
     novo_json = json.dumps(sorted(set(lista)), ensure_ascii=False)
-    run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
-            f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)",
-            want_rows=False)
+    if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
+        run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
+                f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)",
+                want_rows=False)
     run_sql(
         f"MERGE INTO {T_CFG} t USING (SELECT 'egps_novos' AS chave) s ON t.chave = s.chave "
-        f"WHEN MATCHED THEN UPDATE SET t.valor = {sql_lit(novo_json)}, "
-        f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET valor = {sql_lit(novo_json)}, "
+        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (chave, valor, updated_by, updated_at) VALUES "
-        f"('egps_novos', {sql_lit(novo_json)}, current_user(), "
-        f"cast(current_timestamp() AS STRING))", want_rows=False)
+        f"('egps_novos', {sql_lit(novo_json)}, {_ator()}, "
+        f"cast({AGORA} AS STRING))", want_rows=False)
     run_sql(
         f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
         f"VALUES ({sql_lit(uuid.uuid4().hex)}, '(config)', 'migracao', 'egps_novos', "
         f"{sql_lit(json.dumps(sorted(set(antes)), ensure_ascii=False))}, {sql_lit(novo_json)}, "
-        f"current_user(), cast(current_timestamp() AS STRING))", want_rows=False)
+        f"{_ator()}, cast({AGORA} AS STRING))", want_rows=False)
     # A declaração muda quem é extra, e extra entra no frontier: sem bump, o contador
     # "(+N extra)" e a aba EGPs seguiriam servindo a geração anterior.
     _bump_gen()
@@ -6074,17 +6046,17 @@ def _copia_trabalho_para_sucessor(sucessor: str, origem: dict):
     run_sql(
         f"MERGE INTO {T_PIPE} t USING (SELECT {sql_lit(sucessor)} AS projeto) s ON t.projeto = s.projeto "
         f"WHEN MATCHED THEN UPDATE SET "
-        + ", ".join(f"t.{_COPIA_COLS[c]} = {lits[c]}" for c in campos)
-        + f", t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+        + ", ".join(f"{_COPIA_COLS[c]} = {lits[c]}" for c in campos)
+        + f", updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (projeto, {', '.join(cols)}, updated_by, updated_at) "
-        f"VALUES ({sql_lit(sucessor)}, {', '.join(lits[c] for c in campos)}, current_user(), "
-        f"cast(current_timestamp() AS STRING))", want_rows=False)
+        f"VALUES ({sql_lit(sucessor)}, {', '.join(lits[c] for c in campos)}, {_ator()}, "
+        f"cast({AGORA} AS STRING))", want_rows=False)
     for campo, valor in campos.items():
         run_sql(
             f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
             f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(sucessor)}, 'migracao', "
             f"{sql_lit(_COPIA_COLS[campo])}, {sql_lit(_norm(destino.get(campo)))}, "
-            f"{sql_lit(_norm(valor))}, current_user(), cast(current_timestamp() AS STRING))",
+            f"{sql_lit(_norm(valor))}, {_ator()}, cast({AGORA} AS STRING))",
             want_rows=False)
     return campos
 
@@ -6179,18 +6151,18 @@ def egp_pipeline(p: EgpPipe):
              ("egp_atualizado_key", atukey_new, p.egp_atualizado_key),
              ("egp_vinculo_tipo", tipo_new, p.egp_vinculo_tipo),
              ("egp_sucessor", suc_new, p.egp_sucessor)]
-    set_sql = "".join(f"t.{col} = {sql_lit(val)}, " for col, val, enviado in _sets
+    set_sql = "".join(f"{col} = {sql_lit(val)}, " for col, val, enviado in _sets
                       if enviado is not None)
     run_sql(
         f"MERGE INTO {T_PIPE} t USING (SELECT {sql_lit(p.projeto)} AS projeto) s ON t.projeto = s.projeto "
         f"WHEN MATCHED THEN UPDATE SET {set_sql}"
-        f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (projeto, {et_col}, {st_col}, responsavel, responsavel_bv, jira_id, "
         f"preworking_preenchido, preworking_data, egp_atualizado_key, egp_vinculo_tipo, "
         f"egp_sucessor, updated_by, updated_at) VALUES "
         f"({sql_lit(p.projeto)}, {sql_lit(et_new)}, {sql_lit(st_new)}, {sql_lit(resp_new)}, {sql_lit(respbv_new)}, {sql_lit(jira_new)}, "
         f"{sql_lit(pw_new)}, {sql_lit(pwdata_new)}, {sql_lit(atukey_new)}, {sql_lit(tipo_new)}, "
-        f"{sql_lit(suc_new)}, current_user(), cast(current_timestamp() AS STRING))", want_rows=False)
+        f"{sql_lit(suc_new)}, {_ator()}, cast({AGORA} AS STRING))", want_rows=False)
     audits = []
     if p.etapa is not None and _norm(p.etapa) != _norm(old.get("et")):
         audits.append(("etapa", _norm(old.get("et")), _norm(p.etapa)))
@@ -6216,8 +6188,8 @@ def egp_pipeline(p: EgpPipe):
         run_sql(
             f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
             f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(p.projeto)}, {sql_lit(p.funil)}, "
-            f"{sql_lit(campo)}, {sql_lit(va)}, {sql_lit(vn)}, current_user(), "
-            f"cast(current_timestamp() AS STRING))", want_rows=False)
+            f"{sql_lit(campo)}, {sql_lit(va)}, {sql_lit(vn)}, {_ator()}, "
+            f"cast({AGORA} AS STRING))", want_rows=False)
     # No ATO do vínculo o trabalho de gestão vai junto para o sucessor (§3.3.11). Depois do
     # MERGE acima: a etapa copiada é a que o antecessor acabou de ficar.
     if vinculos.vinculo_criado_agora(tipo_new, suc_new, old.get("vinc_tipo"), old.get("sucessor")):
@@ -8129,17 +8101,17 @@ def _read_prio_snapshot():
 
 def _write_prio_snapshot(payload, saved_by_expr, sp=False):
     """Grava/atualiza o snapshot vigente. saved_by_expr = expressão SQL ('auto' no seed via
-    SP; current_user() no save do admin). sp=True escreve como SP (seed sem depender do
+    SP; _ator() no save do admin). sp=True escreve como SP (seed sem depender do
     privilégio do leitor)."""
     run = _run_sp if sp else run_sql
     _ensure_prio_snapshot_table(sp=sp)
     pj = sql_lit(json.dumps(payload, ensure_ascii=False))                   # payload congelado inteiro
     cap = int(payload.get("capacidade") or 0)
     run(f"MERGE INTO {T_PRIO_SNAP} t USING (SELECT 'current' AS id) s ON t.id = s.id "
-        f"WHEN MATCHED THEN UPDATE SET t.payload = {pj}, t.capacidade = {cap}, "
-        f"t.saved_by = {saved_by_expr}, t.saved_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET payload = {pj}, capacidade = {cap}, "
+        f"saved_by = {saved_by_expr}, saved_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (id, payload, capacidade, saved_by, saved_at) VALUES "
-        f"('current', {pj}, {cap}, {saved_by_expr}, cast(current_timestamp() AS STRING))",
+        f"('current', {pj}, {cap}, {saved_by_expr}, cast({AGORA} AS STRING))",
         want_rows=False)
 
 
@@ -8212,7 +8184,7 @@ def priorizacao(scope: str = "indi", area: str = "", deps: str = "transitive", c
     if snap is not None:
         return _com_extras(_poda_fora_da_linha_base(snap))
     payload = _compute_priorizacao(scope, area, deps, capacidade)
-    if dialeto.PG:   # Fase 1 na AWS só lê (ADR 0005): quem congela o plano é o Databricks
+    if dialeto.PG and SOMENTE_LEITURA:   # AWS em modo leitura (Fase 1): quem congela é o Databricks
         return _com_extras({**payload, "snapshot": None})
     try:
         _write_prio_snapshot(payload, "'auto'", sp=True)
@@ -8242,16 +8214,16 @@ def _persist_pins(pins):
         old = cur[0].get("mp") if cur else None
         run_sql(
             f"MERGE INTO {T_PIPE} t USING (SELECT {sql_lit(pj)} AS projeto) s ON t.projeto = s.projeto "
-            f"WHEN MATCHED THEN UPDATE SET t.mes_prioridade = {mes_lit}, "
-            f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+            f"WHEN MATCHED THEN UPDATE SET mes_prioridade = {mes_lit}, "
+            f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
             f"WHEN NOT MATCHED THEN INSERT (projeto, mes_prioridade, updated_by, updated_at) VALUES "
-            f"({sql_lit(pj)}, {mes_lit}, current_user(), cast(current_timestamp() AS STRING))",
+            f"({sql_lit(pj)}, {mes_lit}, {_ator()}, cast({AGORA} AS STRING))",
             want_rows=False)
         if _norm(old) != _norm(mv):
             run_sql(
                 f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
                 f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(pj)}, 'migracao', 'mes_prioridade', "
-                f"{sql_lit(_norm(old))}, {sql_lit(_norm(mv))}, current_user(), cast(current_timestamp() AS STRING))",
+                f"{sql_lit(_norm(old))}, {sql_lit(_norm(mv))}, {_ator()}, cast({AGORA} AS STRING))",
                 want_rows=False)
 
 
@@ -8271,29 +8243,30 @@ def priorizacao_save_snapshot(edits: PrioEdits = PrioEdits()):
     cap = 0
     if edits.capacidade and 1 <= edits.capacidade <= 10000:
         old_cap = _prio_capacidade()
-        run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
-                f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)", want_rows=False)
+        if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
+            run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
+                    f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)", want_rows=False)
         run_sql(
             f"MERGE INTO {T_CFG} t USING (SELECT 'prio_capacidade' AS chave) s ON t.chave = s.chave "
-            f"WHEN MATCHED THEN UPDATE SET t.valor = {sql_lit(str(edits.capacidade))}, "
-            f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+            f"WHEN MATCHED THEN UPDATE SET valor = {sql_lit(str(edits.capacidade))}, "
+            f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
             f"WHEN NOT MATCHED THEN INSERT (chave, valor, updated_by, updated_at) VALUES "
-            f"('prio_capacidade', {sql_lit(str(edits.capacidade))}, current_user(), cast(current_timestamp() AS STRING))",
+            f"('prio_capacidade', {sql_lit(str(edits.capacidade))}, {_ator()}, cast({AGORA} AS STRING))",
             want_rows=False)
         if old_cap != edits.capacidade:   # auditoria (aba Histórico, fonte 'EGPs')
             run_sql(
                 f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
                 f"VALUES ({sql_lit(uuid.uuid4().hex)}, '(config)', 'migracao', 'capacidade_mes', "
-                f"{sql_lit(str(old_cap))}, {sql_lit(str(edits.capacidade))}, current_user(), cast(current_timestamp() AS STRING))",
+                f"{sql_lit(str(old_cap))}, {sql_lit(str(edits.capacidade))}, {_ator()}, cast({AGORA} AS STRING))",
                 want_rows=False)
         cap = edits.capacidade
     payload = _compute_priorizacao(capacidade=cap)   # pins/capacidade já persistidos -> lê do DB
-    _write_prio_snapshot(payload, "current_user()", sp=False)
+    _write_prio_snapshot(payload, _ator(), sp=False)
     try:
         run_sql(
             f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
             f"VALUES ({sql_lit(uuid.uuid4().hex)}, '(config)', 'migracao', 'priorizacao_snapshot', "
-            f"'', cast(current_timestamp() AS STRING), current_user(), cast(current_timestamp() AS STRING))",
+            f"'', cast({AGORA} AS STRING), {_ator()}, cast({AGORA} AS STRING))",
             want_rows=False)
     except HTTPException:
         pass
@@ -8322,17 +8295,17 @@ def priorizacao_set_mes(p: PrioMesPin):
     mes_lit = "NULL" if p.mes is None else str(int(p.mes))
     run_sql(
         f"MERGE INTO {T_PIPE} t USING (SELECT {sql_lit(p.projeto)} AS projeto) s ON t.projeto = s.projeto "
-        f"WHEN MATCHED THEN UPDATE SET t.mes_prioridade = {mes_lit}, "
-        f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET mes_prioridade = {mes_lit}, "
+        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (projeto, mes_prioridade, updated_by, updated_at) VALUES "
-        f"({sql_lit(p.projeto)}, {mes_lit}, current_user(), cast(current_timestamp() AS STRING))",
+        f"({sql_lit(p.projeto)}, {mes_lit}, {_ator()}, cast({AGORA} AS STRING))",
         want_rows=False)
     if _norm(old) != _norm(p.mes):
         run_sql(
             f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
             f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(p.projeto)}, 'migracao', 'mes_prioridade', "
-            f"{sql_lit(_norm(old))}, {sql_lit(_norm(p.mes))}, current_user(), "
-            f"cast(current_timestamp() AS STRING))", want_rows=False)
+            f"{sql_lit(_norm(old))}, {sql_lit(_norm(p.mes))}, {_ator()}, "
+            f"cast({AGORA} AS STRING))", want_rows=False)
     return {"ok": True, "projeto": p.projeto, "mes": p.mes}
 
 
@@ -8352,22 +8325,23 @@ def priorizacao_set_capacidade(p: PrioCapacidade):
             or p.capacidade < 1 or p.capacidade > 10000:
         raise HTTPException(400, "capacidade deve ser inteiro entre 1 e 10000")
     old = _prio_capacidade()
-    run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
-            f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)",
-            want_rows=False)
+    if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
+        run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
+                f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)",
+                want_rows=False)
     run_sql(
         f"MERGE INTO {T_CFG} t USING (SELECT 'prio_capacidade' AS chave) s ON t.chave = s.chave "
-        f"WHEN MATCHED THEN UPDATE SET t.valor = {sql_lit(str(p.capacidade))}, "
-        f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET valor = {sql_lit(str(p.capacidade))}, "
+        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (chave, valor, updated_by, updated_at) VALUES "
-        f"('prio_capacidade', {sql_lit(str(p.capacidade))}, current_user(), "
-        f"cast(current_timestamp() AS STRING))", want_rows=False)
+        f"('prio_capacidade', {sql_lit(str(p.capacidade))}, {_ator()}, "
+        f"cast({AGORA} AS STRING))", want_rows=False)
     if old != p.capacidade:
         run_sql(
             f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
             f"VALUES ({sql_lit(uuid.uuid4().hex)}, '(config)', 'migracao', 'capacidade_mes', "
-            f"{sql_lit(str(old))}, {sql_lit(str(p.capacidade))}, current_user(), "
-            f"cast(current_timestamp() AS STRING))", want_rows=False)
+            f"{sql_lit(str(old))}, {sql_lit(str(p.capacidade))}, {_ator()}, "
+            f"cast({AGORA} AS STRING))", want_rows=False)
     return {"ok": True, "capacidade": p.capacidade}
 
 
@@ -9022,7 +8996,7 @@ def gestao_status_add(p: GestaoStatusNovo):
     run_sql(
         f"INSERT INTO {T_GST} (id, entity, entity_id, autor, criado_por, ts, texto) VALUES ("
         f"{sql_lit(sid)}, {sql_lit(p.entity)}, {sql_lit(p.id)}, {sql_lit(p.autor)}, "
-        f"current_user(), cast(current_timestamp() AS STRING), {sql_lit(p.texto)})",
+        f"{_ator()}, cast({AGORA} AS STRING), {sql_lit(p.texto)})",
         want_rows=False)
     _bump_gen()   # último status aparece na Gestão (payload cacheado)
     return {"ok": True, "id": sid}
@@ -9047,7 +9021,7 @@ def _bv_audit(entity_id, de, para):
     run_sql(
         f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
         f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(entity_id)}, 'gestao', 'ComBV', "
-        f"{sql_lit(de)}, {sql_lit(para)}, current_user(), cast(current_timestamp() AS STRING))",
+        f"{sql_lit(de)}, {sql_lit(para)}, {_ator()}, cast({AGORA} AS STRING))",
         want_rows=False)
 
 
@@ -9065,7 +9039,7 @@ def gestao_bv_add(p: GestaoBV):
     _ensure_gestao_tables()
     bid = uuid.uuid4().hex
     data_lit = (sql_lit(p.data) if p.data is not None else
-                "date_format(from_utc_timestamp(current_timestamp(), 'America/Sao_Paulo'), 'yyyy-MM-dd')")
+                f"date_format(from_utc_timestamp({AGORA}, 'America/Sao_Paulo'), 'yyyy-MM-dd')")
     # DE = predecessor CRONOLÓGICO exato do evento inserido ("-" se nenhum): o evento mais
     # recente com data <= data deste (desempate por ts — o novo é sempre o mais novo). Em
     # correção retroativa (data no passado) isso pega o vizinho anterior à data inserida, não o
@@ -9076,7 +9050,7 @@ def gestao_bv_add(p: GestaoBV):
     run_sql(
         f"INSERT INTO {T_GBV} (id, entity, entity_id, com_bv, data, autor, ts) VALUES ("
         f"{sql_lit(bid)}, {sql_lit(p.entity)}, {sql_lit(p.id)}, {str(p.comBv).lower()}, "
-        f"{data_lit}, current_user(), cast(current_timestamp() AS STRING))",
+        f"{data_lit}, {_ator()}, cast({AGORA} AS STRING))",
         want_rows=False)
     _bv_audit(p.id, _bv_label(prev[0]["com_bv"]) if prev else "-", _bv_label(p.comBv))
     _bump_gen()
@@ -9119,16 +9093,16 @@ def gestao_revisao(p: GestaoRevisao):
     run_sql(
         f"MERGE INTO {T_GRV} t USING (SELECT 'egp' AS entity, {sql_lit(p.id)} AS entity_id) s "
         f"ON t.entity = s.entity AND t.entity_id = s.entity_id "
-        f"WHEN MATCHED THEN UPDATE SET t.contador = {novo}, t.updated_by = current_user(), "
-        f"t.updated_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET contador = {novo}, updated_by = {_ator()}, "
+        f"updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (entity, entity_id, contador, updated_by, updated_at) "
-        f"VALUES (s.entity, s.entity_id, {novo}, current_user(), cast(current_timestamp() AS STRING))",
+        f"VALUES (s.entity, s.entity_id, {novo}, {_ator()}, cast({AGORA} AS STRING))",
         want_rows=False)
     run_sql(
         f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
         f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(p.id)}, 'gestao', 'RevisaoRegras', "
-        f"{sql_lit(str(old))}, {sql_lit(str(novo))}, current_user(), "
-        f"cast(current_timestamp() AS STRING))", want_rows=False)
+        f"{sql_lit(str(old))}, {sql_lit(str(novo))}, {_ator()}, "
+        f"cast({AGORA} AS STRING))", want_rows=False)
     _bump_gen()
     return {"ok": True, "contador": novo}
 
@@ -9163,17 +9137,17 @@ def gestao_set_data(p: GestaoData):
         f"MERGE INTO {T_GDT} t USING (SELECT {sql_lit(p.entity)} AS entity, "
         f"{sql_lit(p.id)} AS entity_id) s "
         f"ON t.entity = s.entity AND t.entity_id = s.entity_id "
-        f"WHEN MATCHED THEN UPDATE SET t.{p.campo} = {v_lit}, t.updated_by = current_user(), "
-        f"t.updated_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET {p.campo} = {v_lit}, updated_by = {_ator()}, "
+        f"updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (entity, entity_id, {p.campo}, updated_by, updated_at) "
-        f"VALUES (s.entity, s.entity_id, {v_lit}, current_user(), "
-        f"cast(current_timestamp() AS STRING))", want_rows=False)
+        f"VALUES (s.entity, s.entity_id, {v_lit}, {_ator()}, "
+        f"cast({AGORA} AS STRING))", want_rows=False)
     if old != (p.valor or None):
         run_sql(
             f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
             f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(p.id)}, 'gestao', {sql_lit(p.campo)}, "
-            f"{sql_lit(old or '')}, {sql_lit(p.valor or '')}, current_user(), "
-            f"cast(current_timestamp() AS STRING))", want_rows=False)
+            f"{sql_lit(old or '')}, {sql_lit(p.valor or '')}, {_ator()}, "
+            f"cast({AGORA} AS STRING))", want_rows=False)
     _bump_gen()   # fim_conversao/datas aparecem na aba EGPs e na Gestão (payloads cacheados)
     return {"ok": True}
 
@@ -9384,22 +9358,22 @@ def preworking_patch(p: PreworkingPatch):
     if not sets:
         raise HTTPException(400, "nada para atualizar (valores idênticos)")
     src_cols = ", ".join(f"{sql_lit(v)} AS {c}" for c, v in sets)
-    upd = ", ".join(f"t.{c} = s.{c}" for c, _ in sets)
+    upd = ", ".join(f"{c} = s.{c}" for c, _ in sets)
     ins_cols = ", ".join(c for c, _ in sets)
     ins_vals = ", ".join(f"s.{c}" for c, _ in sets)
     run_sql(
         f"MERGE INTO {T_PWK} t USING (SELECT {sql_lit(p.chave_canonica)} AS chave_canonica, "
         f"{src_cols}) s "
         f"ON t.chave_canonica = s.chave_canonica "
-        f"WHEN MATCHED THEN UPDATE SET {upd}, t.updated_by = current_user(), "
-        f"t.updated_at = cast(current_timestamp() AS STRING) "
+        f"WHEN MATCHED THEN UPDATE SET {upd}, updated_by = {_ator()}, "
+        f"updated_at = cast({AGORA} AS STRING) "
         f"WHEN NOT MATCHED THEN INSERT (chave_canonica, {ins_cols}, updated_by, updated_at, iniciado_em) "
-        f"VALUES (s.chave_canonica, {ins_vals}, current_user(), cast(current_timestamp() AS STRING), "
-        f"cast(current_timestamp() AS STRING))",
+        f"VALUES (s.chave_canonica, {ins_vals}, {_ator()}, cast({AGORA} AS STRING), "
+        f"cast({AGORA} AS STRING))",
         want_rows=False)
     vals = ",\n".join(
         f"({sql_lit(p.chave_canonica)}, {sql_lit('preworking.' + c)}, {sql_lit(va)}, "
-        f"{sql_lit(vn)}, current_user(), current_timestamp())" for c, va, vn in audits)
+        f"{sql_lit(vn)}, {_ator()}, {AGORA})" for c, va, vn in audits)
     run_sql(f"INSERT INTO {T_AUD} (chave_canonica, campo, valor_antigo, valor_novo, "
             f"updated_by, updated_at) VALUES\n{vals}", want_rows=False)
     result = dict(old)
@@ -9413,7 +9387,7 @@ def preworking_patch(p: PreworkingPatch):
     # partida conhecido, então gravar concluido_em nelas daria uma duração fabricada (a
     # data do próximo toque, não a data real de conclusão) — melhor deixar as 2 em branco.
     if _preworking_completo(result) and not old.get("concluido_em") and old.get("iniciado_em"):
-        run_sql(f"UPDATE {T_PWK} SET concluido_em = cast(current_timestamp() AS STRING) "
+        run_sql(f"UPDATE {T_PWK} SET concluido_em = cast({AGORA} AS STRING) "
                 f"WHERE chave_canonica = {sql_lit(p.chave_canonica)}", want_rows=False)
 
     # checklist 100% -> libera p/ Ingestão UAT (só avança; nunca rebaixa etapa já mais adiantada)
@@ -9440,16 +9414,16 @@ def preworking_patch(p: PreworkingPatch):
         if avancar:
             run_sql(
                 f"UPDATE {T_IN} SET etapa = {sql_lit('Ingestão UAT')}, status = {sql_lit('A Iniciar')}, "
-                f"updated_at = current_timestamp(), updated_by = current_user() "
+                f"updated_at = {AGORA}, updated_by = {_ator()} "
                 f"WHERE chave_canonica IN ({', '.join(sql_lit(k) for k, _, _ in avancar)})",
                 want_rows=False)
             run_sql(
                 f"INSERT INTO {T_AUD} (chave_canonica, campo, valor_antigo, valor_novo, "
                 f"updated_by, updated_at) VALUES " + ", ".join(
                     f"({sql_lit(k)}, 'etapa', {sql_lit(et or '')}, 'Ingestão UAT', "
-                    f"current_user(), current_timestamp()), "
+                    f"{_ator()}, {AGORA}), "
                     f"({sql_lit(k)}, 'status', {sql_lit(st or '')}, 'A Iniciar', "
-                    f"current_user(), current_timestamp())" for k, et, st in avancar),
+                    f"{_ator()}, {AGORA})" for k, et, st in avancar),
                 want_rows=False)
             auto_avancado = True
             _lineage_gen += 1
@@ -9542,7 +9516,7 @@ def prioridades_create(p: PrioIn):
         f"created_by, created_at, updated_by, updated_at) VALUES ("
         f"{sql_lit(pid)}, {ordem}, {sql_lit(projeto)}, {'true' if p.vinculado else 'false'}, "
         f"{sql_lit(p.status)}, {sql_lit(p.responsavel)}, {sql_lit(p.justificativa)}, "
-        f"current_user(), current_timestamp(), current_user(), current_timestamp())", want_rows=False)
+        f"{_ator()}, {AGORA}, {_ator()}, {AGORA})", want_rows=False)
     rows = run_sql(_PRIO_SELECT + f" WHERE p.id = {sql_lit(pid)}")
     if not rows:
         raise HTTPException(502, "falha ao criar a prioridade")
@@ -9573,8 +9547,8 @@ def prioridades_patch(pid: str, p: PrioPatch):
         sets.append(f"justificativa = {sql_lit(p.justificativa)}")
     if not sets:
         raise HTTPException(400, "nada para atualizar")
-    sets.append("updated_by = current_user()")
-    sets.append("updated_at = current_timestamp()")
+    sets.append(f"updated_by = {_ator()}")
+    sets.append(f"updated_at = {AGORA}")
     run_sql(f"UPDATE {T_PRIO} SET {', '.join(sets)} WHERE id = {sql_lit(pid)}", want_rows=False)
     rows = run_sql(_PRIO_SELECT + f" WHERE p.id = {sql_lit(pid)}")
     return _prio_out(rows[0])
@@ -9614,7 +9588,8 @@ egps_atualizados.register(
     http_exc=HTTPException,
     enrich_contexto=_enrich_egp_contexto,
     familia_por_chave=_familia_por_chave,
-    on_write=_bump_gen)
+    on_write=_bump_gen,
+    ator=_ator, agora=AGORA)
 
 
 # ---- consulta: o app grava o que calcula (ADR 0004) ----------------------------------
```

```diff
--- a/egps_analysis/app/backend/egps_atualizados.py
+++ b/egps_analysis/app/backend/egps_atualizados.py
@@ -185,7 +185,8 @@ def pendencias_fora(versoes, ja_listadas):
 
 
 def register(app, run_sql, fq: str, modern_expr: str, http_exc, enrich_contexto,
-             familia_por_chave=None, on_write=None):
+             familia_por_chave=None, on_write=None, ator=lambda: "current_user()",
+             agora="current_timestamp()"):
     """modern_expr: predicado SQL de "input resolvido" do main (_modern), renderizado
     sobre os aliases i (sas_inputs_monitor) e ma (agregado de modernizada_auto por
     chave). http_exc: classe HTTPException do FastAPI. enrich_contexto:
@@ -196,7 +197,9 @@ def register(app, run_sql, fq: str, modern_expr: str, http_exc, enrich_contexto,
     Ausente (ou flag desligada) => nenhum remapeamento, o link usa a chave física.
     on_write: chamado depois de cada escrita bem-sucedida — no main, `_bump_gen`. O
     payload de /api/egp-readiness (cacheado por geração lá) lê tipo_vinculo daqui; sem
-    o gancho, o rótulo ficava velho por até 5 min, inclusive para quem acabou de clicar."""
+    o gancho, o rótulo ficava velho por até 5 min, inclusive para quem acabou de clicar.
+    ator / agora: quem e quando gravam, em SQL (main._ator e main.AGORA — Fase 2, ADR 0005).
+    O padrão é o SQL do Databricks."""
     t_main = f"{fq}.sas_egp_atualizados"
     t_in = f"{fq}.sas_egp_atualizados_inputs"
     t_out = f"{fq}.sas_egp_atualizados_outputs"
@@ -419,7 +422,7 @@ def register(app, run_sql, fq: str, modern_expr: str, http_exc, enrich_contexto,
             run_sql(f"INSERT INTO {t_aud} (id, egp_key, campo, valor_antigo, valor_novo, "
                     f"autor, ts) SELECT uuid(), {_sql_str(egp_key)}, 'tipo_vinculo', "
                     f"{_sql_str(old) if old else 'NULL'}, "
-                    f"{_sql_str(tv) if tv else 'NULL'}, current_user(), current_timestamp()",
+                    f"{_sql_str(tv) if tv else 'NULL'}, {ator()}, {agora}",
                     want_rows=False)
         # MERGE, não DELETE+INSERT (mantido do original): o par deixava uma janela em que a
         # linha já tinha sido apagada e a nova ainda não existia; um timeout do warehouse
@@ -429,10 +432,10 @@ def register(app, run_sql, fq: str, modern_expr: str, http_exc, enrich_contexto,
             f"MERGE INTO {t_pipe} t USING (SELECT {_sql_str(egp_key)} AS egp_key, "
             f"{_sql_str(tv) if tv else 'CAST(NULL AS STRING)'} AS tipo_vinculo) s "
             f"ON t.egp_key = s.egp_key "
-            f"WHEN MATCHED THEN UPDATE SET t.tipo_vinculo = s.tipo_vinculo, "
-            f"t.updated_by = current_user(), t.updated_at = current_timestamp() "
+            f"WHEN MATCHED THEN UPDATE SET tipo_vinculo = s.tipo_vinculo, "
+            f"updated_by = {ator()}, updated_at = {agora} "
             f"WHEN NOT MATCHED THEN INSERT (egp_key, tipo_vinculo, updated_by, updated_at) "
-            f"VALUES (s.egp_key, s.tipo_vinculo, current_user(), current_timestamp())",
+            f"VALUES (s.egp_key, s.tipo_vinculo, {ator()}, {agora})",
             want_rows=False)
         if on_write is not None:
             on_write()
```

Dois testes antigos comparam o texto do SQL e passam a esperar o alvo sem `t.`, com a mesma intenção:

```diff
--- a/egps_analysis/app/backend/test_ponte_tipo_vinculo.py
+++ b/egps_analysis/app/backend/test_ponte_tipo_vinculo.py
@@ -8,6 +8,7 @@ unificação é desfeita pela porta dos fundos — em silêncio, porque a tela "
 ninguém veria dois lugares registrando progresso.
 """
 import os
+import re
 import sys
 
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
@@ -103,9 +104,10 @@ def test_merge_toca_somente_tipo_vinculo():
     estado que a aba deixou para trás."""
     _, sqls, _ = _rodar({"egp_key": "A__x", "tipo_vinculo": "substituicao"}, atual="atualizacao")
     mrg = next(s for s in sqls if s.lower().startswith("merge into"))
-    assert "t.tipo_vinculo = s.tipo_vinculo" in mrg
-    for morto in ("t.etapa", "t.status", "t.responsavel"):
-        assert morto not in mrg, morto
+    # alvo do SET sem o "t." (o Postgres não aceita coluna-alvo qualificada; o Spark aceita as duas)
+    set_clause = mrg.split("UPDATE SET", 1)[1].split("WHEN NOT MATCHED", 1)[0]
+    assert re.findall(r"(\w+) = ", set_clause) == ["tipo_vinculo", "updated_by", "updated_at"]
+    assert "tipo_vinculo = s.tipo_vinculo" in set_clause
 
 
 def test_sem_mudanca_nao_audita_mas_ainda_grava():
```

```diff
--- a/egps_analysis/app/backend/test_egp_pipeline_patch_parcial.py
+++ b/egps_analysis/app/backend/test_egp_pipeline_patch_parcial.py
@@ -52,7 +52,8 @@ def _set_do_matched(merge):
 def test_patch_so_de_responsavel_nao_regrava_etapa_nem_status():
     s = _set_do_matched(_patch_e_merge({"projeto": "Area__X", "funil": "migracao",
                                         "responsavel": "b@x"}))
-    assert "t.responsavel = 'b@x'" in s
+    # alvo do SET sem o "t." (o Postgres não aceita coluna-alvo qualificada; o Spark aceita as duas)
+    assert "responsavel = 'b@x'" in s
     assert "etapa_migracao" not in s
     assert "status_migracao" not in s
     assert "egp_sucessor" not in s
@@ -61,8 +62,8 @@ def test_patch_so_de_responsavel_nao_regrava_etapa_nem_status():
 def test_patch_de_etapa_grava_a_etapa():
     s = _set_do_matched(_patch_e_merge({"projeto": "Area__X", "funil": "migracao",
                                         "etapa": "Validação em DES"}))
-    assert "t.etapa_migracao = 'Validação em DES'" in s
-    assert "t.responsavel" not in s
+    assert "etapa_migracao = 'Validação em DES'" in s
+    assert not re.search(r"\bresponsavel\b", s)
 
 
 def test_linha_nova_continua_inserindo_todas_as_colunas():
```

- [ ] **Step 3b: A sessão fixa o formato do instante.** O instante gravado em coluna texto (`cast({AGORA} AS STRING)`) só sai no formato do Spark com a sessão em UTC (já fixado) e DateStyle ISO, que vinha herdado do servidor (achado da revisão de 15/10). Teste primeiro, com uma conexão que chega com outro DateStyle e outro fuso:

```diff
diff --git a/egps_analysis/app/backend/db_pg.py b/egps_analysis/app/backend/db_pg.py
index d271cc85..d6bbe06c 100644
--- a/egps_analysis/app/backend/db_pg.py
+++ b/egps_analysis/app/backend/db_pg.py
@@ -41,6 +41,9 @@ class ErroSQL(Exception):
 def _configura(conn):
     conn.execute(f"SET search_path = {SEARCH_PATH}")
     conn.execute("SET TIME ZONE 'UTC'")
+    # O instante gravado em coluna texto (main.AGORA = localtimestamp) sai no formato do Spark
+    # ('2026-10-15 19:27:07.090031') só com DateStyle ISO: fixado aqui, não herdado do servidor.
+    conn.execute("SET DateStyle = 'ISO, MDY'")
     # Na AWS o app entra com o usuário MESTRE (o único que o indicium-secret-rotation gira)
     # e baixa os privilégios da sessão para PG_PAPEL (app_leitura na Fase 1). Barreira contra
     # escrita por engano; não contra quem já injeta SQL (RESET ROLE desfaz) — essa é do
diff --git a/egps_analysis/app/backend/test_db_pg.py b/egps_analysis/app/backend/test_db_pg.py
index a19c3e29..7ea722c7 100644
--- a/egps_analysis/app/backend/test_db_pg.py
+++ b/egps_analysis/app/backend/test_db_pg.py
@@ -7,6 +7,7 @@ PG_TEST_OBRIGATORIO=1 transforma o pulo em falha (pular em silêncio esconderia
 import datetime
 import decimal
 import os
+import re
 import sys
 
 import pytest
@@ -80,6 +81,20 @@ def test_sessao_baixa_para_o_papel_configurado(pool_novo, monkeypatch):
     assert db_pg.run("SELECT current_user AS u")[0]["u"] == "t_papel_app"
 
 
+@precisa_pg
+def test_sessao_fixa_fuso_e_formato_do_instante(pool_novo, monkeypatch):
+    """O instante gravado em coluna texto (`cast(AGORA AS STRING)` do main, Fase 2) só sai no
+    formato do Spark ('2026-10-15 19:27:07.090031') com a sessão em UTC e DateStyle ISO. O
+    app fixa os dois, sem herdar do servidor: aqui a conexão chega com outros."""
+    import psycopg
+    hostil = psycopg.conninfo.make_conninfo(DSN, options="-c DateStyle=SQL,DMY -c TimeZone=America/Sao_Paulo")
+    monkeypatch.setenv("PG_DSN", hostil)
+    r = db_pg.run("SELECT current_setting('DateStyle') AS ds, current_setting('TimeZone') AS tz, "
+                  "localtimestamp::text AS agora")[0]
+    assert (r["ds"], r["tz"]) == ("ISO, MDY", "UTC"), r
+    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(\.\d{1,6})?", r["agora"]), r
+
+
 def test_modo_leitura_recusa_escrita_sem_ir_ao_banco():
     with pytest.raises(db_pg.ErroSQL, match="permission denied"):
         db_pg.run("DELETE FROM x", somente_leitura=True)
```

- [ ] **Step 4: Rode tudo.**

```bash
PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres PG_TEST_OBRIGATORIO=1 .venv/bin/python -m pytest -q -p no:cacheprovider backend db sync paridade treino
```

Esperado: tudo passa (15/10, com a C1 já feita: 853 testes; a D1 soma 3).

- [ ] **Step 5: Commit** (só se pedido): `feat(app): escritas do app gravam no Postgres pelo espelho`.

---

## Parte C — O "Sincronizar grupo" sai

### Task C1: Sem SCIM do Databricks, o cadastro de analistas é manual (decisão de 15/10)

**Files:** `backend/main.py` (rota `POST /api/analistas/sync-grupo`), `frontend/src/components/GestaoView.tsx`, `frontend/src/api.ts`, `README.md`

- [ ] **Step 1:** Remova a rota, o botão, a mutação e a função do cliente:

```diff
--- a/egps_analysis/app/backend/main.py
+++ b/egps_analysis/app/backend/main.py
@@ -1239,63 +1259,11 @@ def analistas_delete(email: str):
     _ensure_analistas_table()
     e, _leg = _canon_analista_email((email or "").strip().lower())
     alvo = f"({sql_lit(e)}, {sql_lit(_leg)})" if _leg else f"({sql_lit(e)})"
-    run_sql(f"UPDATE {T_ANALISTAS} SET ativo = false, updated_by = current_user(), "
-            f"updated_at = cast(current_timestamp() AS STRING) WHERE email IN {alvo}", want_rows=False)
+    run_sql(f"UPDATE {T_ANALISTAS} SET ativo = false, updated_by = {_ator()}, "
+            f"updated_at = cast({AGORA} AS STRING) WHERE email IN {alvo}", want_rows=False)
     return {"ok": True, "email": e}
 
 
-@app.post("/api/analistas/sync-grupo")
-def analistas_sync_grupo():
-    """Best-effort: importa membros de bv_users via SCIM e faz upsert (só adiciona; não
-    desativa manuais). Requer leitura SCIM — se faltar (ex.: grupo de conta), retorna erro
-    claro e o cadastro manual segue confiável. Restrito a bv_users."""
-    _require_gestao()
-    _ensure_analistas_table()
-    try:
-        # SCIM (listar membros de grupo) é operação administrativa: usa o SERVICE PRINCIPAL
-        # do app (token all-apis, com scope scim), não o token OBO do usuário (sem scim).
-        w = _sp_client()
-        grp = next(iter(w.groups.list(filter='displayName eq "bv_users"')), None)
-        if grp is None:
-            return {"ok": False, "erro": "grupo bv_users não encontrado via SCIM (provável grupo de conta — cadastre manual)", "added": 0}
-        # groups.list frequentemente NÃO traz members; busca o grupo completo p/ obtê-los.
-        members = grp.members or []
-        if not members and getattr(grp, "id", None):
-            try:
-                members = (w.groups.get(grp.id).members or [])
-            except Exception:
-                members = []
-        n = 0
-        for m in members:
-            email = (getattr(m, "display", None) or "").strip().lower()
-            nome = email.split("@")[0] if "@" in email else None
-            if "@" not in email:
-                # display não é email → resolve o usuário pelo id do membro (m.value)
-                try:
-                    u = w.users.get(m.value)
-                    email = (u.user_name or "").strip().lower()
-                    nome = u.display_name or (email.split("@")[0] if "@" in email else None)
-                except Exception:
-                    continue
-            if "@" not in email:
-                continue
-            email, legado = _canon_analista_email(email)
-            if legado and int(run_sql(f"SELECT count(*) AS n FROM {T_ANALISTAS} "
-                                      f"WHERE email = {sql_lit(legado)}")[0]["n"]) > 0:
-                continue  # mesma pessoa já cadastrada com o sufixo legado .tech
-            run_sql(
-                f"MERGE INTO {T_ANALISTAS} t USING (SELECT {sql_lit(email)} AS email) s ON t.email = s.email "
-                f"WHEN NOT MATCHED THEN INSERT (email, nome, ativo, created_by, created_at, updated_by, updated_at) "
-                f"VALUES ({sql_lit(email)}, {sql_lit(nome or email.split('@')[0])}, true, current_user(), cast(current_timestamp() AS STRING), "
-                f"current_user(), cast(current_timestamp() AS STRING))", want_rows=False)
-            n += 1
-        return {"ok": True, "added": n, "membros": len(members)}
-    except HTTPException:
-        raise
-    except Exception as ex:
-        return {"ok": False, "erro": f"SCIM indisponível: {ex}", "added": 0}
-
-
 @app.get("/api/metrics")
 def metrics(scope: str = "indi", area: list[str] = Query(default=[])):
     _ensure_input_pipeline_cols()
```

```diff
--- a/egps_analysis/app/frontend/src/components/GestaoView.tsx
+++ b/egps_analysis/app/frontend/src/components/GestaoView.tsx
@@ -121,17 +121,6 @@ export function GestaoView() {
     onSuccess: invalidate,
     onError: (e) => setMsg(`Falha: ${e}`),
   });
-  const sync = useMutation({
-    mutationFn: () => api.analistasSyncGrupo(),
-    onSuccess: (r) => {
-      setMsg(r.ok
-        ? `Sincronizado: +${r.added ?? 0} novo(s) de ${r.membros ?? 0} membro(s) do grupo.`
-        : `Sync indisponível (${r.erro ?? "erro"}). Use o cadastro manual.`);
-      invalidate();
-    },
-    onError: (e) => setMsg(`Falha no sync: ${e}`),
-  });
-
   const rows: Analista[] = q.data?.rows ?? [];
 
   function add() {
@@ -282,10 +271,6 @@ export function GestaoView() {
               organograma
             </label>
             <button className="theme-btn" onClick={add} disabled={upsert.isPending}>+ Adicionar</button>
-            <button className="ghost" onClick={() => sync.mutate()} disabled={sync.isPending}
-              title="Importa membros do grupo bv_users (best-effort; se indisponível, cadastre manual)">
-              {sync.isPending ? "Sincronizando…" : "⟳ Sincronizar do grupo"}
-            </button>
           </div>
           {msg && <div className="muted" style={{ marginTop: 8 }}>{msg}</div>}
         </div>
@@ -325,7 +310,7 @@ export function GestaoView() {
               </tr>
             ))}
             {!q.isFetching && rows.length === 0 && (
-              <tr><td colSpan={5} className="muted">Nenhum analista cadastrado. Adicione acima ou sincronize do grupo.</td></tr>
+              <tr><td colSpan={5} className="muted">Nenhum analista cadastrado. Adicione acima.</td></tr>
             )}
           </tbody>
         </table>
```

```diff
--- a/egps_analysis/app/frontend/src/api.ts
+++ b/egps_analysis/app/frontend/src/api.ts
@@ -175,8 +175,6 @@ export const api = {
     }).then(json<{ ok: boolean; email: string; nome: string }>),
   analistaDelete: (email: string) =>
     fetch(`api/analistas/${encodeURIComponent(email)}`, { method: "DELETE" }).then(json<{ ok: boolean }>),
-  analistasSyncGrupo: () =>
-    fetch("api/analistas/sync-grupo", { method: "POST" }).then(json<{ ok: boolean; added?: number; membros?: number; erro?: string }>),
 
   responsaveisBv: (incluirInativos = false) =>
     fetch(`api/responsaveis-bv${incluirInativos ? "?incluir_inativos=true" : ""}`).then(json<ResponsaveisBvPayload>),
```

```diff
--- a/egps_analysis/app/README.md
+++ b/egps_analysis/app/README.md
@@ -71,7 +71,7 @@ Todas sob `/api/*` (declaradas **antes** do mount estático do SPA → têm prec
 | GET | `/api/priorizacao` | plano de meses (recorte fixo indi+deps; capacidade da config, default 400) + resumo |
 | PATCH | `/api/priorizacao/mes` · `/api/priorizacao/capacidade` | fixa/solta o **mês pinado** de um EGP (1..100) · muda a **capacidade** persistida do plano (1..10000) — ambos **gestão** |
 | GET/POST/DELETE | `/api/indicium` · `/api/escopo` · `/api/escopo/{id}[/ativar]` | lista DOR1 · adiciona · desativa (soft; `?hard=true` apaga) / reativa (cada edição **re-deriva o escopo** no app todo) |
-| GET/POST/DELETE | `/api/analistas[/{email}]` · POST `/api/analistas/sync-grupo` | GET aberto (dropdowns); escritas **gestão**; delete soft |
+| GET/POST/DELETE | `/api/analistas[/{email}]` | GET aberto (dropdowns); escritas **gestão**; delete soft. O antigo `sync-grupo` (SCIM do Databricks) saiu na Fase 2: cadastro só manual |
 | GET | `/api/scope-egps?scope&area` | indicador n_egps/n_base/n_deps do recorte (cards do Monitor) |
 | GET | `/api/egps-atualizados` · `/api/egps-atualizados/aguardando-corpus` · `/api/egp-atualizado?versao_id` | versões recebidas (módulo `backend/egps_atualizados.py`, **read-only puro**): catálogo p/ a busca do vínculo no detalhe do EGP · guarda "aguardando corpus" + pendências · comparação com o antecessor (inputs com JOIN vivo no monitor, outputs, histórico). O PATCH do funil próprio saiu com a aba (2026-09) |
 | GET | `/api/lineage/{areas,search,graph,neighbors}` | grafo de linhagem — `areas`/`graph`/`neighbors` com cache em memória (ver Decisões); `search` é live. **Aba Linhagem desativada (2026-07)** — rotas mantidas, sem UI |
@@ -933,7 +933,7 @@ Todo timestamp do painel (`sas_gestao_status.ts`, `sas_inputs_audit.updated_at`,
 Aba **Gestão** (`/gestao`) gerencia a lista de **analistas** (`sas_analistas`: email, nome, ativo) — fonte dos **dropdowns de responsável**. Atribuição de responsável acontece **nas abas existentes**: input (Monitor) e EGP (aba EGPs). Responsável do **input** = ingestão; do **EGP** = migração.
 
 - **Gate por grupo via SQL** (não SCIM): `is_account_group_member('bv_users') OR is_member('bv_users')` roda **como o usuário** (OBO). Exposto como `is_gestao` no `/api/config`; o front **esconde a aba** e o backend reforça **403** (`_require_gestao()`) nas escritas de analista. Aceita `bv_users`/`bv_user` (o real é `bv_users`, plural). Validado: `is_account_group_member('bv_users')`=true.
-- **Só a aba Gestão é restrita** — os **dropdowns** de responsável são livres a qualquer usuário (como editar status). `GET /api/analistas` é aberto (popular dropdowns); `POST/DELETE` e `sync-grupo` são gated. Delete é **soft** (`ativo=false`).
+- **Só a aba Gestão é restrita** — os **dropdowns** de responsável são livres a qualquer usuário (como editar status). `GET /api/analistas` é aberto (popular dropdowns); `POST/DELETE` são gated. Delete é **soft** (`ativo=false`).
 - **Valor guardado = email** do analista; a UI exibe o **nome**. Valores antigos (texto livre) seguem aparecendo até serem reatribuídos (o `<select>` injeta uma option com o valor atual se não estiver na lista).
 - **Sufixo canônico `@indicium.ai` (2026-07):** a mesma pessoa existe na Indicium com `@indicium.tech` e `@indicium.ai` — toda escrita (upsert/sync/delete) **canoniza para `.ai`** (`_canon_analista_email`) e **nunca duplica** por `nome.sobrenome`: se a pessoa já existe com o sufixo legado `.tech`, a linha é **migrada** para `.ai` (ou a legada é descartada se o `.ai` já existe); o delete desativa o par. Dados históricos migrados por UPDATE (analistas + colunas `responsavel`).
 - **EGP responsável**: coluna `responsavel` em `sas_egp_pipeline` (`_ensure_pipe_table` cria/ALTER); `PATCH /api/egp-pipeline` aceita `responsavel` (+ auditoria). Prontidão (`_egp_readiness_rows`) devolve `responsavel`.
```

- [ ] **Step 2:** Rode o guarda de cobertura, que só aceita rota existente em `FORA_DO_TESTE`, os testes do front e o build:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider backend/test_escritas_portadas.py
npm --prefix frontend run build
```

Rode cada `frontend/*.test.mts` com `node --experimental-strip-types`. Esperado: tudo passa.

- [ ] **Step 3: Commit** (só se pedido): `feat(app): Sincronizar grupo sai da Gestão`.

---

## Parte D — Prova contra o Databricks

O critério de aceite da ADR: o mesmo roteiro de edições, partindo dos mesmos dados, produz as
mesmas tabelas no Databricks e no Postgres. Ele importa porque o código traduzido também roda
no app de prod do Databricks: o `SET` sem `t.` e o novo texto de autor e horário precisam
funcionar no Spark.

### Task D1: O comparador em modo escritas

**Files:** `paridade/tabelas.py`, `paridade/test_tabelas.py`

- [ ] **Step 1: Testes.** O carimbo de instante e o id gerado comparam pela CLASSE do valor. Um `+00` no texto do Postgres continua aparecendo como diferença. Com `--desde` (o início do roteiro), só o instante a partir dele vira classe; o anterior compara pelo valor, e assim carimbo que não foi atualizado, UPDATE que carimbou linhas a mais e fuso deslocado para trás aparecem (revisão de 15/10). Os dois formatos de instante têm classe própria, e um `--desde` fora do formato é recusado.

```diff
diff --git a/egps_analysis/app/paridade/test_tabelas.py b/egps_analysis/app/paridade/test_tabelas.py
index 027bccd7..1ab0a957 100644
--- a/egps_analysis/app/paridade/test_tabelas.py
+++ b/egps_analysis/app/paridade/test_tabelas.py
@@ -1,7 +1,10 @@
 # -*- coding: utf-8 -*-
+import argparse
 import os
 import sys
 
+import pytest
+
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
 from paridade import tabelas  # noqa: E402
 
@@ -16,3 +19,86 @@ def test_conta_repetidas_e_aponta_a_coluna_sem_mostrar_valor():
     assert (r["so_no_databricks"], r["so_no_postgres"]) == (1, 1)
     assert r["colunas_que_diferem"] == ["y"]
     assert "1" not in repr(r["colunas_que_diferem"])
+
+
+# Depois do roteiro de escritas (paridade.escritas): os dois lados carimbaram em instantes
+# diferentes e sortearam ids diferentes — o valor some, a CLASSE do valor tem de bater.
+def test_mascara_carimbo_e_id_gerado_mas_nao_o_resto():
+    cols = ("id", "updated_by", "updated_at", "ts", "data")
+    spark = ("3f2a9c0e8b7d4a1f9e6c5b4a3d2c1b0a", "a@x", "2026-10-15 19:27:07.090031",
+             "2026-10-15T19:27:07.090Z", "2026-10-15")
+    pg = ("9b1c2d3e-4f5a-6b7c-8d9e-0f1a2b3c4d5e", "a@x", "2026-10-15 19:28:01.5",
+          "2026-10-15T19:28:01.500Z", "2026-10-15")
+    assert tabelas.mascara(cols, spark) == tabelas.mascara(cols, pg) == \
+        ("<id>", "a@x", "<instante>", "<instante T>", "2026-10-15")
+
+
+def test_mascara_id_so_na_coluna_id():
+    cols = ("id", "arquivo_hash")
+    h = "3f2a9c0e8b7d4a1f9e6c5b4a3d2c1b0a"
+    assert tabelas.mascara(cols, (h, h)) == ("<id>", h)
+
+
+def test_mascara_formatos_de_instante_tem_classe_propria():
+    cols = ("a", "b")
+    assert tabelas.mascara(cols, ("2026-10-15 19:27:07", "2026-10-15T19:27:07Z")) == \
+        ("<instante>", "<instante T>")
+
+
+DESDE = "2026-10-15 19:00:00"
+
+
+def test_desde_instante_antigo_compara_pelo_valor():
+    cols = ("updated_at",)
+    a = [tabelas.mascara(cols, ("2026-10-01 10:00:00.1",), DESDE)]
+    b = [tabelas.mascara(cols, ("2026-10-15 19:27:07.5",), DESDE)]   # carimbou onde não devia
+    assert tabelas.diferenca(a, b, cols)["so_no_databricks"] == 1
+    # coluna timestamp (T...Z) no MESMO dia do desde, mas antes dele: também compara pelo valor
+    assert tabelas.mascara(cols, ("2026-10-15T18:00:00.000Z",), "2026-10-15 19:25:00") == \
+        ("2026-10-15T18:00:00.000Z",)
+
+
+def test_desde_sem_escritas_e_recusado(monkeypatch):
+    # isolado: se o guarda regredir, o import do SDK falha em vez de comparar contra o Databricks
+    monkeypatch.setitem(sys.modules, "databricks.sdk", None)
+    with pytest.raises(SystemExit) as e:
+        tabelas.main(["--desde", "2026-10-15 19:25:00"])
+    assert e.value.code == 2
+
+
+def test_mascara_tamanhos_diferentes_falha_alto():
+    with pytest.raises(ValueError):
+        tabelas.mascara(("a", "b"), ("x",))
+
+
+def test_desde_valido_normaliza_e_recusa_formato_fora_do_padrao():
+    assert tabelas.desde_valido("2026-10-15 19:25") == "2026-10-15 19:25:00"
+    assert tabelas.desde_valido("2026-10-15T19:25:30.5Z") == "2026-10-15 19:25:30"
+    for ruim in ("15/10/2026 19:25", "10/15/2026 19:25:00", "2026-10-15", "2026-10-15 19:25+00"):
+        with pytest.raises(argparse.ArgumentTypeError):
+            tabelas.desde_valido(ruim)
+
+
+def test_desde_instante_novo_continua_mascarado():
+    cols = ("updated_at", "ts")
+    a = tabelas.mascara(cols, ("2026-10-15 19:27:07.09", "2026-10-15T19:27:07.090Z"), DESDE)
+    b = tabelas.mascara(cols, ("2026-10-15 19:40:00", "2026-10-15T19:40:00.5Z"), DESDE)
+    assert a == b == ("<instante>", "<instante T>")
+
+
+def test_sem_desde_todo_instante_vira_classe():
+    cols = ("updated_at",)
+    assert tabelas.mascara(cols, ("2026-10-01 10:00:00",)) == ("<instante>",)
+
+
+def test_mascara_instante_gravado_em_coluna_de_valor():
+    # o audit do snapshot da priorização grava a HORA em valor_novo (pego na prova de 15/10)
+    cols = ("campo", "valor_novo")
+    assert tabelas.mascara(cols, ("priorizacao_snapshot", "2026-10-15 20:46:39.015625")) == \
+        ("priorizacao_snapshot", "<instante>")
+
+
+def test_mascara_nao_esconde_carimbo_em_outro_formato_nem_nulo():
+    cols = ("updated_at", "created_at")
+    assert tabelas.mascara(cols, ("2026-10-15 19:27:07.090031+00", None)) == \
+        ("2026-10-15 19:27:07.090031+00", None)        # '+00' no texto não é o formato do Spark
```

- [ ] **Step 2:** Rode e veja falhar: `module 'paridade.tabelas' has no attribute 'mascara'`.

- [ ] **Step 3: Implemente.**

```diff
diff --git a/egps_analysis/app/paridade/tabelas.py b/egps_analysis/app/paridade/tabelas.py
index 6ea374c3..11146c8a 100644
--- a/egps_analysis/app/paridade/tabelas.py
+++ b/egps_analysis/app/paridade/tabelas.py
@@ -12,11 +12,13 @@ sincronização e a comparação aparece como diferença (rode de novo para conf
 
 Uso (a partir de egps_analysis/app):
   DATABRICKS_CONFIG_PROFILE=<perfil> PG_DSN=postgresql://... \\
-    python -m paridade.tabelas --warehouse <id> [--origem bv_dev_db.monitoramento_sas] [--tabela sas_x]
+    python -m paridade.tabelas --warehouse <id> [--origem bv_dev_db.monitoramento_sas] [--tabela sas_x] \\
+    [--escritas [--desde <instante UTC>]]
 """
 import argparse
 import collections
 import os
+import re
 import sys
 
 import psycopg
@@ -26,6 +28,55 @@ import db_pg  # noqa: E402
 from sync import espelho, leitor  # noqa: E402
 
 
+# Depois do roteiro de escritas (paridade.escritas, Fase 2) os dois lados carimbaram em instantes
+# diferentes e sortearam ids diferentes. Esses valores viram a CLASSE do valor, que ainda tem de
+# bater dos dois lados: '... +00' no texto do Postgres não é o formato do Spark e continua
+# aparecendo como diferença. Instante vale em qualquer coluna (o audit do snapshot da
+# priorização grava a hora em valor_novo); data sem hora não é instante e compara pelo valor.
+# Os dois formatos têm classe própria ('<instante>' e '<instante T>'): se um lado trocar um
+# pelo outro, aparece. Sem --desde, TODO instante vira classe, inclusive os anteriores ao
+# roteiro (a fidelidade deles é a da comparação SEM --escritas, 40/40). Com --desde, só vira
+# classe o instante a partir dele; o anterior compara pelo valor, e então aparece (a) UPDATE
+# traduzido que perdeu o carimbo (o valor antigo difere do que o outro lado carimbou) e
+# (b) UPDATE amplo demais que carimbou linhas a mais. O instante novo continua só pela classe:
+# fuso deslocado para trás além da folga (ex.: sessão em America/Sao_Paulo) cai antes do
+# --desde e aparece; deslocado para frente continua só pela classe.
+INSTANTE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(\.\d{1,6})?", re.ASCII)
+INSTANTE_T = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,6})?Z", re.ASCII)
+ID_GERADO = re.compile(r"[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
+                       re.ASCII)
+
+
+DESDE_FORMATO = re.compile(r"\d{4}-\d\d-\d\d( \d\d:\d\d(:\d\d)?|T\d\d:\d\d(:\d\d(\.\d{1,6})?)?Z)", re.ASCII)
+
+
+def _segundo(v):
+    return v[:19].replace("T", " ")
+
+
+def desde_valido(texto):
+    """Tipo do --desde. A comparação é lexicográfica: formato fora do padrão desligaria a
+    proteção em silêncio, então só 'AAAA-MM-DD HH:MM[:SS]' e 'AAAA-MM-DDTHH:MM[:SS][.f]Z' passam."""
+    if not DESDE_FORMATO.fullmatch(texto):
+        raise argparse.ArgumentTypeError(
+            f"{texto!r}: use 'AAAA-MM-DD HH:MM[:SS]' ou 'AAAA-MM-DDTHH:MM[:SS][.f]Z' (UTC)")
+    s = texto.rstrip("Z").replace("T", " ")
+    return s[:19] if len(s) >= 19 else s + ":00"
+
+
+def mascara(colunas, linha, desde=None):
+    desde = _segundo(desde) if desde else None
+    saida = []
+    for c, v in zip(colunas, linha, strict=True):
+        if v is not None and (INSTANTE.fullmatch(v) or INSTANTE_T.fullmatch(v)):
+            if desde is None or _segundo(v) >= desde:
+                v = "<instante T>" if "T" in v else "<instante>"
+        elif v is not None and c == "id" and ID_GERADO.fullmatch(v):
+            v = "<id>"
+        saida.append(v)
+    return tuple(saida)
+
+
 def diferenca(antigo, novo, colunas):
     """antigo/novo: listas de tuplas (texto). Devolve o resumo sem valores."""
     a, b = collections.Counter(antigo), collections.Counter(novo)
@@ -53,7 +104,15 @@ def main(argv=None):
     ap.add_argument("--warehouse", default=os.environ.get("DATABRICKS_WAREHOUSE_ID"))
     ap.add_argument("--origem", default="bv_dev_db.monitoramento_sas")
     ap.add_argument("--tabela", action="append")
+    ap.add_argument("--escritas", action="store_true",
+                    help="depois de paridade.escritas: carimbo de instante e id gerado comparam pela classe")
+    ap.add_argument("--desde", type=desde_valido,
+                    help="com --escritas: só instante a partir deste (UTC, 'AAAA-MM-DD HH:MM:SS') "
+                    "vira classe; é o início do roteiro com uma folga (ex.: 1 minuto antes), por causa do "
+                    "relógio entre as máquinas. Sem ele, todo instante vira classe")
     args = ap.parse_args(argv)
+    if args.desde and not args.escritas:
+        ap.error("--desde só vale com --escritas")
     from databricks.sdk import WorkspaceClient
     w = WorkspaceClient()
     iguais, total = 0, 0
@@ -62,7 +121,11 @@ def main(argv=None):
             cols = espelho.colunas(t)
             antigo = [tuple(r[c] for c in cols)
                       for r in leitor.le_tabela(w, args.warehouse, f"{args.origem}.{t}", cols)]
-            r = diferenca(antigo, le_postgres(conn, t), cols)
+            novo = le_postgres(conn, t)
+            if args.escritas:
+                antigo = [mascara(cols, x, args.desde) for x in antigo]
+                novo = [mascara(cols, x, args.desde) for x in novo]
+            r = diferenca(antigo, novo, cols)
             igual = r["so_no_databricks"] == r["so_no_postgres"] == 0
             iguais, total = iguais + igual, total + 1
             print(f"[tabelas] {'IGUAL' if igual else 'DIFERE'} {t}: {r}", flush=True)
```

- [ ] **Step 4:** `pytest paridade`: tudo passa.

### Task D2: O roteiro fixo de escritas

**Files:** Create `paridade/escritas.py`

- [ ] **Step 1:** São 26 edições, pela API, nos dois apps.
  - Os alvos saem da base Postgres por `ORDER BY`, antes do roteiro, quando ela é igual ao Databricks.
  - A rota que usa o id de uma escrita anterior (escopo, "Com BV") usa o id DAQUELE lado.

```python
# -*- coding: utf-8 -*-
"""Roteiro fixo de escritas (ADR 0005, Fase 2): a MESMA sequência de edições, pela API, no app
antigo (Databricks) e no novo (Postgres), partindo da mesma base. Depois,
`paridade.tabelas --escritas --desde <instante UTC>` compara as 40 tabelas (o --desde mascara só os
instantes a partir do início do roteiro; o roteiro imprime o comando pronto) — é o critério de
aceite da escrita na ADR.

Os alvos saem da base Postgres de forma determinística (ORDER BY), ANTES do roteiro, quando
ela é igual ao Databricks (paridade.tabelas 40/40). As duas bases precisam ser descartáveis:
o roteiro grava de verdade (responsável de teste, escopo, vínculo, snapshot da priorização...).
Para os dois lados gravarem o mesmo autor, o app Postgres roda com DEV_USUARIO igual ao
usuário do Databricks. Esse usuário, nos DOIS lados (DEV_USUARIO no app Postgres; o usuário do
Databricks), precisa ser admin (bv_admins): o snapshot da priorização e o Com BV exigem.
O roteiro NÃO é idempotente: rodar de novo na mesma base falha em passos como familia-periodo
(a base é descartável).

Uso (a partir de egps_analysis/app):
  PG_DSN=postgresql://... python -m paridade.escritas --antigo http://127.0.0.1:8010 \\
      --novo http://127.0.0.1:8011
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import psycopg

MARCA = "Paridade 2A"   # tudo o que o roteiro escreve leva esta marca
# escritas que devolvem o id usado pelo passo seguinte ({id} na rota)
PRODUZ_ID = {("POST", "/api/escopo"), ("POST", "/api/gestao/bv")}


def alvos(dsn):
    """Chaves reais da base, escolhidas sempre do mesmo jeito."""
    with psycopg.connect(dsn) as c:
        c.execute("SET search_path = compat, derivado, pg_catalog, public")

        def um(sql, *params):
            linha = c.execute(sql, params).fetchone()
            if linha is None:
                raise SystemExit(f"[escritas] base sem alvo para: {sql[:90]}")
            return linha

        egp, = um("SELECT projeto FROM sas_lineage_nodes WHERE escopo_indi ORDER BY projeto LIMIT 1")
        vinculados = ("SELECT projeto FROM sas_egp_pipeline WHERE coalesce(egp_sucessor, '') <> '' "
                      "UNION SELECT egp_sucessor FROM sas_egp_pipeline WHERE coalesce(egp_sucessor, '') <> ''")
        # Migrado é terminal: o PATCH de vínculo recusa (409) antecessor nesse status
        livres = [r[0] for r in c.execute(
            f"SELECT projeto FROM sas_lineage_nodes WHERE projeto <> %s AND projeto NOT IN ({vinculados}) "
            f"AND projeto NOT IN (SELECT projeto FROM sas_egp_pipeline WHERE status_migracao = 'Migrado') "
            f"ORDER BY projeto LIMIT 2", (egp,))]
        if len(livres) < 2:
            raise SystemExit("[escritas] base sem 2 EGPs livres (sem vínculo e fora de Migrado) para o vínculo")
        fora, area = um("SELECT projeto, area FROM sas_lineage_nodes WHERE NOT escopo_indi AND projeto NOT IN "
                        "(SELECT projeto FROM sas_escopo WHERE projeto IS NOT NULL) ORDER BY projeto LIMIT 1")
        multi, produtor_out = um(
            "SELECT o.chave_canonica, min(e.projeto) FROM sas_outputs_monitor o JOIN sas_egp_outputs e "
            "USING (chave_canonica) WHERE o.qtd_produtores > 1 AND o.chave_canonica NOT IN "
            "(SELECT chave_canonica FROM sas_output_producer_choice) GROUP BY 1 ORDER BY 1 LIMIT 1")
        produtor, = um("SELECT depende_do FROM sas_lineage_edges WHERE coalesce(via_tabelas, '') <> '' "
                       "AND projeto_alvo <> depende_do ORDER BY depende_do LIMIT 1")
        # EGP novo: fora do escopo e diferente de todos os outros EGPs que o roteiro usa
        usados = [egp, *livres, fora, produtor]
        egp_novo = next((r[0] for r in c.execute(
            "SELECT projeto FROM sas_lineage_nodes WHERE NOT escopo_indi ORDER BY projeto DESC")
            if r[0] not in usados), None)
        if egp_novo is None:
            raise SystemExit("[escritas] base sem alvo para egp_novo (fora do escopo e distinto dos demais alvos)")
        atu_key, = um("SELECT egp_key FROM sas_egp_atualizados ORDER BY egp_key LIMIT 1")
        atu_tipo = c.execute("SELECT tipo_vinculo FROM sas_egp_atualizados_pipeline WHERE egp_key = %s",
                             (atu_key,)).fetchone()
        return {
            "input": um("SELECT chave_canonica FROM sas_inputs_monitor WHERE categoria = 'tabela' "
                        "AND NOT coalesce(orfao, false) ORDER BY qtd_projetos DESC, chave_canonica LIMIT 1")[0],
            "arquivo": um("SELECT chave_canonica FROM sas_inputs_monitor WHERE categoria = 'arquivo' "
                          "AND NOT coalesce(orfao, false) ORDER BY chave_canonica LIMIT 1")[0],
            "egp": egp,
            "par": um("SELECT projeto, chave_canonica FROM sas_egp_inputs WHERE projeto = %s "
                      "ORDER BY chave_canonica LIMIT 1", egp),
            "antigo": livres[0], "sucessor": livres[1],
            "produtor": produtor,
            "egp_novo": egp_novo,
            "fora": fora, "area": area,
            "output": um("SELECT chave_canonica FROM sas_outputs_monitor ORDER BY chave_canonica LIMIT 1")[0],
            "multi": multi, "produtor_out": produtor_out,
            "atu_key": atu_key,
            "atu_tipo": "substituicao" if (atu_tipo or [None])[0] != "substituicao" else "atualizacao",
        }


def roteiro(a):
    """(método, rota, corpo) — rota com {id} usa o id que a escrita anterior devolveu DAQUELE lado."""
    egp_dor1 = a["fora"].split("__", 1)[-1]
    return [
        ("POST", "/api/responsaveis-bv", {"nome": f"Teste {MARCA}", "subarea": "Cobrança"}),
        ("POST", "/api/analistas", {"email": "teste.paridade2a@indicium.ai", "nome": f"Teste {MARCA}"}),
        ("DELETE", "/api/analistas/teste.paridade2a@indicium.ai", None),
        ("PATCH", "/api/inputs", {"chave_canonica": a["input"], "responsavel": f"Teste {MARCA}",
                                  "observacao": MARCA}),
        ("PATCH", "/api/inputs/preworking", {"chave_canonica": a["arquivo"], "frequencia": "Diária",
                                             "recebido": "true", "data_recebimento": "2026-10-01"}),
        ("PATCH", "/api/familia-ingestao", {"categoria": "tabela", "familia": "PARIDADE_2A.FAM",
                                            "desde": "202601", "ingerida_em": "2026-10-01"}),
        ("PATCH", "/api/egp-pipeline", {"projeto": a["egp"], "responsavel": f"Teste {MARCA}", "jira_id": "BV-2026"}),
        ("PATCH", "/api/egp-pipeline", {"projeto": a["antigo"], "responsavel": f"Teste {MARCA}"}),
        ("PATCH", "/api/egp-pipeline", {"projeto": a["antigo"], "egp_vinculo_tipo": "Substituído",
                                        "egp_sucessor": a["sucessor"]}),
        ("PATCH", "/api/egp-input-link", {"projeto": a["par"][0], "chave_canonica": a["par"][1],
                                          "link_broken": True}),
        ("PATCH", "/api/familia-periodo", {"projeto": a["egp"], "categoria": "tabela",
                                           "familia": "PARIDADE_2A.FAM", "tipo": "desde", "valor": "202601"}),
        ("PATCH", "/api/egp-dep-mantida", {"produtor": a["produtor"], "mantida": True, "motivo": MARCA}),
        ("PATCH", "/api/egps-novos", {"projeto": a["egp_novo"], "acao": "declarar"}),
        ("PATCH", "/api/egp-atualizado-pipeline", {"egp_key": a["atu_key"], "tipo_vinculo": a["atu_tipo"]}),
        ("PATCH", "/api/output-pipeline", {"chave_canonica": a["output"], "recebido": True,
                                           "recebido_data": "2026-10-01"}),
        ("POST", "/api/output-producer", {"chave_canonica": a["multi"], "projeto_escolhido": a["produtor_out"]}),
        ("POST", "/api/escopo", {"egp_dor1": egp_dor1, "area": a["area"], "projeto": a["fora"]}),
        ("DELETE", "/api/escopo/{id}", None),
        ("POST", "/api/escopo/{id}/ativar", None),
        ("POST", "/api/gestao/status", {"entity": "egp", "id": a["egp"], "autor": f"Teste {MARCA}",
                                        "texto": MARCA}),
        ("POST", "/api/gestao/bv", {"entity": "egp", "id": a["egp"], "comBv": True}),
        ("POST", "/api/gestao/bv", {"entity": "egp", "id": a["egp"], "comBv": False}),
        ("DELETE", "/api/gestao/bv?id={id}", None),
        ("POST", "/api/gestao/revisao", {"id": a["egp"], "delta": 1}),
        ("PATCH", "/api/gestao/datas", {"entity": "egp", "id": a["egp"], "campo": "inicio", "valor": "2026-10-01"}),
        ("POST", "/api/priorizacao/snapshot", {"pins": {}}),
    ]


def chama(base, metodo, rota, corpo):
    dados = None if corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(base.rstrip("/") + rota, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except (urllib.error.URLError, TimeoutError, ValueError) as e:   # sem resposta ou corpo não-JSON
        return 0, f"{type(e).__name__}: {e}"[:300]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aplica o roteiro fixo de escritas nos dois apps")
    ap.add_argument("--antigo", required=True)
    ap.add_argument("--novo", required=True)
    args = ap.parse_args(argv)
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        raise SystemExit("[escritas] defina PG_DSN com o DSN da base Postgres (descartável) que serve de referência")
    passos = roteiro(alvos(dsn))
    desde = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")
    comparar = f"[escritas] para comparar depois: python -m paridade.tabelas --escritas --desde '{desde}'"
    print(comparar, flush=True)
    ultimo_id = {"antigo": None, "novo": None}
    falhas = 0
    for metodo, rota, corpo in passos:
        status = {}
        for lado, base in (("antigo", args.antigo), ("novo", args.novo)):
            if (metodo, rota) in PRODUZ_ID:
                ultimo_id[lado] = None   # nunca reaproveita o id de uma escrita anterior
            if "{id}" in rota and not ultimo_id[lado]:
                status[lado] = 0
                print(f"[escritas]   {lado}: sem id da escrita anterior", flush=True)
                continue
            st, r = chama(base, metodo, rota.replace("{id}", urllib.parse.quote(ultimo_id[lado] or "")), corpo)
            status[lado] = st
            if st == 200 and isinstance(r, dict) and r.get("id"):
                ultimo_id[lado] = r["id"]
            elif st != 200:
                ultimo_id[lado] = None
                print(f"[escritas]   {lado}: HTTP {st} {r}", flush=True)
        ok = status["antigo"] == status["novo"] == 200
        falhas += not ok
        print(f"[escritas] {'OK   ' if ok else 'FALHA'} {metodo} {rota} {status}", flush=True)
    print(f"[escritas] {len(passos) - falhas}/{len(passos)} escritas aceitas nos dois lados")
    print(comparar, flush=True)
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
```

### Task D3: Rodar num schema descartável (com consentimento)

- [ ] **Step 1:** Peça o consentimento. Esta task cria e apaga `bv_dev_db.monitoramento_sas_2a` no Databricks e um banco local carregado com dados do BV (`monitoramento_2a`).

- [ ] **Step 2: Clone o dev** no schema descartável. O script recusa se o schema já existir:

```python
"""Schema DESCARTÁVEL para validar as escritas da Fase 2 no Spark (autorizado em 15/10/2026):
clona as 40 tabelas do espelho de bv_dev_db.monitoramento_sas_dev em
bv_dev_db.monitoramento_sas_2a. Recusa se o schema já existir. --apaga derruba o schema.
Uso (de egps_analysis/app): DATABRICKS_CONFIG_PROFILE=bv .venv/bin/python clona_2a.py [--apaga]"""
import os
import sys
import time

sys.path.insert(0, os.getcwd())
from databricks.sdk import WorkspaceClient  # noqa: E402
from sync.espelho_tabelas import TABELAS  # noqa: E402

WAREHOUSE = "5922c26f81f1bbdd"
ORIGEM, DESTINO = "bv_dev_db.monitoramento_sas_dev", "bv_dev_db.monitoramento_sas_2a"
w = WorkspaceClient()


def sql(stmt):
    r = w.statement_execution.execute_statement(statement=stmt, warehouse_id=WAREHOUSE, wait_timeout="50s")
    while r.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"{stmt[:80]}: {r.status.state.value} {r.status.error}")
    return r.result.data_array if r.result else None


if "--apaga" in sys.argv:
    sql(f"DROP SCHEMA IF EXISTS {DESTINO} CASCADE")
    print("[2a] schema apagado:", DESTINO)
    sys.exit(0)
existentes = [x[0] for x in sql("SHOW SCHEMAS IN bv_dev_db LIKE 'monitoramento_sas_2a'") or []]
if existentes:
    sys.exit(f"[2a] {DESTINO} já existe — nada foi feito")
sql(f"CREATE SCHEMA {DESTINO} COMMENT 'DESCARTAVEL: validacao das escritas da Fase 2 (15/10/2026). Apagar.'")
for t in TABELAS:
    sql(f"CREATE TABLE {DESTINO}.{t} DEEP CLONE {ORIGEM}.{t}")
    print("[2a] clonada", t, flush=True)
print(f"[2a] {len(TABELAS)} tabelas em {DESTINO}")
```

```bash
DATABRICKS_CONFIG_PROFILE=bv .venv/bin/python /tmp/clona_2a.py
```

- [ ] **Step 3: Banco local, carga e comparação de partida.** Esperado: `40/40 tabelas iguais`.

```bash
PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_2a .venv/bin/python -m db.migra --cria-banco
PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_2a DATABRICKS_CONFIG_PROFILE=bv DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd ORIGEM_SCHEMA=bv_dev_db.monitoramento_sas_2a .venv/bin/python -m sync.sincroniza
PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_2a DATABRICKS_CONFIG_PROFILE=bv .venv/bin/python -m paridade.tabelas --warehouse 5922c26f81f1bbdd --origem bv_dev_db.monitoramento_sas_2a
```

- [ ] **Step 4: Os dois apps.** O autor tem de ser o mesmo nos dois lados. O `current_user()` do Databricks é `lucas.muller@indicium.ai`, então o app Postgres roda com esse `DEV_USUARIO`, cadastrado como admin:

```sql
SELECT set_config('app.usuario', 'lucas.muller@indicium.ai', false);
INSERT INTO cadastro.usuario (email, nome, papel) VALUES ('lucas.muller@indicium.ai', 'Lucas Muller', 'admin')
ON CONFLICT (email) DO UPDATE SET papel = 'admin', ativo = true;
```

```bash
DB_BACKEND=databricks PUBLISH_CATALOG=bv_dev_db PUBLISH_SCHEMA=monitoramento_sas_2a DATABRICKS_CONFIG_PROFILE=bv DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd APP_PORT=8010 FAMILIAS_SAFRA=1 .venv/bin/python backend/main.py
DB_BACKEND=postgres PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_2a PUBLISH_SCHEMA=compat IDENTIDADE=dev DEV_USUARIO=lucas.muller@indicium.ai PG_PAPEL=app_escrita SOMENTE_LEITURA=0 APP_PORT=8011 FAMILIAS_SAFRA=1 .venv/bin/python backend/main.py
```

- [ ] **Step 5: O roteiro e a comparação depois dele:**

```bash
PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_2a .venv/bin/python -m paridade.escritas --antigo http://127.0.0.1:8010 --novo http://127.0.0.1:8011
PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento_2a DATABRICKS_CONFIG_PROFILE=bv .venv/bin/python -m paridade.tabelas --warehouse 5922c26f81f1bbdd --origem bv_dev_db.monitoramento_sas_2a --escritas --desde '<o instante que o roteiro imprimiu>'
```

Esperado: `26/26 escritas aceitas nos dois lados` e `40/40 tabelas iguais`.

- [ ] **Step 6: Limpe.** Pare os dois apps, rode `/tmp/clona_2a.py --apaga` e faça `DROP DATABASE monitoramento_2a WITH (FORCE)`.

---

## Parte E — O dev da AWS vira o laboratório (depois do apply da F2 e do deploy do 1b)

### Task E1: O papel da sessão segue o modo do ambiente

Na F2 (`indicium_infra`, `aws/production-acc/ecs_applications/monitoramento_sas/`), o
`PG_PAPEL` era fixo em `app_leitura`. Passa a seguir `somente_leitura`: `"1"` usa
`app_leitura`, `"0"` usa `app_escrita`. Ligar a escrita de um ambiente vira a troca de uma
chave.

- [ ] **Step 1:** Em `ecs.tf`, troque `{ name = "PG_PAPEL", value = "app_leitura" },` por:

```hcl
      # Entra como mestre (o único que a plataforma gira) e baixa a sessão (db_pg._configura):
      # só leitura -> app_leitura; com escrita (Fase 2) -> app_escrita (migração 0007).
      { name = "PG_PAPEL", value = each.value.somente_leitura == "1" ? "app_leitura" : "app_escrita" },
```

- [ ] **Step 2:** Em `vars.tf`, troque o `somente_leitura` do dev para `"0"`. O comentário de `ambientes` passa a dizer que o dev é o laboratório da Fase 2.
- [ ] **Step 3:** `terraform fmt`, `validate`, `tflint` (via Docker) e o pre-commit. Depois, PR (o usuário abre pelo link). Se a F2 ainda não tiver sido aplicada, isto entra na própria branch dela.

### Task E2: Migrações 0006 e 0007 no dev e na prod (com consentimento)

- [ ] Logo depois do push da imagem do 2a e ANTES da próxima sincronização agendada (ou com o agendamento pausado), uma tarefa avulsa por banco, como na H1 do 1a (`python -m db.migra`, sem `--cria-banco`). Esperado: `[migra] aplicada 0006_...` e `[migra] aplicada 0007_...`. A prod continua só leitura, porque o `PG_PAPEL` dela segue `app_leitura`.
- [ ] A ordem importa:
  - A imagem nova sincroniza as 40 tabelas. Num banco sem a 0006, cada rodada falha com `relation "legado.sas_egp_atualizados_audit" does not exist`. A falha é barulhenta (dispara o alarme), mas dá para evitar.
  - A troca do dev para `somente_leitura = "0"` (Task E1, Step 2) só pode vir depois da 0007. Sem o papel `app_escrita`, o `SET ROLE` falha e o app do dev não abre conexão.

### Task E3: Carga do dev com cópia de prod e o roteiro na AWS (com consentimento)

- [ ] Carregue o dev uma vez com a sincronização, como na H3 do 1a: o `run-task` com `PGDATABASE=monitoramento_dev`.
- [ ] Rode `paridade.escritas` contra o app dev da AWS e contra um app Databricks local apontando para um schema descartável clonado da mesma origem, como na Parte D. Depois rode `paridade.tabelas --escritas`. Esperado: 40/40.

---

## Parte F — Documentos

- [ ] A spec ganha a decisão de 15/10, a Fase 2 dividida em 2a a 2d, a Fase 3, o dev como laboratório depois do 2a e os critérios de escrita e login:

```diff
--- a/egps_analysis/app/docs/superpowers/specs/2026-10-14-migracao-aws-design.md
+++ b/egps_analysis/app/docs/superpowers/specs/2026-10-14-migracao-aws-design.md
@@ -140,6 +140,10 @@ ECR: imagem do app · CloudWatch: logs + alarme (SNS por e-mail)
 
 ## Schema
 
+> **Desde 15/10/2026 este modelo é a Fase 3** (ver Fases). Nas Fases 1 e 2 o app lê, e depois
+> escreve, o espelho `legado` pelas views `compat`; o modelo abaixo continua sendo o destino
+> do de-para com as correções, se ele ainda valer a pena depois de o Databricks sair.
+
 DDL: [`2026-10-14-migracao-aws-schema.sql`](2026-10-14-migracao-aws-schema.sql). Aplicado
 num Postgres 17 em 2026-10-14: 44 tabelas, 6 views, 44 PK, 44 FK, 55 CHECK, 5 UNIQUE.
 Testes de comportamento em
@@ -257,8 +261,10 @@ ensaio de Terraform no mesmo dia, sem DNS e sem dado.
 (passo 0, infra, migrações, sincronização das 5 primeiras tabelas, backend em modo Postgres,
 CI, subida fechada ao BV); [1b](../plans/2026-10-14-migracao-aws-fase1b.md) — espelho fiel
 das demais tabelas, port das rotas GET até a comparação zerar, front sem escrita para o
-leitor, cadastro do BV e JIT; 2 — de-para para o schema novo com as correções, escrita,
-publish e virada.
+leitor, cadastro do BV e JIT; [2a](../plans/2026-10-15-migracao-aws-fase2a.md) — escrita
+no Postgres sobre o espelho; 2b — publish do pacote do orchestrator dentro do app; 2c — a
+virada; 2d — o pipeline inteiro (extractor e orchestrator) dentro do app. O de-para para o
+schema novo com as correções é a Fase 3 (decisão de 15/10, abaixo).
 
 **Decisão de 14/10 (1b): na Fase 1, cópia fiel em vez de de-para.** O inventário de prod
 mostrou caso especial demais para normalizar e remontar byte a byte já na Fase 1: 17 colunas
@@ -313,37 +319,62 @@ dimensionar prod — isso sai do dev da AWS, com dado real.
 4. App de prod na AWS **só leitura para todos**, lendo pelas views `compat`: port de dialeto
    das rotas GET, login, papéis, faixa "dados de HH:MM" (vermelha após 1 h de atraso no
    horário comercial).
-5. Dev na AWS **com escrita**, sem sincronização, carregado com cópia de prod e com log
-   estruturado de cada escrita (rota, usuário, linhas, erro). É onde a fase 2 é construída.
+5. Dev na AWS só leitura, como a prod, até o plano 2a. Com o 2a ele passa a ter escrita
+   (`app_escrita`), sem sincronização agendada, carregado uma vez com cópia de prod. É o
+   laboratório da Fase 2.
 6. Comparação das leituras; cadastro do BV como leitor; comunicação do endereço novo.
 7. **JIT volta** quando: o teste de login passou, a comparação das leituras bateu, o BV está
    cadastrado como leitor e já entrou no endereço novo.
 
+**Decisão de 15/10 (Fase 2): o espelho vira a fonte.** Na virada, o app e o publish passam
+a escrever nas MESMAS tabelas do `legado`, pelas views `compat`, só com o SQL traduzido. O
+Postgres aceita INSERT/UPDATE/DELETE/MERGE nas views simples de uma tabela, e o SQL muda de
+dialeto, não de tabela. O de-para para o schema novo com as correções vira a Fase 3, já num
+sistema só e sem sincronização no meio. Fazer o de-para antes atrasaria a saída do Databricks
+sem mudar o que o usuário vê. Decidido na mesma rodada:
+- a virada da escrita acontece num momento só, e não por grupo;
+- o publish entra no próprio app: primeiro o pacote do orchestrator, depois o pipeline
+  inteiro. Os textos extraídos vão para o Postgres e os binários `.egp` para um S3 privado.
+  A VPN fica para ajuste manual, como exceção;
+- o botão "Sincronizar grupo" da Gestão sai, e os analistas passam a ser cadastrados à mão;
+- não há data alvo.
+
 **Fase 2 — o Postgres vira a fonte da verdade**
-1. Escritas no schema `trabalho` com `app.usuario`; papéis aplicados no backend.
-2. Publish em uma transação no Postgres (por enquanto da máquina, pela VPN; no futuro,
-   tarefa ECS); `publish_egps_atualizados.py`, `identidade_*.py`; `sync_dev.py` vira
+1. **2a, escrita.** Entram no espelho as 7 tabelas que as escritas e o publish usam: os 4
+   audits que faltavam, `sas_resumo_proj`, `sas_pipeline_metrics` e
+   `sas_input_alias_canonico`. As escritas são traduzidas: quem grava sai de `_ator()`, a
+   hora sai de `AGORA`, e a coluna-alvo do SET perde o `t.`. O papel `app_escrita` só grava
+   nas 33 views que o app grava. A prova é um roteiro fixo de edições nos dois lados.
+2. **2b, publish no app.** O publish do pacote do orchestrator roda numa transação, com
+   prévia, e `publish_egps_atualizados.py` e `identidade_*.py` vêm junto. `sync_dev.py` vira
    `pg_dump`/`pg_restore`. Os scripts de `docs/analises` são histórico e não são portados.
-3. Migração dos dados com as correções e o relatório de números que mudaram; normalização
-   dos e-mails. É aqui o de-para das tabelas do espelho para o schema novo, por grupo, com a
-   auditoria de integridade; a view `compat` de cada grupo passa a ler do schema novo e
-   `legado` encolhe até sumir.
-4. Rotas saem das views `compat` uma a uma; `compat` some.
-5. Saem a aba Perguntas, a pasta `genie/` e a rotina de consulta (ADR 0004).
-6. Virada: a gestão passa a editar no app AWS; a sincronização para; o app do Databricks é
-   desligado; o schema `monitoramento_sas` fica só leitura para sempre.
+3. **2c, virada.** A gestão passa a editar no app AWS e a sincronização para de vez. Saem a
+   aba Perguntas, a pasta `genie/` e a rotina de consulta (ADR 0004). O app do Databricks é
+   desligado, e o schema `monitoramento_sas` fica só leitura para sempre.
+4. **2d, pipeline no app.** Extractor e orchestrator rodam na AWS, a partir do `.egp` que a
+   pessoa sobe.
+
+**Fase 3 (se ainda valer a pena) — o modelo novo.** É o de-para do espelho para o schema da
+seção Schema, por grupo, com as correções, o relatório de números que mudaram, a
+normalização dos e-mails e a auditoria de integridade. As rotas saem das views `compat`,
+`legado` encolhe até sumir, e as escritas passam para `trabalho`/`historico` com
+`app.usuario`.
 
 ## Critérios de verificação
 
 - **Leitura**: para cada rota GET e conjunto de parâmetros, o JSON do app novo é igual ao do
   antigo partindo dos mesmos dados; diferenças aceitas = as do relatório de correções.
 - **Escrita**: um roteiro fixo de edições aplicado no dev antigo e no dev novo, partindo dos
-  mesmos dados, produz as mesmas tabelas (após o mapeamento).
+  mesmos dados, produz as mesmas tabelas (`paridade.escritas` e depois
+  `paridade.tabelas --escritas`: o instante gravado e o id gerado comparam pela classe do
+  valor). Toda rota de escrita tem teste contra um Postgres de verdade
+  (`backend/test_escritas_pg.py`, com guarda de cobertura).
 - **Testes**: a suíte do backend roda contra um Postgres de verdade no CI (service
   container do Bitbucket); os testes que hoje validam o texto do SQL Spark são reescritos.
 - **Papel**: teste automático percorre todas as rotas de escrita e exige 403 para o leitor.
-- **Login**: requisição sem login nunca chega ao app; cabeçalho OIDC com assinatura
-  inválida → 401.
+- **Login**: sem login, o app só serve `/login` e `/api/health` (o resto vai para `/login` e
+  a API responde 401); cabeçalho OIDC com assinatura inválida, ou com e-mail não verificado
+  → 401.
 - **Sincronização**: contagem por tabela igual à do Databricks; falha → faixa vermelha +
   alarme.
 
```

- [ ] A ADR 0005 ganha o parágrafo de atualização:

```diff
--- a/docs/adr/0005-app-sai-do-databricks.md
+++ b/docs/adr/0005-app-sai-do-databricks.md
@@ -6,4 +6,6 @@ A plataforma da Indicium vai restringir o Databricks a identidades da Indicium (
 
 Opções rejeitadas: **levar só o app para a AWS e manter os dados no Databricks**, lidos por conta de serviço — mais simples de construir, mas mantém o custo (warehouse ~US$ 600 e os dois apps ~US$ 335 em 30 dias, a preço de tabela, quase tudo uso do próprio app), o piso de ~1 s por consulta e os grants de conta de serviço que somem a cada apply do Terraform; **dashboard AI/BI com credencial embutida** — o link só abre para usuário cadastrado na conta Databricks, então não alcança o cliente; **dashboard incorporado para externos** — exige uma página com login de qualquer jeito e só entrega leitura; **Delta Sharing / Marketplace** — Delta Sharing não leva app, e app de Marketplace roda na conta de quem recebe; **conta AWS dedicada** — o setup de conta não compensa, e o RDS e o security group próprios já isolam os dados; **cluster ECS compartilhado** (`tf-indicium-ecs`) — o banco teria de aceitar o security group do cluster inteiro, ou seja, qualquer app que rode ali; **App Runner** — fechado a clientes novos desde 30/04/2026; **ECS Express Mode** — cria load balancer próprio, contra a regra de um load balancer compartilhado.
 
+Atualização (2026-10-15): na Fase 2, a cópia fiel que a Fase 1 mantém (schema `legado`) vira a fonte. O app e o publish passam a escrever nas mesmas tabelas, só com o SQL traduzido, e o publish entra no próprio app. O de-para para o modelo novo, com as correções de dados, fica para uma Fase 3, se ainda valer a pena: refazer o modelo antes de desligar o Databricks atrasaria a saída sem mudar o que o cliente vê. A virada da escrita acontece num momento só.
+
 Consequências: somem a aba Perguntas (Genie) e a rotina das tabelas de consulta — esta ADR substitui a 0004 a partir da virada da Fase 2. Pronto = o app novo responde igual ao antigo em todas as rotas de leitura com os mesmos dados (comparação automática), e um roteiro fixo de edições produz as mesmas tabelas no dev antigo e no novo. O escape de literais muda antes da primeira consulta no Postgres: o `\'` do Spark vira injeção no Postgres. O JIT só volta quando o login com conta do cliente foi testado, a comparação das leituras bateu, as pessoas do cliente estão cadastradas como leitor e o cliente já entrou no endereço novo.
```

- [ ] **Commit** (só se pedido): `docs(app): Fase 2 com o espelho como fonte (plano 2a)`.

## Saída do 2a

- Toda rota de escrita grava no Postgres pelo espelho. Os guardas impedem rota nova sem teste, dialeto do Databricks e DDL solto.
- A mesma sequência de escritas dá as mesmas 40 tabelas no Databricks e no Postgres, e o código traduzido continua rodando no app de prod do Databricks.
- O dev da AWS escreve e serve de laboratório. A prod segue só leitura até a virada (2c).
- Próximo: o plano 2b, o publish dentro do app.
