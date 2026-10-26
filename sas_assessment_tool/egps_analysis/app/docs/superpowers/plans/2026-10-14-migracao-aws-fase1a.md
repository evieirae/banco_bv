# Migração para a AWS — Fase 1a (fundação) — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pôr de pé, sem abrir ao BV, a fundação do app na AWS: login do Google pelo load balancer, Postgres com o schema novo, sincronização Databricks → Postgres, backend rodando no Postgres em modo leitura, imagem, CI e as duas instâncias (dev e prod) no ECS Fargate.

**Architecture:** O mesmo código serve o app do Databricks (que segue no ar) e o app na AWS, escolhido por variável de ambiente (`DB_BACKEND`, `IDENTIDADE`, `SOMENTE_LEITURA`). No Postgres, o schema `compat` imita nomes de tabela e funções do Spark (`search_path = compat, derivado, pg_catalog, public`), e o driver devolve cada célula como texto, no formato do Databricks, de modo que o SQL do app e o formato da API não mudam nesta fase. A sincronização é uma tarefa Fargate agendada que lê o Databricks por uma conta de serviço só leitura e grava um retrato completo numa transação só.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3 + psycopg_pool, PyJWT, PostgreSQL 17 (RDS), databricks-sdk 0.108, React/Vite, Terraform (AWS provider ≥ 5), ECS Fargate, ALB `authenticate-oidc` (Google), EventBridge Scheduler, Bitbucket Pipelines.

Spec: [`../specs/2026-10-14-migracao-aws-design.md`](../specs/2026-10-14-migracao-aws-design.md) · ADR: [`docs/adr/0005-app-sai-do-databricks.md`](../../../../../docs/adr/0005-app-sai-do-databricks.md)

---

## Escopo deste plano e dos próximos

| Plano | Conteúdo | Quando escrever |
|---|---|---|
| **1a (este)** | Passo 0 (teste de login, PR mínima na produção) + fundação: migrações, funções Spark, sincronização das 5 primeiras tabelas, backend em modo Postgres (identidade, papéis, só leitura), comparador de leituras, faixa de sincronização no front, **ensaio diário na training**, infra de produção, imagem e CI, subida em dev e prod **fechada ao BV** | agora |
| 1b | De-para das ~40 tabelas restantes + views `compat`, port das rotas GET até a comparação zerar, front sem controles de edição para o leitor, cadastro do BV, critério do JIT | depois do 1a, **a partir da `main` do momento** — o schema antigo ainda muda (`carga_fria`, `sas_gestao_revisao` estão em outras branches) |
| 2 | Escrita no Postgres, publish, scripts, correções de dado, virada | depois do 1b |

**O código dos módulos novos deste plano (db, sync, paridade, treino, dialeto, db_pg, auth_alb) e as migrações 0001–0004 foram executados contra um Postgres 17 em 2026-10-14: 60 testes passando, sem aviso.** Todo o Terraform do plano (passo 0, banco, app completo e o ensaio da training) passou em `terraform validate` e `fmt -check`; o script do ensaio, em `bash -n`. Cobrem migrações, funções Spark, comportamento do schema, papéis de banco, sincronização rodando só com o papel `sincronizador`, sessão baixando para o papel configurado, identidade, driver e comparador. As migrações também rodaram com um usuário mestre **sem superusuário** (como o do RDS), em dois bancos do mesmo servidor: com `SET ROLE app_leitura` a sessão lê e é barrada ao escrever. Um teste pegou um bug real no executor de migrações, já corrigido no texto abaixo. As mudanças no `main.py` (Parte C3–C6) e no front **não** foram executadas: os testes delas estão escritos aqui e rodam na execução.

**Revisado contra a `master` do `indicium_infra` de 2026-10-14 (depois do pull):**
- A conta training é **apagada toda noite** pelo `aws-nuke` (`aws/training-acc/aws-nuke/iam.tf`). Por isso o teste de login (passo 0) roda **na produção**, numa PR mínima. Delegar um subdomínio da produção para uma zona que some toda noite deixaria uma delegação órfã, que é risco de sequestro do subdomínio.
- Banco em root próprio, `aws/production-acc/rds/<app>/`, no molde de `rds/knowledge_hub_mcp`. Segredos seguem o padrão `indicium-infra/<camada>/<serviço>/...`.
- O `indicium-secret-rotation` gira **só a senha do usuário mestre**, a cada 80 dias, e reinicia os serviços. Por isso o app e a sincronização entram como mestre e baixam a sessão para `app_leitura` ou `sincronizador` com `SET ROLE` (`PG_PAPEL`). Não existem usuários de login avulsos com senha parada.
- A VPN agora é a instância `pritunl-node-us`. O `ecs-sg` do load balancer compartilhado libera saída para `0.0.0.0/0`, então o login do Google pelo load balancer funciona.

**Executado em 2026-10-14 (A–E, G1 e T), sobre a `main` `2a303650`.** O texto abaixo já traz o que a execução corrigiu:
- **Collation C.** A primeira comparação real (D1) achou as `areas` na ordem errada: o Spark ordena texto por bytes (`TI` antes de `Teste`, `Ágil` depois de `Zeta`) e o Postgres, pela collation de idioma do banco. O banco do app passa a nascer com `LC_COLLATE 'C'`, que só se escolhe ao criar: `python -m db.migra --cria-banco` cria, e o `migra` recusa banco com outra collation. Por isso o RDS (ensaio e produção) nasce **sem** `db_name`, e os testes criam bancos com `TEMPLATE template0 LC_COLLATE 'C'`. Com isso, a comparação de `/api/config` ficou igual, salvo as diferenças esperadas.
- **Checagem de acesso com o banco fora do ar** respondia 500 com traceback, porque roda no middleware, fora dos handlers do FastAPI. Agora responde o 502 "Falha SQL" das rotas (teste novo na C5).
- **`/api/me` no Databricks** segue `{user}`. O `papel` só aparece no Postgres (havia teste fixando a forma antiga, e a regra é não mudar o app do Databricks).
- **Estilos da faixa** usam os tokens do app (`--panel2`, `--mut`, `--tone-cyc-*`), que mudam com o tema; os do texto original não existem no `styles.css`.
- **`.dockerignore`** ignora `.venv`. O container local alcança o Postgres da preparação por `--network host`, porque o Postgres só escuta em `127.0.0.1`.
- **Linhas citadas** (`main.py:NNN`) são da `main` anterior e andaram: procure pelo nome. Os mesmos 15 `_ensure_*`, e nenhum novo.

## Regras (não negociáveis)

- **Commit e push só quando o usuário pedir.** Mensagem em português, **sem** `Co-Authored-By`. Branch em inglês.
- **Deploy e escrita em prod só com consentimento explícito** do usuário, a cada vez.
- **Bash: um comando por chamada** (regra da organização). Pipe pode; `&&` e `;` não.
- Terraform de **produção** só por PR no `indicium_infra` (plan na branch, apply no merge na `master`, feito pela plataforma). A **training** é o ensaio diário (Parte T): apply local, tudo some à noite, nada de DNS e **nunca com dado do BV**.
- **Ordem das PRs no `indicium_infra`:** o CI aplica os roots alterados em ordem alfabética (`ecs_applications/` antes de `rds/`), e um root que lê outro por `data` quebra o plan se os dois vierem juntos. Por isso cada PR que depende de outra só abre **depois do apply da anterior**: passo 0 → `rds/monitoramento_sas` → app completo → entrada na rotação.
- Credencial nunca em arquivo versionado nem na conversa. Segredo entra no Secrets Manager por arquivo temporário, apagado em seguida.
- Branches: app `feat/aws-migration-phase1a` a partir da `main` mais recente; infra `aws/production-acc/ecs_applications/monitoramento_sas/phase1a` a partir da `master` mais recente; Databricks infra `feat/monitoramento-sas-sync-sp`.

## Mapa de arquivos

**Repo do app** (`egps_analysis/app/`):

| Arquivo | Responsabilidade |
|---|---|
| `backend/dialeto.py` (novo) | Qual banco está em uso + literal de texto nos dois dialetos |
| `backend/db_pg.py` (novo) | Execução no Postgres com o contrato do `run_sql` (células em texto) |
| `backend/auth_alb.py` (novo) | E-mail do usuário a partir do JWT assinado pelo ALB |
| `backend/main.py` (modificar) | Despacho do `run_sql`, `FQ`, `_ensure_*` inertes no PG, identidade e acesso, `/api/config`, filtro do "Com BV" |
| `backend/familias.py`, `backend/egps_atualizados.py` (modificar) | Literais passam por `dialeto.lit` |
| `backend/test_dialeto.py`, `test_db_pg.py`, `test_auth_alb.py`, `test_acesso_pg.py` (novos) | Testes |
| `db/__init__.py`, `db/migra.py`, `db/test_migra.py`, `db/test_schema.py` (novos) | Executor de migrações e testes do schema |
| `db/migrations/0001_schema_inicial.sql` … `0004_papeis_banco.sql` (novos) | Schema, funções Spark, ajuste da view, papéis de banco |
| `sync/__init__.py`, `leitor.py`, `mapeamento.py`, `retrato.py`, `carrega.py`, `sincroniza.py`, `test_sync.py` (novos) | Sincronização Databricks → Postgres |
| `paridade/__init__.py`, `compara.py`, `test_compara.py` (novos) | Comparador de leituras antigo × novo |
| `sync/sintetico.py`, `sync/test_sintetico.py` (novos) | Massa sintética do ensaio (mesmo caminho da sincronização real) |
| `treino/fumaca.py`, `treino/test_fumaca.py`, `treino/sobe_treino.sh`, `treino/terraform/*.tf` (novos) | Ensaio diário na training: teste de fumaça, script e infra descartável |
| `frontend/src/types.ts`, `App.tsx`, `styles.css`, `components/SincronizacaoBanner.tsx` | Faixa de sincronização e tela "sem acesso" |
| `Dockerfile`, `.dockerignore` (novos) | Imagem única: app e sincronização |
| `requirements.txt` (modificar) | psycopg, psycopg_pool, PyJWT, cryptography |
| `bitbucket-pipelines.yml` (raiz, modificar) | Postgres nos testes; build, push e deploy na AWS |

**Repo `indicium_infra`:**
- `aws/production-acc/ecs_applications/monitoramento_sas/` — app, sincronização, regra de login no ALB, ECR, alarme (nasce no passo 0)
- `aws/production-acc/rds/monitoramento_sas/` — banco, SG de clientes, segredo `indicium-infra/rds/monitoramento-sas/credentials`
- `aws/production-acc/lambda/secret-rotation/variables.tf` — entrada na rotação
- `aws/production-acc/IAM/service_accounts.auto.tfvars` + política — conta de deploy

**Repo `indicium_databricks_aws_infra`:** `configs/principal_configs.yml` (conta de serviço da sincronização).

## Decisões de implementação desta fase

1. **Um código, dois bancos.** `DB_BACKEND=databricks|postgres` (padrão `databricks`), `IDENTIDADE=obo|alb|dev` (padrão `obo`), `SOMENTE_LEITURA=1`. O app do Databricks continua recebendo o mesmo código e não muda de comportamento.
2. **O Postgres fala Spark o suficiente.** Funções com nome do Spark no schema `compat` sombreiam as do sistema (verificado: `regexp_replace` passa a trocar todas as ocorrências). Domínios `string` e `double` fazem `CAST(x AS STRING)` funcionar. O que não dá para imitar (`current_timestamp()` com parênteses, lambda, `ARRAY` literal, `NULLS` na ordenação, divisão inteira) é reescrito na 1b, rota a rota, guiado pela comparação.
3. **Célula volta como texto** no formato do Databricks. A API não muda na Fase 1.
4. **Sincronização fiel.** Nenhuma correção de dado: as correções são da Fase 2. Âncora citada por um par mas ausente vira órfã. Pessoa referenciada e não cadastrada entra em `cadastro.usuario` **inativa**: a sincronização nunca dá acesso.
5. **Acesso no Postgres decidido num lugar só:** um middleware recusa quem não está ativo em `cadastro.usuario` e recusa qualquer método de escrita quando `SOMENTE_LEITURA=1` ou o papel é `leitor`. Isso cobre as 28 rotas de escrita sem tocar nelas, e um teste percorre todas.

## Preparação local (uma vez)

- [ ] Subir um Postgres 17 descartável (só local):

```bash
docker run -d --name pg17-monitoramento -e POSTGRES_HOST_AUTH_METHOD=trust -p 127.0.0.1:55432:5432 postgres:17
```

```bash
docker exec pg17-monitoramento pg_isready -U postgres
```

Esperado: `accepting connections`. Nos testes abaixo, `PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres`: cada teste cria o seu banco, com collation C. O app local (B3, D1, G1) usa o banco `monitoramento`, criado por `python -m db.migra --cria-banco`.

---

## Passo 0 — Teste de login (PR mínima na produção)

Objetivo: provar, **antes de qualquer outra coisa**, que uma conta `@bv.com.br` passa pelo login do Google num app novo da Indicium. Sem app e sem dado: o load balancer compartilhado responde uma página fixa depois do login. A regra nasce no root definitivo do app (`ecs_applications/monitoramento_sas/`) e, na Parte F, o "página fixa" vira "encaminhar para o app".

Por que não na training: ela é apagada toda noite (`aws/training-acc/aws-nuke/`). O login precisa de HTTPS num domínio com certificado válido, e a zona `hub.indicium.ai` é da produção. Delegar um subdomínio para uma zona que some à noite deixaria uma delegação órfã.

> **Estado em 2026-10-14:** a branch `aws/production-acc/ecs_applications/monitoramento_sas/login-test` do `indicium_infra` está pronta, com `validate`, `tflint` e pre-commit verdes, prioridade 150 e commit local. O plan da PR só passa depois da Task 0.1, porque lê o segredo.

### Task 0.1: Cadastro OAuth no Google da Indicium (manual, time de plataforma)

- [ ] No Google Cloud da organização `indicium.ai` (projeto indicado pela plataforma), em **APIs & Services → OAuth consent screen**: tipo **External**; nome "Monitoramento SAS"; escopos só `openid` e `email`; status **In production**. Com só esses escopos não há verificação do Google. Em modo de teste, só os "test users" entrariam.
- [ ] Em **Credentials → Create OAuth client ID → Web application**, cadastre estas URIs de redirecionamento autorizadas:
  - `https://monitoramento-sas.hub.indicium.ai/oauth2/idpresponse`
  - `https://monitoramento-sas-dev.hub.indicium.ai/oauth2/idpresponse`
- [ ] Guarde o client no Secrets Manager da produção, sem o segredo passar pelo histórico do shell:

```bash
aws secretsmanager create-secret --profile indicium --name indicium-infra/ecs/monitoramento-sas/google-oauth --secret-string file://google-oauth.json
```

`google-oauth.json` = `{"client_id": "...", "client_secret": "..."}`, criado e apagado à mão (`shred -u google-oauth.json`). As chaves não são `db_password` nem `access_token`, então o `indicium-secret-rotation` não mexe nele.

### Task 0.2: Root do app com a regra de login e página fixa

**Files** (em `indicium_infra/aws/production-acc/ecs_applications/monitoramento_sas/`):
- Create: `provider.tf`, `data.tf`, `alb.tf`

- [ ] **Step 1: provider.tf** (molde de `rds/knowledge_hub_mcp/provider.tf`)

```hcl
provider "aws" {
  profile = "indicium"
  region  = "us-east-1"

  default_tags {
    tags = {
      Company = "IndiciumTech"
    }
  }
}

terraform {
  # >= 1.10 pelo use_lockfile (trava nativa do S3), como lambda/indiguesser.
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    profile      = "indicium"
    bucket       = "indicium-data"
    key          = "deploy/terraform/ecs_applications/monitoramento_sas.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

- [ ] **Step 2: data.tf** (versão do passo 0; a Parte F acrescenta o resto)

```hcl
data "aws_lb" "indicium_lb" {
  name = "tf-load-balancer"
}

data "aws_lb_listener" "tf_lb_https" {
  load_balancer_arn = data.aws_lb.indicium_lb.arn
  port              = 443
}

data "aws_route53_zone" "hub" {
  name = "hub.indicium.ai."
}

# Criado À MÃO (Task 0.1): o segredo nunca passa pelo Terraform de quem cria.
data "aws_secretsmanager_secret_version" "google_oauth" {
  secret_id = "indicium-infra/ecs/monitoramento-sas/google-oauth"
}

locals {
  host_prod    = "monitoramento-sas.hub.indicium.ai"
  google_oauth = jsondecode(data.aws_secretsmanager_secret_version.google_oauth.secret_string)
}
```

- [ ] **Step 3: Conferir a prioridade livre no listener**

```bash
aws elbv2 describe-rules --profile indicium --listener-arn "$(aws elbv2 describe-listeners --profile indicium --load-balancer-arn "$(aws elbv2 describe-load-balancers --profile indicium --names tf-load-balancer --query 'LoadBalancers[0].LoadBalancerArn' --output text)" --query 'Listeners[?Port==`443`].ListenerArn' --output text)" --query "Rules[].Priority"
```

Escolha uma prioridade livre para prod e outra para dev. O padrão abaixo é 150 e 151: a 140 já é do `lambda/budget-mcp` (achado em 2026-10-14). Tomadas no repo nessa data: 10–13, 20–23, 28–33, 40–42, 45–46, 50–52, 60, 70, 99–105, 107–108, 110–120, 129–131, 140 e 500. O plan da PR não pega colisão de prioridade, só o apply.

- [ ] **Step 4: alb.tf** (versão do passo 0)

```hcl
resource "aws_acm_certificate" "app" {
  domain_name               = local.host_prod
  subject_alternative_names = ["monitoramento-sas-dev.hub.indicium.ai"]
  validation_method         = "DNS"
  lifecycle { create_before_destroy = true }
  tags = { ManagedBy = "Terraform" }
}

resource "aws_route53_record" "cert" {
  for_each = { for d in aws_acm_certificate.app.domain_validation_options : d.domain_name => d }
  zone_id  = data.aws_route53_zone.hub.zone_id
  name     = each.value.resource_record_name
  type     = each.value.resource_record_type
  ttl      = 60
  records  = [each.value.resource_record_value]
}

resource "aws_acm_certificate_validation" "app" {
  certificate_arn         = aws_acm_certificate.app.arn
  validation_record_fqdns = [for r in aws_route53_record.cert : r.fqdn]
}

resource "aws_lb_listener_certificate" "app" {
  listener_arn    = data.aws_lb_listener.tf_lb_https.arn
  certificate_arn = aws_acm_certificate_validation.app.certificate_arn
}

# PASSO 0: login do Google e página fixa. A Parte F troca a 2ª ação por "forward" ao app.
# Público e protegido por LOGIN, não por IP como os outros apps deste ALB: o BV entra de
# fora da VPN.
resource "aws_lb_listener_rule" "teste_login" {
  listener_arn = data.aws_lb_listener.tf_lb_https.arn
  priority     = 150

  action {
    type  = "authenticate-oidc"
    order = 1
    authenticate_oidc {
      authorization_endpoint     = "https://accounts.google.com/o/oauth2/v2/auth"
      token_endpoint             = "https://oauth2.googleapis.com/token"
      user_info_endpoint         = "https://openidconnect.googleapis.com/v1/userinfo"
      issuer                     = "https://accounts.google.com"
      client_id                  = local.google_oauth.client_id
      client_secret              = local.google_oauth.client_secret
      scope                      = "openid email"
      session_timeout            = 28800
      on_unauthenticated_request = "authenticate"
    }
  }

  action {
    type  = "fixed-response"
    order = 2
    fixed_response {
      content_type = "text/plain"
      message_body = "login ok - monitoramento-sas (teste do passo 0)"
      status_code  = "200"
    }
  }

  condition {
    host_header {
      values = [local.host_prod]
    }
  }

  tags = { ManagedBy = "Terraform" }
}

resource "aws_route53_record" "prod" {
  zone_id = data.aws_route53_zone.hub.zone_id
  name    = local.host_prod
  type    = "A"
  alias {
    name                   = data.aws_lb.indicium_lb.dns_name
    zone_id                = data.aws_lb.indicium_lb.zone_id
    evaluate_target_health = false
  }
}
```

- [ ] **Step 5: Validar e abrir a PR** (`aws/production-acc/ecs_applications/monitoramento_sas/login-test`)

```bash
terraform -chdir=aws/production-acc/ecs_applications/monitoramento_sas init -backend=false
```

```bash
terraform -chdir=aws/production-acc/ecs_applications/monitoramento_sas validate
```

```bash
make -C ~/indicium/indicium_infra hooks
```

Esperado: `Success! The configuration is valid.` e os hooks verdes. O plano da PR deve mostrar 1 certificado, os registros de validação, 1 certificado no listener, 1 regra e 1 registro A. O apply é da plataforma, no merge.

### Task 0.3: O teste

- [ ] Numa janela anônima, abra `https://monitoramento-sas.hub.indicium.ai` e entre com a conta **@bv.com.br**. Esperado: a página `login ok - monitoramento-sas (teste do passo 0)`.
- [ ] Repita com uma conta **@indicium.ai**. Esperado: o mesmo.
- [ ] Registre o resultado na spec (seção Riscos).
- [ ] **Portão:** se a conta do BV for recusada pelo Google (por exemplo `admin_policy_enforced`), **pare o plano** e leve ao usuário. Caminhos, nesta ordem: pedir à TI do BV que confie no client id; ou **Cognito com e-mail e senha** na regra do ALB (`authenticate-cognito`), combinado com a plataforma. O "não adicione Cognito" do README do Knowledge Hub vale **para aquele root**, não é regra geral. O Google pode ser ligado ao mesmo Cognito depois, sem mudar o app.

---

## Parte A — Banco: migrações, schema e funções Spark

### Task A1: Executor de migrações

**Files:**
- Create: `egps_analysis/app/db/__init__.py` (vazio)
- Create: `egps_analysis/app/db/migra.py`
- Test: `egps_analysis/app/db/test_migra.py`

- [ ] **Step 1: Dependências.** Em `egps_analysis/app/requirements.txt`, acrescente:

```text
# Postgres na AWS (ADR 0005): driver, pool e o JWT do login do load balancer
psycopg[binary]==3.2.*
psycopg-pool==3.2.*
PyJWT==2.*
cryptography>=43
```

```bash
pip install -r egps_analysis/app/requirements.txt
```

- [ ] **Step 2: Escrever o teste** `db/test_migra.py`

```python
# -*- coding: utf-8 -*-
"""Executor de migrações: ordem, idempotência e rollback do arquivo que falha."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import migra  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
pytestmark = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")


@pytest.fixture
def banco_limpo():
    """Banco descartável por teste (CREATE DATABASE não roda dentro de transação)."""
    import psycopg
    nome = "t_migra_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    yield f"{base}/{nome}"
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def test_aplica_em_ordem_e_e_idempotente(tmp_path, banco_limpo):
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (x int);")
    (tmp_path / "0002_b.sql").write_text("INSERT INTO a VALUES (1); INSERT INTO a VALUES (2);")
    assert migra.aplica(banco_limpo, tmp_path, saida=lambda *_: None) == 2
    assert migra.aplica(banco_limpo, tmp_path, saida=lambda *_: None) == 0


def test_arquivo_que_falha_nao_deixa_rastro(tmp_path, banco_limpo):
    import psycopg
    (tmp_path / "0001_ok.sql").write_text("CREATE TABLE ok (x int);")
    (tmp_path / "0002_quebra.sql").write_text("CREATE TABLE meia (x int); SELECT 1/0;")
    with pytest.raises(psycopg.Error):
        migra.aplica(banco_limpo, tmp_path, saida=lambda *_: None)
    with psycopg.connect(banco_limpo) as c:
        assert c.execute("SELECT to_regclass('public.meia')").fetchone()[0] is None
        assert {r[0] for r in c.execute("SELECT versao FROM schema_migracao")} == {"0001"}


def test_banco_sem_collation_c_e_recusado(tmp_path):
    """O app ordena texto como o Spark (bytes). Banco com collation de idioma ordenaria
    `TI`/`Teste`, `Ágil`/`Zeta` diferente — e a diferença só apareceria na comparação."""
    import psycopg
    nome = "t_migra_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'en_US.utf8'")
    base, _, _ = DSN.rpartition("/")
    try:
        (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (x int);")
        with pytest.raises(SystemExit, match="collation"):
            migra.aplica(f"{base}/{nome}", tmp_path, saida=lambda *_: None)
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def test_cria_banco_com_collation_c_e_idempotente():
    import psycopg
    nome = "t_migra_" + uuid.uuid4().hex[:8]
    base, _, _ = DSN.rpartition("/")
    try:
        assert migra.cria_banco(f"{base}/{nome}", saida=lambda *_: None) is True
        assert migra.cria_banco(f"{base}/{nome}", saida=lambda *_: None) is False
        with psycopg.connect(f"{base}/{nome}") as c:
            assert c.execute("SELECT datcollate FROM pg_database "
                             "WHERE datname = current_database()").fetchone()[0] == "C"
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {nome} WITH (FORCE)")


def test_nome_fora_do_padrao_e_recusado(tmp_path):
    (tmp_path / "1_sem_zero.sql").write_text("SELECT 1;")
    with pytest.raises(SystemExit, match="padrão"):
        migra.arquivos(tmp_path)
```

- [ ] **Step 3: Rodar e ver falhar**

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest -q egps_analysis/app/db/test_migra.py
```

Esperado: erro de import (`cannot import name 'migra'`).

- [ ] **Step 4: Implementar** `db/migra.py`

```python
# -*- coding: utf-8 -*-
"""Aplica as migrações numeradas de db/migrations, em ordem (ADR 0005).

Cada arquivo roda numa transação; a versão só é registrada se o arquivo inteiro passou.
Tabela ou coluna nova no app só entra com a migração correspondente — os `_ensure_*` e as
sondas ALTER ADD COLUMNS do tempo do Databricks não rodam no Postgres.

O banco tem de ter collation "C": o Spark ordena texto por bytes (`TI` antes de `Teste`,
`Ágil` depois de `Zeta`), e o app no Postgres precisa devolver as listas na mesma ordem.
A collation só se escolhe ao CRIAR o banco — por isso o RDS nasce sem banco do app e
`--cria-banco` o cria (o `db_name` do Terraform usaria a collation de idioma da instância).

Uso:  PG_DSN=postgresql://... python -m db.migra               aplica as pendentes
      PG_DSN=postgresql://... python -m db.migra --cria-banco  cria o banco (collation C), se
                                                               faltar, e aplica as pendentes
      PG_DSN=postgresql://... python -m db.migra --status      lista aplicadas e pendentes
"""
import argparse
import os
import pathlib
import re
import sys

import psycopg
from psycopg import conninfo, sql

PASTA = pathlib.Path(__file__).with_name("migrations")
_NOME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
COLLATION = "C"


def arquivos(pasta=PASTA):
    achados = []
    for p in sorted(pathlib.Path(pasta).glob("*.sql")):
        m = _NOME.match(p.name)
        if not m:
            raise SystemExit(f"nome de migração fora do padrão NNNN_nome.sql: {p.name}")
        achados.append((m.group(1), p))
    versoes = [v for v, _ in achados]
    if len(versoes) != len(set(versoes)):
        raise SystemExit(f"versão repetida em {pasta}: {versoes}")
    return achados


def cria_banco(dsn, saida=print):
    """Cria o banco do DSN com collation C, conectando no banco `postgres` do mesmo servidor.
    True se criou, False se já existia (a collation do existente é conferida pelo `aplica`)."""
    partes = conninfo.conninfo_to_dict(dsn)
    nome = partes.get("dbname")
    if not nome:
        raise SystemExit("PG_DSN sem dbname: não sei que banco criar")
    with psycopg.connect(conninfo.make_conninfo(dsn, dbname="postgres"), autocommit=True) as c:
        if c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nome,)).fetchone():
            saida(f"[migra] banco {nome} já existe")
            return False
        c.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 LC_COLLATE {}").format(
            sql.Identifier(nome), sql.Literal(COLLATION)))
    saida(f"[migra] banco {nome} criado (collation {COLLATION})")
    return True


def _confere_collation(conn):
    nome, col = conn.execute("SELECT datname, datcollate FROM pg_database "
                             "WHERE datname = current_database()").fetchone()
    if col != COLLATION:
        raise SystemExit(f"banco {nome} com collation {col!r}; o app precisa de {COLLATION!r} "
                         f"(ordem de bytes, como o Spark). Recrie com --cria-banco.")


def _garante_controle(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migracao ("
                 "versao text PRIMARY KEY, arquivo text NOT NULL, "
                 "aplicada_em timestamptz NOT NULL DEFAULT now())")


def aplicadas(conn):
    return {r[0] for r in conn.execute("SELECT versao FROM public.schema_migracao")}


def aplica(dsn, pasta=PASTA, saida=print):
    # autocommit é obrigatório: sem ele o SELECT de `aplicadas` abre uma transação
    # implícita, cada `conn.transaction()` vira SAVEPOINT dentro dela, e a falha de um
    # arquivo desfaz também os anteriores (pego pelo test_arquivo_que_falha_nao_deixa_rastro).
    with psycopg.connect(dsn, autocommit=True) as conn:
        _confere_collation(conn)
        _garante_controle(conn)
        feitas = aplicadas(conn)
        novas = 0
        for versao, caminho in arquivos(pasta):
            if versao in feitas:
                continue
            with conn.transaction():
                conn.execute(caminho.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO public.schema_migracao (versao, arquivo) VALUES (%s, %s)",
                             (versao, caminho.name))
            saida(f"[migra] aplicada {caminho.name}")
            novas += 1
        saida(f"[migra] {novas} nova(s); {len(feitas) + novas} no total")
        return novas


def status(dsn, pasta=PASTA, saida=print):
    with psycopg.connect(dsn, autocommit=True) as conn:
        _garante_controle(conn)
        feitas = aplicadas(conn)
    for versao, caminho in arquivos(pasta):
        saida(f"{'aplicada' if versao in feitas else 'PENDENTE'}  {caminho.name}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--cria-banco", action="store_true")
    args = ap.parse_args(argv)
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        sys.exit("PG_DSN não definido")
    if args.cria_banco:
        cria_banco(dsn)
    (status if args.status else aplica)(dsn)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Rodar e ver passar** (mesmo comando do Step 3). Esperado: `5 passed`.

- [ ] **Step 6: Checkpoint de commit** (só se o usuário pedir): `feat(app): executor de migrações do Postgres`.

### Task A2: Schema inicial, funções Spark e ajuste da view

**Files:**
- Create: `egps_analysis/app/db/migrations/0001_schema_inicial.sql` (gerado da spec)
- Create: `egps_analysis/app/db/migrations/0002_compat_funcoes.sql`
- Create: `egps_analysis/app/db/migrations/0003_compat_sentinela_publish.sql`
- Test: `egps_analysis/app/db/test_schema.py`

- [ ] **Step 1: Gerar a 0001 a partir do DDL validado da spec**, tirando as linhas de controle de transação (o executor já abre uma):

```bash
sed -e "/^BEGIN;$/d" -e "/^ROLLBACK;/d" egps_analysis/app/docs/superpowers/specs/2026-10-14-migracao-aws-schema.sql > egps_analysis/app/db/migrations/0001_schema_inicial.sql
```

```bash
grep -c "^BEGIN;$" egps_analysis/app/db/migrations/0001_schema_inicial.sql
```

Esperado: `0`. O `BEGIN` sem ponto e vírgula, dentro do corpo de `cadastro.carimba()`, fica.

- [ ] **Step 2: Escrever o teste** `db/test_schema.py`

```python
# -*- coding: utf-8 -*-
"""Migrações aplicadas num banco limpo: comportamento do schema e das funções Spark."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import migra  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
pytestmark = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")


@pytest.fixture(scope="module")
def conn():
    import psycopg
    nome = "t_schema_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    dsn = f"{base}/{nome}"
    migra.aplica(dsn, saida=lambda *_: None)
    c = psycopg.connect(dsn, autocommit=True)
    c.execute("SET search_path = compat, derivado, pg_catalog, public")
    c.execute("SELECT set_config('app.usuario', 'teste@indicium.ai', false)")
    yield c
    c.close()
    with psycopg.connect(DSN, autocommit=True) as c2:
        c2.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def _um(conn, sql):
    return conn.execute(sql).fetchone()[0]


@pytest.mark.parametrize("sql, esperado", [
    ("SELECT CAST(42 AS STRING)", "42"),
    ("SELECT CAST('1.5' AS DOUBLE)", 1.5),
    ("SELECT split('a|b|c', '[|]')", ["a", "b", "c"]),
    ("SELECT element_at(split('a|b', '[|]'), 1)", "a"),
    ("SELECT array_contains(split('a|b', '[|]'), 'b')", True),
    ("SELECT arrays_overlap(split('a|b', '[|]'), split('c|b', '[|]'))", True),
    ("SELECT size(split('a|b', '[|]'))", 2),
    ("SELECT regexp_replace('a-b-c', '-', '')", "abc"),
    ("SELECT count_if(x > 1) FROM (VALUES (1), (2), (3)) t(x)", 2),
    ("SELECT date_format(timestamptz '2026-10-14 15:04:05+00', 'yyyy-MM-dd')", "2026-10-14"),
    ("SELECT date_format(date '2026-10-14', 'yyyy-MM')", "2026-10"),
    ("SELECT date_format(from_utc_timestamp(timestamptz '2026-10-14 02:00+00', 'America/Sao_Paulo'), 'yyyy-MM-dd')",
     "2026-10-13"),
    ("SELECT count(*) FROM (SELECT explode(split('a|b|c', '[|]')) AS x) t", 3),
])
def test_funcoes_spark(conn, sql, esperado):
    assert _um(conn, sql) == esperado


def test_ancora_com_estado_humano_nao_se_apaga_e_rekey_propaga(conn):
    import psycopg
    conn.execute("INSERT INTO corpus.egp (projeto) VALUES ('Area__EGP_A')")
    conn.execute("INSERT INTO corpus.input (chave, categoria, artefato) VALUES ('tabela::LIB.T', 'tabela', 'LIB.T')")
    conn.execute("INSERT INTO trabalho.leitura_dispensada (projeto, input_chave) VALUES ('Area__EGP_A', 'tabela::LIB.T')")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("DELETE FROM corpus.input WHERE chave = 'tabela::LIB.T'")
    conn.execute("UPDATE corpus.input SET chave = 'tabela::LIB.T2', artefato = 'LIB.T2' WHERE chave = 'tabela::LIB.T'")
    assert _um(conn, "SELECT input_chave FROM trabalho.leitura_dispensada") == "tabela::LIB.T2"
    assert _um(conn, "SELECT atualizado_por FROM trabalho.leitura_dispensada") == "teste@indicium.ai"


def test_comentario_tem_um_alvo_so(conn):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO trabalho.gestao_comentario (projeto, input_chave, autor, texto) "
                     "VALUES ('Area__EGP_A', 'tabela::LIB.T2', 'a@indicium.ai', 'x')")


def test_prefixo_da_chave_bate_com_a_categoria(conn):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO corpus.input (chave, categoria, artefato) VALUES ('arquivo::X', 'tabela', 'X')")
```

- [ ] **Step 3: Rodar e ver falhar**

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest -q egps_analysis/app/db/test_schema.py
```

Esperado: os testes de função falham (`function split(unknown, unknown) does not exist` etc.); os de comportamento passam, porque a 0001 já existe.

- [ ] **Step 4: Escrever** `db/migrations/0002_compat_funcoes.sql`

```sql
-- Funções e tipos com nome e semântica do Spark SQL, no schema compat (ADR 0005, Fase 1).
--
-- Na Fase 1 o mesmo SQL do backend roda no Databricks e no Postgres. O app conecta com
-- search_path = compat, derivado, pg_catalog, public: como compat vem ANTES de pg_catalog,
-- uma função daqui com a mesma assinatura de uma do sistema a SOMBREIA (verificado no PG 17).
-- Só entra aqui o que o backend usa de fato; o que não dá para imitar (current_timestamp()
-- com parênteses, lambda, ARRAY literal) é reescrito no código para a forma que roda nos dois.
-- Some na Fase 2, quando o SQL passa a ser só Postgres.

-- CAST(x AS STRING) / CAST(x AS DOUBLE)
CREATE DOMAIN compat.string AS text;
CREATE DOMAIN compat.double AS double precision;

-- split(str, regex) -> array (Spark usa regex no separador, como regexp_split_to_array)
CREATE FUNCTION compat.split(text, text) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $$ SELECT regexp_split_to_array($1, $2) $$;

-- explode(array) no SELECT -> uma linha por elemento
CREATE FUNCTION compat.explode(anyarray) RETURNS SETOF anyelement
LANGUAGE sql IMMUTABLE AS $$ SELECT unnest($1) $$;

-- element_at(array, n): índice a partir de 1 nos DOIS bancos (no Spark, arr[0] é base 0 e
-- no Postgres arr[1] é base 1 — por isso o código usa element_at, nunca colchete)
CREATE FUNCTION compat.element_at(anyarray, integer) RETURNS anyelement
LANGUAGE sql IMMUTABLE AS $$ SELECT $1[$2] $$;

CREATE FUNCTION compat.array_contains(anyarray, anyelement) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$ SELECT $2 = ANY($1) $$;

CREATE FUNCTION compat.arrays_overlap(anyarray, anyarray) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$ SELECT $1 && $2 $$;

CREATE FUNCTION compat.size(anyarray) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$ SELECT coalesce(cardinality($1), -1) $$;

-- regexp_replace do Spark troca TODAS as ocorrências; o do Postgres só a primeira sem 'g'
CREATE FUNCTION compat.regexp_replace(text, text, text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT pg_catalog.regexp_replace($1, $2, $3, 'g') $$;

-- count_if(cond)
CREATE FUNCTION compat._count_if_passo(bigint, boolean) RETURNS bigint
LANGUAGE sql IMMUTABLE AS $$ SELECT $1 + CASE WHEN $2 THEN 1 ELSE 0 END $$;
CREATE AGGREGATE compat.count_if(boolean) (SFUNC = compat._count_if_passo, STYPE = bigint, INITCOND = '0');

-- from_utc_timestamp(ts, tz): o instante visto no fuso tz (sem fuso no resultado)
CREATE FUNCTION compat.from_utc_timestamp(timestamptz, text) RETURNS timestamp
LANGUAGE sql STABLE AS $$ SELECT $1 AT TIME ZONE $2 $$;

-- date_format(ts, padrão Java) — só os pedaços que o backend usa (yyyy, MM, dd, HH, mm, ss)
CREATE FUNCTION compat._padrao_java(text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT replace(replace(replace(replace(replace(replace($1,
         'yyyy', 'YYYY'), 'dd', 'DD'), 'HH', 'HH24'), 'mm', 'MI'), 'ss', 'SS'), 'MM', 'MM')
$$;
CREATE FUNCTION compat.date_format(timestamptz, text) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT to_char($1, compat._padrao_java($2)) $$;
CREATE FUNCTION compat.date_format(timestamp, text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT to_char($1, compat._padrao_java($2)) $$;
CREATE FUNCTION compat.date_format(date, text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT to_char($1, compat._padrao_java($2)) $$;
```

- [ ] **Step 5: Escrever** `db/migrations/0003_compat_sentinela_publish.sql`

```sql
-- compat.sas_inputs_monitor devolve updated_at/updated_by NULOS quando ninguém editou o
-- input (a sincronização grava atualizado_por = 'publish' — ver sync/mapeamento.py), como
-- o Databricks devolvia. Sem isso a comparação de leituras acusaria 11 mil diferenças falsas.
CREATE OR REPLACE VIEW compat.sas_inputs_monitor AS
SELECT i.chave                                  AS chave_canonica,
       i.artefato                               AS artifact,
       i.categoria,
       i.origem,
       array_to_string(i.source_types, ' | ')   AS source_types,
       i.qtd_projetos,
       array_to_string(i.areas, ' | ')          AS areas,
       ve.escopo_indi,
       CASE WHEN i.disponivel_auto THEN 'Disponível' ELSE 'A ingerir' END AS modernizada_auto,
       array_to_string(i.paths_fisicos, ' | ')  AS paths_fisicos,
       i.n_paths_fisicos,
       s.etapa, s.status, s.responsavel, s.observacao,
       CASE WHEN s.atualizado_por = 'publish' THEN NULL ELSE s.atualizado_em END AS updated_at,
       nullif(s.atualizado_por, 'publish')      AS updated_by,
       i.orfao,
       i.publicado_em                           AS refreshed_at
FROM corpus.input i
LEFT JOIN trabalho.estado_input s   ON s.chave = i.chave
LEFT JOIN derivado.v_input_escopo ve ON ve.chave = i.chave;
```

- [ ] **Step 6: Rodar e ver passar** (comando do Step 3). Esperado: `16 passed`.

- [ ] **Step 7: Checkpoint de commit** (só se pedido): `feat(app): schema inicial do Postgres e funções Spark`.

### Task A3: Papéis de banco

**Files:**
- Create: `egps_analysis/app/db/migrations/0004_papeis_banco.sql`
- Modify: `egps_analysis/app/db/test_schema.py` (acrescentar teste)

- [ ] **Step 1: Teste que falha** (acrescente ao fim de `test_schema.py`):

```python
def test_papel_de_leitura_nao_escreve(conn):
    import psycopg
    conn.execute("CREATE ROLE t_leitor LOGIN IN ROLE app_leitura")
    try:
        conn.execute("SET ROLE t_leitor")
        assert _um(conn, "SELECT count(*) FROM corpus.egp") >= 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO corpus.egp (projeto) VALUES ('x__y')")
    finally:
        conn.execute("RESET ROLE")
        conn.execute("DROP ROLE t_leitor")
```

- [ ] **Step 2: Rodar e ver falhar**: `role "app_leitura" does not exist`.

- [ ] **Step 3: Escrever** `db/migrations/0004_papeis_banco.sql`

```sql
-- Papéis de banco (ADR 0005), sem LOGIN: a sessão do mestre baixa para eles com SET ROLE.
--   app_leitura  — app na Fase 1 (prod): só lê.
--   sincronizador — tarefa de sincronização da Fase 1: regrava corpus/trabalho, acrescenta
--                   em cadastro.usuario e historico.publicacao.
-- Na Fase 2 entram app_escrita e publicador (esboço no fim do DDL da spec).
-- Papéis são do CLUSTER, não do banco: o IF NOT EXISTS deixa dev e prod no mesmo RDS.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_leitura') THEN
    CREATE ROLE app_leitura NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sincronizador') THEN
    CREATE ROLE sincronizador NOLOGIN;
  END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA cadastro, corpus, trabalho, historico, atualizados, derivado, compat
  TO app_leitura, sincronizador;
GRANT SELECT ON ALL TABLES IN SCHEMA cadastro, corpus, trabalho, historico, atualizados, derivado, compat
  TO app_leitura, sincronizador;
GRANT SELECT ON public.schema_migracao TO app_leitura, sincronizador;

GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA corpus, trabalho TO sincronizador;
GRANT INSERT, UPDATE ON cadastro.usuario TO sincronizador;
GRANT INSERT ON historico.publicacao TO sincronizador;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA historico TO sincronizador;

-- O app e a sincronização entram com o usuário MESTRE (o único que o indicium-secret-rotation
-- gira, a cada 80 dias) e fazem SET ROLE para o papel da sessão: o mestre precisa ser membro.
-- CURRENT_USER = quem roda as migrações = o mestre.
GRANT app_leitura, sincronizador TO CURRENT_USER;

-- Tabelas e views das PRÓXIMAS migrações (rodadas pelo mesmo usuário que rodou esta)
-- nascem legíveis pelos dois papéis — sem isso, a 0005 em diante quebraria o app em silêncio.
ALTER DEFAULT PRIVILEGES IN SCHEMA cadastro, corpus, trabalho, historico, atualizados, derivado, compat
  GRANT SELECT ON TABLES TO app_leitura, sincronizador;
```

- [ ] **Step 4: Rodar e ver passar.** Esperado: `17 passed`.

- [ ] **Step 5: Checkpoint de commit** (só se pedido): `feat(app): papéis de banco app_leitura e sincronizador`.

---

## Parte B — Sincronização Databricks → Postgres (5 tabelas)

Tabelas desta fatia: `sas_lineage_nodes` → `corpus.egp`; `sas_inputs_monitor` → `corpus.input` + `trabalho.estado_input`; `sas_egp_inputs` → `corpus.egp_input`; `sas_escopo` → `trabalho.escopo_item`; `sas_analistas` → `cadastro.usuario`. Valores conferidos em prod em 2026-10-14: `modernizada_auto` ∈ {`A ingerir`, `Disponível`}; `categoria` ∈ {`tabela`, `arquivo`, `script`}; `origem` do escopo ∈ {`csv`, `manual`, `casca`}; etapas e status todos dentro do vocabulário; `responsavel` vazio ou e-mail em minúsculas.

### Task B1: Leitor e de-para

**Files:**
- Create: `egps_analysis/app/sync/__init__.py` (vazio)
- Create: `egps_analysis/app/sync/leitor.py`
- Create: `egps_analysis/app/sync/mapeamento.py`
- Test: `egps_analysis/app/sync/test_sync.py`

- [ ] **Step 1: Escrever o teste** `sync/test_sync.py` (os testes de carga entram na B2, no mesmo arquivo)

```python
# -*- coding: utf-8 -*-
"""Sincronização: leitura sem truncar, de-para fiel e carga atômica com âncoras completas."""
import os
import sys
import uuid
from types import SimpleNamespace as NS

import pytest
from databricks.sdk.service.sql import StatementState

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import migra  # noqa: E402
from sync import leitor, mapeamento as mp  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
precisa_pg = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")


# ---------------------------------------------------------------- leitor
class _Execucao:
    def __init__(self, chunks, total):
        self._chunks, self._total = chunks, total

    def _chunk(self, i):
        prox = i + 1 if i + 1 < len(self._chunks) else None
        return NS(data_array=self._chunks[i], next_chunk_index=prox)

    def execute_statement(self, **_):
        return NS(statement_id="s1", status=NS(state=StatementState.SUCCEEDED, error=None),
                  result=self._chunk(0), manifest=NS(total_row_count=self._total))

    def get_statement_result_chunk_n(self, sid, i):
        return self._chunk(i)


def test_leitor_segue_todos_os_chunks():
    w = NS(statement_execution=_Execucao([[["a"]], [["b"]], [["c"]]], 3))
    assert leitor.le_tabela(w, "wh", "x.y", ["c"]) == [{"c": "a"}, {"c": "b"}, {"c": "c"}]


def test_leitor_falha_alto_se_o_total_nao_bate():
    w = NS(statement_execution=_Execucao([[["a"]]], 2))
    with pytest.raises(RuntimeError, match="truncamento"):
        leitor.le_tabela(w, "wh", "x.y", ["c"])


# ---------------------------------------------------------------- de-para
def _monitor(**kw):
    base = {"chave_canonica": "tabela::LIB.T", "artifact": "LIB.T", "categoria": "tabela",
            "source_types": "PROC SQL | DATA", "qtd_projetos": "2", "areas": "Cobranças | Riscos",
            "modernizada_auto": "A ingerir", "responsavel": "", "observacao": None,
            "updated_at": None, "updated_by": None, "orfao": "false",
            "refreshed_at": "2026-10-13T10:00:00.000Z", "origem": "BigQuery",
            "paths_fisicos": None, "etapa": "A Receber", "status": "A Iniciar"}
    base.update(kw)
    return base


def test_input_converte_tipos_e_listas():
    t = mp.input_(_monitor())
    assert t[4] == ["PROC SQL", "DATA"] and t[5] == ["Cobranças", "Riscos"]
    assert t[6] == 2 and t[7] is False and t[8] == [] and t[9] is False


def test_estado_do_publish_leva_a_sentinela():
    e = mp.estado_input(_monitor())
    assert e[1:5] == ("A Receber", "A Iniciar", None, None) and e[6] == mp.SENTINELA_PUBLISH


def test_estado_editado_guarda_quem_e_quando():
    e = mp.estado_input(_monitor(responsavel="Fulano@indicium.ai", updated_by="b@indicium.ai",
                                 updated_at="2026-10-01T12:00:00.000Z"))
    assert e[3] == "fulano@indicium.ai" and e[6] == "b@indicium.ai" and e[5].isoformat().startswith("2026-10-01T12:00")


def test_valor_fora_do_previsto_para_tudo():
    with pytest.raises(mp.ValorInesperado):
        mp.input_(_monitor(modernizada_auto="Talvez"))
    with pytest.raises(mp.ValorInesperado):
        mp.input_(_monitor(orfao="sim"))


def test_escopo_seed_vira_nulo_e_id_hex_vira_uuid():
    r = {"id": "0" * 31 + "1", "egp_dor1": "X", "area": "Cobranças", "status_extracao": "exato",
         "projeto": "Cobranças__X", "origem": "csv", "created_by": None, "created_at": "seed",
         "ativo": "true"}
    t = mp.escopo_item(r)
    assert t[0] == "00000000-0000-0000-0000-000000000001" and t[7] is None and t[8] == "seed"
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
python -m pytest -q egps_analysis/app/sync/test_sync.py
```

Esperado: erro de import (`cannot import name 'leitor'`).

- [ ] **Step 3: Implementar** `sync/leitor.py`

```python
# -*- coding: utf-8 -*-
"""Lê uma tabela do Databricks INTEIRA pela conta de serviço da sincronização.

Com disposition=INLINE só o primeiro chunk vem na resposta; ler apenas `result.data_array`
truncava em silêncio tudo que não coubesse num chunk (já mordeu este repo duas vezes).
Por isso segue `next_chunk_index` até o fim E confere o total do manifesto.
"""
import time

from databricks.sdk.service.sql import Disposition, Format, StatementState


def le_tabela(w, warehouse_id, fq_tabela, colunas):
    sql = f"SELECT {', '.join(colunas)} FROM {fq_tabela}"
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        r = w.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if (r.status and r.status.error) else "erro desconhecido"
        raise RuntimeError(f"leitura de {fq_tabela} falhou: {msg}")
    linhas, chunk = [], r.result
    while chunk is not None:
        linhas.extend(chunk.data_array or [])
        nxt = getattr(chunk, "next_chunk_index", None)
        if nxt is None:
            break
        chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
    total = getattr(getattr(r, "manifest", None), "total_row_count", None)
    if total is not None and int(total) != len(linhas):
        raise RuntimeError(f"{fq_tabela}: li {len(linhas)} de {total} linhas (truncamento)")
    return [dict(zip(colunas, linha)) for linha in linhas]
```

- [ ] **Step 4: Implementar** `sync/mapeamento.py`

```python
# -*- coding: utf-8 -*-
"""De-para das tabelas Delta para o schema novo — Fase 1, cópia FIEL (ADR 0005).

Entrada: linhas como o Databricks devolve (texto ou None). Saída: tuplas na ordem de
COLUNAS[destino]. Valor fora do previsto LEVANTA ValorInesperado: a sincronização para e
alarma em vez de gravar um palpite. Correções de dado (etapa_migracao, e-mails .tech) são
da Fase 2 — aqui nada muda de sentido, só de tipo.

Sentinela: estado de input que ninguém editou (updated_by vazio, linha criada pelo
publish com os valores padrão) vai com atualizado_por = 'publish'; a view compat devolve
NULL nesse caso, como o Databricks.
"""
import datetime
import decimal
import uuid

SENTINELA_PUBLISH = "publish"

COLUNAS = {
    "corpus.egp": (
        "projeto", "area", "onda", "ciclo_id", "casca", "n_inputs", "n_outputs", "loc",
        "code_tasks_count", "n_outputs_avaliados", "n_outputs_consumidos_por_outro_egp",
        "pct_outputs_consumidos_por_outro_egp", "n_egps_consumidores", "n_exports_arquivos",
        "flag_output_100pct_egp", "flag_algum_output_egp", "flag_sem_export_arquivo",
        "flag_output_unico", "flag_hub_multiplos_consumidores", "orfao", "publicado_em"),
    "corpus.input": (
        "chave", "categoria", "artefato", "origem", "source_types", "areas", "qtd_projetos",
        "disponivel_auto", "paths_fisicos", "orfao", "publicado_em"),
    "trabalho.estado_input": (
        "chave", "etapa", "status", "responsavel", "observacao", "atualizado_em", "atualizado_por"),
    "corpus.egp_input": ("projeto", "input_chave", "artefato", "source_types"),
    "trabalho.escopo_item": (
        "id", "egp_dor1", "area", "status_extracao", "projeto", "origem", "ativo",
        "criado_em", "criado_por"),
}

# Colunas que a sincronização LÊ de cada tabela Delta (ordem livre; vão por nome).
ORIGEM = {
    "sas_lineage_nodes": (
        "projeto", "area", "onda", "n_inputs", "n_outputs", "ciclo_id", "loc", "code_tasks_count",
        "n_outputs_avaliados", "n_outputs_consumidos_por_outro_egp",
        "pct_outputs_consumidos_por_outro_egp", "n_egps_consumidores", "n_exports_arquivos",
        "flag_output_100pct_egp", "flag_algum_output_egp", "flag_sem_export_arquivo",
        "flag_output_unico", "flag_hub_multiplos_consumidores"),
    "sas_inputs_monitor": (
        "chave_canonica", "artifact", "categoria", "source_types", "qtd_projetos", "areas",
        "modernizada_auto", "responsavel", "observacao", "updated_at", "updated_by", "orfao",
        "refreshed_at", "origem", "paths_fisicos", "etapa", "status"),
    "sas_egp_inputs": ("projeto", "chave_canonica", "artifact", "categoria", "source_types"),
    "sas_escopo": (
        "id", "egp_dor1", "area", "status_extracao", "projeto", "origem", "created_by",
        "created_at", "ativo"),
    "sas_analistas": ("email", "nome", "ativo", "organograma", "papel"),
}


class ValorInesperado(ValueError):
    pass


def _bool(v):
    if v is None:
        return None
    if v in ("true", "false"):
        return v == "true"
    raise ValorInesperado(f"booleano inesperado: {v!r}")


def _int(v):
    return None if v in (None, "") else int(v)


def _num(v):
    return None if v in (None, "") else decimal.Decimal(v)


def _txt(v):
    """Texto vazio vira NULL — as telas já tratam os dois igual (ver consulta._sem_vazio)."""
    return None if v is None or not str(v).strip() else v


def _lista(v):
    """'a | b | c' -> ['a', 'b', 'c']; vazio -> []."""
    if v is None or not str(v).strip():
        return []
    return [p.strip() for p in str(v).split("|") if p.strip()]


def _instante(v):
    """Texto de data/hora (TIMESTAMP do Databricks ou STRING gravada pelo app) -> UTC.
    Sem fuso = UTC (a sessão do warehouse grava em UTC)."""
    if v is None or not str(v).strip():
        return None
    s = str(v).strip().replace("Z", "+00:00")
    d = datetime.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d


def egp(r, orfao=False):
    return (r["projeto"], r.get("area"), r.get("onda"), _int(r.get("ciclo_id")) or 0, False,
            _int(r.get("n_inputs")), _int(r.get("n_outputs")), _int(r.get("loc")),
            _int(r.get("code_tasks_count")), _int(r.get("n_outputs_avaliados")),
            _int(r.get("n_outputs_consumidos_por_outro_egp")),
            _num(r.get("pct_outputs_consumidos_por_outro_egp")),
            _int(r.get("n_egps_consumidores")), _int(r.get("n_exports_arquivos")),
            _bool(r.get("flag_output_100pct_egp")), _bool(r.get("flag_algum_output_egp")),
            _bool(r.get("flag_sem_export_arquivo")), _bool(r.get("flag_output_unico")),
            _bool(r.get("flag_hub_multiplos_consumidores")), orfao,
            datetime.datetime.now(datetime.timezone.utc))


def _disponivel(v):
    if v == "Disponível":
        return True
    if v == "A ingerir":
        return False
    if v is None:
        return None
    raise ValorInesperado(f"modernizada_auto inesperado: {v!r}")


def input_(r):
    return (r["chave_canonica"], r["categoria"], r["artifact"], _txt(r.get("origem")),
            _lista(r.get("source_types")), _lista(r.get("areas")), _int(r.get("qtd_projetos")),
            _disponivel(r.get("modernizada_auto")), _lista(r.get("paths_fisicos")),
            bool(_bool(r.get("orfao"))),
            _instante(r.get("refreshed_at")) or datetime.datetime.now(datetime.timezone.utc))


def estado_input(r):
    """None quando não há estado nenhum (a linha não é criada)."""
    etapa, status = _txt(r.get("etapa")), _txt(r.get("status"))
    resp, obs = _txt(r.get("responsavel")), _txt(r.get("observacao"))
    if not any((etapa, status, resp, obs)):
        return None
    por = _txt(r.get("updated_by"))
    em = _instante(r.get("updated_at")) if por else None
    return (r["chave_canonica"], etapa, status, resp.lower() if resp else None, obs,
            em or _instante(r.get("refreshed_at")) or datetime.datetime.now(datetime.timezone.utc),
            por or SENTINELA_PUBLISH)


def egp_input(r):
    return (r["projeto"], r["chave_canonica"], r["artifact"], _lista(r.get("source_types")))


def escopo_item(r):
    criado = r.get("created_at")
    return (str(uuid.UUID(hex=r["id"])), r["egp_dor1"], _txt(r.get("area")), r["status_extracao"],
            _txt(r.get("projeto")), r["origem"], bool(_bool(r.get("ativo"))),
            None if criado == "seed" else _instante(criado), _txt(r.get("created_by")) or "seed")


def ancora_input_ausente(chave, categoria, artefato):
    """Input citado por um par mas ausente do monitor: entra como âncora órfã (as FKs do
    estado humano precisam do pai; o drift atual vira contagem no relatório)."""
    return (chave, categoria, artefato, None, [], [], None, None, [], True,
            datetime.datetime.now(datetime.timezone.utc))
```

- [ ] **Step 5: Rodar e ver passar** (comando do Step 2). Esperado: `7 passed`.

### Task B2: Retrato e carga atômica

**Files:**
- Create: `egps_analysis/app/sync/retrato.py`
- Create: `egps_analysis/app/sync/carrega.py`
- Modify: `egps_analysis/app/sync/test_sync.py`

- [ ] **Step 1: Acrescentar os testes de carga** ao fim de `sync/test_sync.py`, e mudar a linha de import do topo para `from sync import carrega, leitor, mapeamento as mp, retrato  # noqa: E402`:

```python
# ---------------------------------------------------------------- carga
def _linhas():
    return {
        "sas_lineage_nodes": [{"projeto": "Cob__A", "area": "Cobranças", "ciclo_id": "0"}],
        "sas_inputs_monitor": [_monitor(responsavel="fulano@indicium.ai",
                                        updated_by="fulano@indicium.ai",
                                        updated_at="2026-10-01T12:00:00.000Z")],
        "sas_egp_inputs": [
            {"projeto": "Cob__A", "chave_canonica": "tabela::LIB.T", "artifact": "LIB.T",
             "categoria": "tabela", "source_types": "PROC SQL"},
            {"projeto": "Cob__A", "chave_canonica": "tabela::LIB.T", "artifact": "LIB.T",
             "categoria": "tabela", "source_types": "PROC SQL"},
            {"projeto": "Cob__SUMIU", "chave_canonica": "arquivo::X.CSV", "artifact": "X.CSV",
             "categoria": "arquivo", "source_types": ""}],
        "sas_escopo": [{"id": "a" * 32, "egp_dor1": "A", "area": "Cobranças",
                        "status_extracao": "exato", "projeto": "Cob__A", "origem": "csv",
                        "created_by": None, "created_at": "seed", "ativo": "true"}],
        "sas_analistas": [{"email": "Fulano@indicium.ai", "nome": "Fulano", "ativo": "true",
                           "organograma": "true", "papel": "DE"}],
    }


@pytest.fixture
def banco():
    import psycopg
    nome = "t_sync_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    dsn = f"{base}/{nome}"
    migra.aplica(dsn, saida=lambda *_: None)
    yield dsn
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


@precisa_pg
def test_carga_completa_ancoras_e_e_repetivel(banco):
    import psycopg
    ret = retrato.monta(_linhas())
    assert ret["ancoras_acrescentadas"] == {"egp": 1, "input": 1, "pares_duplicados_descartados": 1}
    with psycopg.connect(banco) as conn:
        r1 = carrega.carrega(conn, ret)
        r2 = carrega.carrega(conn, retrato.monta(_linhas()))   # 2ª vez: mesmo resultado
        assert r1["corpus.egp_input"] == r2["corpus.egp_input"] == 2
        conn.execute("SET search_path = compat, derivado, pg_catalog, public")
        orfaos = conn.execute("SELECT projeto FROM corpus.egp WHERE orfao").fetchall()
        assert orfaos == [("Cob__SUMIU",)]
        u = conn.execute("SELECT papel, ativo, cargo FROM cadastro.usuario WHERE email = 'fulano@indicium.ai'").fetchone()
        assert u == ("leitor", False, "DE")          # sincronização nunca dá acesso
        assert conn.execute("SELECT count(*) FROM historico.publicacao WHERE ok").fetchone()[0] == 2
        linha = conn.execute("SELECT areas, escopo_indi, updated_by FROM compat.sas_inputs_monitor").fetchone()
        assert linha == ("Cobranças | Riscos", True, "fulano@indicium.ai")


@precisa_pg
def test_carga_roda_com_o_papel_sincronizador(banco):
    """O login da tarefa ECS só tem o papel `sincronizador` (0004): a carga inteira tem de
    caber nesses privilégios, senão a sincronização de prod falha no primeiro apply."""
    import psycopg
    papel = "t_sync_" + uuid.uuid4().hex[:6]
    with psycopg.connect(banco, autocommit=True) as adm:
        adm.execute(f"CREATE ROLE {papel} LOGIN IN ROLE sincronizador")
    try:
        with psycopg.connect(banco) as conn:
            conn.execute(f"SET ROLE {papel}")
            resumo = carrega.carrega(conn, retrato.monta(_linhas()))
            assert resumo["corpus.input"] == 2
    finally:
        with psycopg.connect(banco, autocommit=True) as adm:
            adm.execute(f"DROP OWNED BY {papel}")
            adm.execute(f"DROP ROLE {papel}")


@precisa_pg
def test_falha_no_meio_nao_troca_o_retrato(banco):
    import psycopg
    with psycopg.connect(banco) as conn:
        carrega.carrega(conn, retrato.monta(_linhas()))
        ruim = retrato.monta(_linhas())
        ruim["trabalho.estado_input"] = [("tabela::NAO_EXISTE",) + ruim["trabalho.estado_input"][0][1:]]
        with pytest.raises(psycopg.Error):
            carrega.carrega(conn, ruim)
        assert conn.execute("SELECT count(*) FROM trabalho.estado_input").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM historico.publicacao").fetchone()[0] == 1
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest -q egps_analysis/app/sync/test_sync.py
```

Esperado: erro de import (`cannot import name 'carrega'`).

- [ ] **Step 3: Implementar** `sync/retrato.py`

```python
# -*- coding: utf-8 -*-
"""Monta o retrato a partir das linhas lidas do Databricks: aplica o de-para e completa as
âncoras (EGP/input citados por um par mas ausentes da tabela-mãe entram como órfãos)."""
from . import mapeamento as mp


def monta(linhas):
    """`linhas`: dict tabela Delta -> lista de dicts (texto). Devolve o retrato de carrega()."""
    egps = {r["projeto"]: mp.egp(r) for r in linhas["sas_lineage_nodes"]}
    inputs = {r["chave_canonica"]: mp.input_(r) for r in linhas["sas_inputs_monitor"]}
    estados = [e for e in (mp.estado_input(r) for r in linhas["sas_inputs_monitor"]) if e]

    pares, vistos, duplicados = [], set(), 0
    egps_novos, inputs_novos = 0, 0
    for r in linhas["sas_egp_inputs"]:
        k = (r["projeto"], r["chave_canonica"])
        if k in vistos:
            duplicados += 1
            continue
        vistos.add(k)
        if r["projeto"] not in egps:
            egps[r["projeto"]] = mp.egp({"projeto": r["projeto"]}, orfao=True)
            egps_novos += 1
        if r["chave_canonica"] not in inputs:
            inputs[r["chave_canonica"]] = mp.ancora_input_ausente(
                r["chave_canonica"], r["categoria"], r["artifact"])
            inputs_novos += 1
        pares.append(mp.egp_input(r))

    usuarios = [(r["email"].strip().lower(), r.get("nome") or r["email"], mp._txt(r.get("papel")),
                 bool(mp._bool(r.get("organograma"))))
                for r in linhas["sas_analistas"]]
    referenciadas = [e[3] for e in estados if e[3]]
    return {
        "corpus.egp": list(egps.values()),
        "corpus.input": list(inputs.values()),
        "trabalho.estado_input": estados,
        "corpus.egp_input": pares,
        "trabalho.escopo_item": [mp.escopo_item(r) for r in linhas["sas_escopo"]],
        "usuarios": usuarios,
        "pessoas_referenciadas": referenciadas,
        "ancoras_acrescentadas": {"egp": egps_novos, "input": inputs_novos,
                                  "pares_duplicados_descartados": duplicados},
    }
```

- [ ] **Step 4: Implementar** `sync/carrega.py`

```python
# -*- coding: utf-8 -*-
"""Grava um retrato completo no Postgres numa transação só (ADR 0005, Fase 1).

Quem lê o app vê o retrato anterior até o COMMIT. Na Fase 1 o Databricks é a fonte da
verdade de TUDO (inclusive do estado humano), então as tabelas sincronizadas são apagadas e
recarregadas; as FKs ficam adiadas até o COMMIT para a ordem não importar. As exceções são
`cadastro.usuario` (os papéis moram só no Postgres: a sincronização só acrescenta pessoas,
inativas, e atualiza nome/cargo) e `historico.publicacao` (só recebe linha).
"""
import datetime
import json

from . import mapeamento as mp

# Apaga filhos antes dos pais; insere pais antes dos filhos.
SINCRONIZADAS = ("trabalho.estado_input", "corpus.egp_input", "trabalho.escopo_item",
                 "corpus.input", "corpus.egp")


def _copia(cur, tabela, linhas):
    cols = mp.COLUNAS[tabela]
    with cur.copy(f"COPY {tabela} ({', '.join(cols)}) FROM STDIN") as cp:
        for linha in linhas:
            cp.write_row(linha)


def carrega(conn, retrato, versao_codigo=None, agora=None):
    """`retrato`: dict destino -> lista de tuplas (âncoras já completas) + 'usuarios'
    (lista de (email, nome, cargo, organograma)) + 'pessoas_referenciadas' (e-mails).
    Devolve o resumo gravado em historico.publicacao."""
    agora = agora or datetime.datetime.now(datetime.timezone.utc)
    resumo = {t: len(retrato.get(t, [])) for t in SINCRONIZADAS}
    with conn.transaction():
        conn.execute("SELECT set_config('app.usuario', 'sincronizacao', true)")
        conn.execute("SET CONSTRAINTS ALL DEFERRED")
        with conn.cursor() as cur:
            for t in SINCRONIZADAS:
                cur.execute(f"DELETE FROM {t}")
            for email, nome, cargo, organograma in retrato.get("usuarios", []):
                cur.execute(
                    "INSERT INTO cadastro.usuario (email, nome, cargo, organograma, ativo) "
                    "VALUES (%s, %s, %s, %s, false) ON CONFLICT (email) DO UPDATE SET "
                    "nome = EXCLUDED.nome, cargo = EXCLUDED.cargo, organograma = EXCLUDED.organograma",
                    (email, nome, cargo, organograma))
            for email in sorted(set(retrato.get("pessoas_referenciadas", []))):
                cur.execute("INSERT INTO cadastro.usuario (email, nome, ativo) VALUES (%s, %s, false) "
                            "ON CONFLICT (email) DO NOTHING", (email, email))
            for t in reversed(SINCRONIZADAS):
                _copia(cur, t, retrato.get(t, []))
            cur.execute("SELECT count(*) FROM derivado.v_trabalho_orfao")
            resumo["trabalho_orfao"] = cur.fetchone()[0]
            resumo["ancoras_acrescentadas"] = retrato.get("ancoras_acrescentadas", {})
            cur.execute(
                "INSERT INTO historico.publicacao (origem, iniciada_em, concluida_em, ok, versao_codigo, resumo) "
                "VALUES ('sync_databricks', %s, now(), true, %s, %s::jsonb)",
                (agora, versao_codigo, json.dumps(resumo)))
    return resumo
```

- [ ] **Step 5: Rodar e ver passar.** Esperado: `10 passed`.

### Task B3: Ponto de entrada da sincronização

**Files:**
- Create: `egps_analysis/app/sync/sincroniza.py`

- [ ] **Step 1: Implementar**

```python
# -*- coding: utf-8 -*-
"""Sincronização Databricks -> Postgres (ADR 0005, Fase 1). Roda como tarefa ECS agendada.

Uso: python -m sync.sincroniza
Ambiente: DATABRICKS_HOST / DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET (conta de serviço
só leitura), DATABRICKS_WAREHOUSE_ID, ORIGEM_SCHEMA (padrão bv_dev_db.monitoramento_sas),
PG_DSN ou PGHOST/PGUSER/PGPASSWORD/PGDATABASE, PG_PAPEL (sincronizador na AWS),
VERSAO_CODIGO (opcional).
Sai com código 1 e a linha "[sync] FALHA" no log em qualquer erro — o alarme do CloudWatch
filtra essa linha; o app mostra a faixa vermelha quando a última sincronização boa envelhece.
"""
import os
import sys
import traceback

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg import sql

from . import carrega, leitor, mapeamento as mp, retrato


def main():
    origem = os.environ.get("ORIGEM_SCHEMA", "bv_dev_db.monitoramento_sas")
    try:
        warehouse = os.environ["DATABRICKS_WAREHOUSE_ID"]
        w = WorkspaceClient()
        linhas = {t: leitor.le_tabela(w, warehouse, f"{origem}.{t}", cols)
                  for t, cols in mp.ORIGEM.items()}
        with psycopg.connect(os.environ.get("PG_DSN") or "") as conn:
            # Entra como mestre (girado pela plataforma) e baixa para o papel da carga.
            papel = os.environ.get("PG_PAPEL")
            if papel:
                conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(papel)))
                conn.commit()
            resumo = carrega.carrega(conn, retrato.monta(linhas), os.environ.get("VERSAO_CODIGO"))
        print(f"[sync] OK {resumo}", flush=True)
    except Exception as e:  # noqa: BLE001 — qualquer falha tem de virar alarme
        print(f"[sync] FALHA {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Rodar contra o Postgres local com a origem DEV** (leitura apenas; perfil `bv`):

```bash
env PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento DATABRICKS_CONFIG_PROFILE=bv DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd ORIGEM_SCHEMA=bv_dev_db.monitoramento_sas_dev python -m sync.sincroniza
```

Rode a partir de `egps_analysis/app`, depois de criar o banco e aplicar as migrações (`env PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento python -m db.migra --cria-banco`). Esperado: `[sync] OK {...}`, com contagens próximas das de dev e `ancoras_acrescentadas` e `trabalho_orfao` registrados. Anote o resumo, porque ele é a primeira auditoria de integridade. Medido em 2026-10-14 contra `monitoramento_sas_dev`: `corpus.egp` 1.229, `corpus.input` 12.560, `corpus.egp_input` 21.578, `trabalho.escopo_item` 229, `trabalho_orfao` 292, âncoras acrescentadas 0, pares duplicados descartados 1.

- [ ] **Step 3: Checkpoint de commit** (só se pedido): `feat(app): sincronização Databricks -> Postgres (5 tabelas)`.

---

## Parte C — Backend em modo Postgres

### Task C1: Dialeto e literais

**Files:**
- Create: `egps_analysis/app/backend/dialeto.py`
- Modify: `egps_analysis/app/backend/main.py` (`sql_lit`, `main.py:544`)
- Modify: `egps_analysis/app/backend/familias.py` (`_lit`, ~`:356`)
- Modify: `egps_analysis/app/backend/egps_atualizados.py` (`_sql_str`, ~`:515`)
- Test: `egps_analysis/app/backend/test_dialeto.py`

- [ ] **Step 1: Escrever o teste** `backend/test_dialeto.py`

```python
# -*- coding: utf-8 -*-
"""Literal de texto nos dois dialetos — e a prova de que o do Spark é injeção no Postgres."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import dialeto  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")


def test_spark_dobra_contrabarra_e_escapa_aspa():
    assert dialeto.lit("O'Brien", pg=False) == "'O\\'Brien'"
    assert dialeto.lit("a\\b", pg=False) == "'a\\\\b'"


def test_postgres_dobra_aspa_e_deixa_contrabarra():
    assert dialeto.lit("O'Brien", pg=True) == "'O''Brien'"
    assert dialeto.lit("a\\b", pg=True) == "'a\\b'"


def test_none_vira_null():
    assert dialeto.lit(None, pg=True) == "NULL" and dialeto.lit(None, pg=False) == "NULL"


@pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")
def test_no_postgres_o_literal_devolve_o_mesmo_texto():
    import psycopg
    ataque = "x\\' OR 1=1 --"
    with psycopg.connect(DSN) as conn:
        assert conn.execute(f"SELECT {dialeto.lit(ataque, pg=True)}").fetchone()[0] == ataque
        # e o escape do Spark, no Postgres, NÃO devolve o mesmo texto (é o furo):
        with pytest.raises(psycopg.Error):
            conn.execute(f"SELECT {dialeto.lit(ataque, pg=False)} AS s").fetchone()
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest -q egps_analysis/app/backend/test_dialeto.py
```

Esperado: `ModuleNotFoundError: No module named 'dialeto'`.

- [ ] **Step 3: Implementar** `backend/dialeto.py`

```python
# -*- coding: utf-8 -*-
"""Qual banco o app usa e como escrever um literal de texto nele (ADR 0005).

Na Fase 1 o MESMO código serve o app do Databricks (prod atual) e o app na AWS (Postgres).
Fora daqui e de db_pg.py o backend não pergunta qual é o banco: o que muda de um para o
outro é o literal e a execução — o resto do SQL é escrito na forma que roda nos dois.
"""
import os

DB_BACKEND = os.environ.get("DB_BACKEND", "databricks").strip().lower()
if DB_BACKEND not in ("databricks", "postgres"):
    raise RuntimeError(f"DB_BACKEND inválido: {DB_BACKEND!r} (use databricks ou postgres)")
PG = DB_BACKEND == "postgres"


def lit(v, pg=None):
    """Literal SQL de texto (None vira NULL).

    Spark: a aspa vira \\' e a contrabarra é dobrada antes — no Spark `'O''Brien'` são DOIS
    literais concatenados e o apóstrofo some em silêncio (verificado no warehouse).
    Postgres (standard_conforming_strings=on, o padrão): a aspa vira '' e a contrabarra é
    literal — o \\' do Spark lá FECHA a string, e `x\\' OR 1=1 --` vira injeção.
    """
    if v is None:
        return "NULL"
    s = str(v)
    if PG if pg is None else pg:
        return "'" + s.replace("'", "''") + "'"
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
```

- [ ] **Step 4: Delegar os 3 escapes ao `dialeto`.** Em `main.py`, junto dos outros imports locais (perto de `import familias`, `main.py:38`), acrescente `import dialeto  # banco em uso + literal (ADR 0005)`, e troque o corpo de `sql_lit` (`main.py:544-554`) por:

```python
def sql_lit(v):
    # Dialeto do banco em uso (ADR 0005). No Spark a aspa vira \' — `'O''Brien'` lá são DOIS
    # literais concatenados e o apóstrofo some em silêncio (verificado no warehouse); no
    # Postgres o \' FECHA a string (injeção). As duas regras moram em dialeto.lit.
    return dialeto.lit(v)
```

Em `familias.py`, acrescente `import dialeto` aos imports e troque `_lit`:

```python
def _lit(s):
    return dialeto.lit(s)
```

Em `egps_atualizados.py`, acrescente `import dialeto` aos imports e troque o corpo de `_sql_str` (o comentário histórico fica):

```python
    return dialeto.lit(v)
```

Os literais de regex escritos à mão em `familias.py` (`_nao_sep`, `_sep_fim`) **ficam como estão**: no Spark `'[^/\\\\]*$'` vira a classe `[^/\\]`, e no Postgres a classe `[^/\\\\]`. As duas excluem `/` e `\`, então o resultado é o mesmo. O teste de paridade das famílias da 1b confere.

- [ ] **Step 5: Rodar a suíte inteira do backend** (tudo continua no modo Databricks por padrão):

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest -q egps_analysis/app/backend
```

Esperado: tudo passa, inclusive `test_dialeto.py` (`4 passed` nele). Se `test_sql_escape.py` (raiz de `egps_analysis`) testar os helpers, ele também roda: `python egps_analysis/test_sql_escape.py`. Esperado: sai com 0, porque o padrão continua Spark.

- [ ] **Step 6: Checkpoint de commit** (só se pedido): `feat(app): literal SQL por dialeto (Spark x Postgres)`.

### Task C2: Driver do Postgres com o contrato do `run_sql`

**Files:**
- Create: `egps_analysis/app/backend/db_pg.py`
- Test: `egps_analysis/app/backend/test_db_pg.py`

- [ ] **Step 1: Escrever o teste** `backend/test_db_pg.py`

```python
# -*- coding: utf-8 -*-
"""db_pg: formato de saída igual ao do Databricks + execução real contra um Postgres.

Os testes de execução precisam de PG_TEST_DSN. Sem ele são pulados — EXCETO no CI, onde
PG_TEST_OBRIGATORIO=1 transforma o pulo em falha (pular em silêncio esconderia o gate).
"""
import datetime
import decimal
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import db_pg  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
precisa_pg = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")


@pytest.fixture
def pool_novo(monkeypatch):
    """Cada teste abre o próprio pool (com o ambiente dele) e o FECHA no fim — trocar o
    pool sem fechar deixa threads do psycopg_pool penduradas e polui a saída."""
    monkeypatch.setenv("PG_DSN", DSN or "")
    db_pg._pool = None
    yield
    if db_pg._pool is not None:
        db_pg._pool.close()
    db_pg._pool = None


def test_texto_reproduz_o_formato_do_databricks():
    utc = datetime.timezone.utc
    assert db_pg.texto(None) is None
    assert db_pg.texto(True) == "true" and db_pg.texto(False) == "false"
    assert db_pg.texto(7) == "7"
    assert db_pg.texto(decimal.Decimal("12.50")) == "12.50"
    assert db_pg.texto(datetime.datetime(2026, 10, 14, 15, 4, 5, 123456, tzinfo=utc)) == "2026-10-14T15:04:05.123Z"
    sp = datetime.timezone(datetime.timedelta(hours=-3))
    assert db_pg.texto(datetime.datetime(2026, 10, 14, 12, 0, tzinfo=sp)) == "2026-10-14T15:00:00.000Z"
    assert db_pg.texto(datetime.date(2026, 10, 1)) == "2026-10-01"
    assert db_pg.texto(["a", "b"]) == '["a", "b"]'


def test_e_escrita():
    assert db_pg.e_escrita("  INSERT INTO x VALUES (1)")
    assert db_pg.e_escrita("merge into t using s on 1=1 when matched then delete")
    assert not db_pg.e_escrita("SELECT 1")
    assert not db_pg.e_escrita("")


@precisa_pg
def test_run_devolve_texto(pool_novo):
    linhas = db_pg.run("SELECT true AS b, 2 AS n, NULL::text AS z, 'O''Brien' AS s")
    assert linhas == [{"b": "true", "n": "2", "z": None, "s": "O'Brien"}]


@precisa_pg
def test_run_com_params_e_percent_literal(pool_novo):
    assert db_pg.run("SELECT 'a%' AS p")[0]["p"] == "a%"
    assert db_pg.run("SELECT %s::int + 1 AS n", params=(41,))[0]["n"] == "42"


@precisa_pg
def test_tabela_ausente_vira_marca_que_o_main_entende(pool_novo):
    with pytest.raises(db_pg.ErroSQL, match="TABLE_OR_VIEW_NOT_FOUND"):
        db_pg.run("SELECT * FROM nao_existe_tabela")


@precisa_pg
def test_sessao_baixa_para_o_papel_configurado(pool_novo, monkeypatch):
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't_papel_app') "
                  "THEN CREATE ROLE t_papel_app NOLOGIN; END IF; END $$")
    monkeypatch.setenv("PG_PAPEL", "t_papel_app")
    assert db_pg.run("SELECT current_user AS u")[0]["u"] == "t_papel_app"


def test_modo_leitura_recusa_escrita_sem_ir_ao_banco():
    with pytest.raises(db_pg.ErroSQL, match="permission denied"):
        db_pg.run("DELETE FROM x", somente_leitura=True)
```

- [ ] **Step 2: Rodar e ver falhar.** Esperado: `No module named 'db_pg'`.

- [ ] **Step 3: Implementar** `backend/db_pg.py`

```python
# -*- coding: utf-8 -*-
"""Execução de SQL no Postgres com o MESMO contrato de main.run_sql (ADR 0005).

O contrato vem do Databricks (formato JSON_ARRAY): toda célula volta como TEXTO, ou None.
O app foi escrito em cima disso (`== "true"`, `int(r["n"])`, `substr(ts, 1, 7)` no front),
e na Fase 1 a resposta da API não muda — então o texto é reproduzido aqui, em vez de o app
inteiro aprender tipos nativos agora. Booleano vira "true"/"false"; instante vira ISO-8601
em UTC com milissegundos e "Z"; data vira AAAA-MM-DD; lista vira JSON.

`search_path` põe `compat` ANTES de `pg_catalog`: as funções com nome do Spark que moram em
compat (regexp_replace global, split por regex, count_if...) sombreiam as do sistema.
"""
import datetime
import decimal
import json
import os
import threading

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool

SEARCH_PATH = "compat, derivado, pg_catalog, public"
ESCRITA = ("insert", "update", "delete", "merge", "create", "alter", "drop", "truncate",
           "grant", "revoke", "copy", "comment", "vacuum")
# SQLSTATE -> marca que main._objeto_ausente / main._sql_http_error já reconhecem.
_MARCA = {
    "42P01": "TABLE_OR_VIEW_NOT_FOUND",   # undefined_table
    "42703": "UNRESOLVED_COLUMN",         # undefined_column
    "42501": "permission denied",         # insufficient_privilege
}

_pool = None
_pool_lock = threading.Lock()


class ErroSQL(Exception):
    """Falha de SQL, com a mensagem no formato que o main já classifica."""


def _configura(conn):
    conn.execute(f"SET search_path = {SEARCH_PATH}")
    conn.execute("SET TIME ZONE 'UTC'")
    # Na AWS o app entra com o usuário MESTRE (o único que o indicium-secret-rotation gira)
    # e baixa os privilégios da sessão para PG_PAPEL (app_leitura na Fase 1). Barreira contra
    # escrita por engano; não contra quem já injeta SQL (RESET ROLE desfaz) — essa é do
    # sql_lit/parâmetros e do middleware de acesso.
    papel = os.environ.get("PG_PAPEL")
    if papel:
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(papel)))
    conn.commit()


def pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            # PG_DSN no uso local; no ECS vêm as variáveis padrão da libpq (PGHOST, PGUSER,
            # PGPASSWORD do Secrets Manager...) e a string de conexão fica vazia.
            dsn = os.environ.get("PG_DSN") or ""
            if not dsn and not os.environ.get("PGHOST"):
                raise RuntimeError("Sem PG_DSN nem PGHOST (DB_BACKEND=postgres).")
            _pool = ConnectionPool(dsn, min_size=1, max_size=int(os.environ.get("PG_POOL_MAX", "10")),
                                   configure=_configura, open=True)
    return _pool


def texto(v):
    """Uma célula no formato que o Databricks devolvia."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime.datetime):
        if v.tzinfo is not None:
            v = v.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return v.isoformat(timespec="milliseconds") + "Z"
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return format(v, "f")
    if isinstance(v, (list, tuple)):
        return json.dumps([texto(x) for x in v], ensure_ascii=False)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def e_escrita(statement):
    """Primeira palavra é comando que escreve. Defesa em profundidade: a barreira de verdade
    é o papel de banco do app (app_leitura só tem SELECT)."""
    palavras = statement.split(None, 1)
    return bool(palavras) and palavras[0].lower() in ESCRITA


def run(statement, want_rows=True, params=None, somente_leitura=False):
    if somente_leitura and e_escrita(statement):
        raise ErroSQL("permission denied: escrita recusada — app em modo leitura")
    try:
        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(statement, params)
                if not want_rows or cur.description is None:
                    return None
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, (texto(v) for v in linha))) for linha in cur.fetchall()]
    except psycopg.Error as e:
        codigo = getattr(e, "sqlstate", None) or ""
        raise ErroSQL(f"{_MARCA.get(codigo, '')} [{codigo}] {e}".strip()) from e
```

- [ ] **Step 4: Rodar e ver passar**, tratando aviso de pool como erro:

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest -q -W error::pytest.PytestUnraisableExceptionWarning egps_analysis/app/backend/test_db_pg.py
```

Esperado: `7 passed`.

### Task C3: Despacho do `run_sql`, `FQ` e `_ensure_*` inertes no Postgres

**Files:**
- Modify: `egps_analysis/app/backend/main.py`
- Test: `egps_analysis/app/backend/test_acesso_pg.py` (criado aqui, ampliado na C5)

- [ ] **Step 1: Escrever o teste** `backend/test_acesso_pg.py`

```python
# -*- coding: utf-8 -*-
"""Modo Postgres do backend: despacho do run_sql, DDL nunca enviado, identidade e acesso."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from backend import main as m  # noqa: E402

ENSURES = ["_ensure_analistas_table", "_ensure_responsaveis_bv_table", "_ensure_link_tables",
           "_ensure_dep_mantida_tables", "_ensure_periodo_tables", "_ensure_ingestao_tables",
           "_ensure_out_pipe_table", "_ensure_escopo_ativo", "_ensure_node_metric_cols",
           "_ensure_input_pipeline_cols", "_ensure_pipe_table", "_ensure_prio_snapshot_table",
           "_ensure_gestao_tables", "_ensure_preworking_table", "_ensure_prio_table"]


def test_run_sql_vai_ao_postgres_no_modo_pg(monkeypatch):
    chamadas = []
    monkeypatch.setattr(m.dialeto, "PG", True)
    monkeypatch.setattr(m.db_pg, "run", lambda s, w=True, p=None, somente_leitura=False:
                        chamadas.append((s, p)) or [{"x": "1"}])
    assert m.run_sql("SELECT 1 AS x") == [{"x": "1"}]
    assert m.run_sql("SELECT %s AS x", params=(1,)) == [{"x": "1"}]
    assert chamadas == [("SELECT 1 AS x", None), ("SELECT %s AS x", (1,))]


def test_params_no_databricks_e_erro_alto(monkeypatch):
    monkeypatch.setattr(m.dialeto, "PG", False)
    with pytest.raises(ValueError, match="params"):
        m.run_sql("SELECT 1", params=(1,))


@pytest.mark.parametrize("nome", ENSURES)
def test_ensure_nao_manda_ddl_no_postgres(monkeypatch, nome):
    monkeypatch.setattr(m.dialeto, "PG", True)
    monkeypatch.setattr(m, "run_sql", lambda *a, **k: pytest.fail(f"{nome} enviou SQL no modo PG"))
    monkeypatch.setattr(m, "_run_sp", lambda *a, **k: pytest.fail(f"{nome} enviou SQL no modo PG"))
    fn = getattr(m, nome)
    getattr(fn, "__wrapped__", fn)()
```

- [ ] **Step 2: Rodar e ver falhar.** Esperado: `AttributeError: module 'backend.main' has no attribute 'db_pg'` e os `_ensure_*` enviando SQL.

- [ ] **Step 3: Imports e flags.** Em `main.py`, junto de `import dialeto`:

```python
import db_pg     # execução no Postgres com o contrato do run_sql (ADR 0005)
import auth_alb  # e-mail do usuário a partir do JWT assinado pelo load balancer
```

Logo depois de `REQUIRE_OBO = ...` (`main.py:54`):

```python
# App na AWS (ADR 0005). IDENTIDADE: obo = Databricks App (token do usuário); alb = login do
# Google feito pelo load balancer (cabeçalho assinado); dev = DEV_USUARIO fixo, SÓ local.
IDENTIDADE = os.environ.get("IDENTIDADE", "obo").strip().lower()
ALB_SIGNER = os.environ.get("ALB_SIGNER_ARN", "")
DEV_USUARIO = os.environ.get("DEV_USUARIO", "")
# Fase 1 na AWS: ninguém escreve (a fonte da verdade ainda é o Databricks).
SOMENTE_LEITURA = os.environ.get("SOMENTE_LEITURA", "").strip().lower() in ("1", "true", "yes")
```

- [ ] **Step 4: `FQ`.** Troque `FQ = f"{CATALOG}.{SCHEMA}"` (`main.py:63`) por:

```python
# No Postgres não há catálogo: o app lê as views do schema `compat`, que imitam as tabelas
# Delta pelo nome (PUBLISH_SCHEMA=compat na AWS).
FQ = SCHEMA if dialeto.PG else f"{CATALOG}.{SCHEMA}"
```

- [ ] **Step 5: Despacho.** Troque a assinatura e o início de `run_sql` (`main.py:606`) por:

```python
def run_sql(statement, want_rows=True, *, params=None):
    if dialeto.PG:
        return _run_pg(statement, want_rows, params)
    if params is not None:
        raise ValueError("params só existe no Postgres; no Databricks use sql_lit")
    if not WAREHOUSE_ID:
```

(o resto da função fica igual). No início de `_run_sp`, antes do `if not WAREHOUSE_ID:`:

```python
    if dialeto.PG:
        return _run_pg(statement, want_rows, None)
```

E, logo antes de `def run_sql`:

```python
def _run_pg(statement, want_rows, params):
    """run_sql no Postgres (ADR 0005). Mesma tradução de erro do Databricks: permissão -> 403,
    tabela/coluna ausente -> 502 com a marca que _objeto_ausente reconhece."""
    try:
        return db_pg.run(statement, want_rows, params, somente_leitura=SOMENTE_LEITURA)
    except db_pg.ErroSQL as e:
        print(f"[run_sql] PG: {e}", flush=True)
        raise _sql_http_error(str(e))
```

- [ ] **Step 6: `_ensure_*` inertes.** No topo do corpo de **cada uma** das 15 funções abaixo, insira as duas linhas a seguir **antes** de qualquer outra instrução, mas **depois da docstring** (senão a função perde o `__doc__`). As linhas da tabela são da `main` anterior: procure pelo nome. O valor devolvido é o mesmo que a função devolve no caminho de sucesso; confira o `return` final de cada uma, e se ela não devolve nada, use `return None`:

```python
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
```

| Linha | Função |
|---|---|
| 768 | `_ensure_analistas_table` |
| 777 | `_ensure_responsaveis_bv_table` |
| 835 | `_ensure_link_tables` |
| 860 | `_ensure_dep_mantida_tables` |
| 2326 | `_ensure_periodo_tables` |
| 2501 | `_ensure_ingestao_tables` |
| 2885 | `_ensure_out_pipe_table` |
| 4088 | `_ensure_escopo_ativo(exec_fn=None)` |
| 4106 | `_ensure_node_metric_cols` |
| 4129 | `_ensure_input_pipeline_cols(exec_fn=None)` |
| 5606 | `_ensure_pipe_table` |
| 7510 | `_ensure_prio_snapshot_table(sp=False)` |
| 8264 | `_ensure_gestao_tables` (tem `@functools.lru_cache` **duplicado** em 8262-8263; tire o duplicado) |
| 8651 | `_ensure_preworking_table` |
| 8902 | `_ensure_prio_table` |

- [ ] **Step 7: Rodar e ver passar**

```bash
python -m pytest -q egps_analysis/app/backend/test_acesso_pg.py
```

Esperado: `17 passed`. Depois, a suíte inteira:

```bash
env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest -q egps_analysis/app/backend
```

Esperado: tudo verde. Os stubs antigos de `run_sql` (`fake_run_sql(stmt, want_rows=True)`) continuam valendo, porque nenhum caminho do Databricks passa `params`.

- [ ] **Step 8: Checkpoint de commit** (só se pedido): `feat(app): backend despacha SQL para o Postgres (DB_BACKEND)`.

### Task C4: Identidade do load balancer

**Files:**
- Create: `egps_analysis/app/backend/auth_alb.py`
- Test: `egps_analysis/app/backend/test_auth_alb.py`

- [ ] **Step 1: Escrever o teste** `backend/test_auth_alb.py`

```python
# -*- coding: utf-8 -*-
"""Identidade do ALB: só e-mail com assinatura do NOSSO load balancer passa."""
import base64
import json
import os
import sys
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

sys.path.insert(0, os.path.dirname(__file__))
import auth_alb  # noqa: E402

SIGNER = "arn:aws:elasticloadbalancing:us-east-1:835825599161:loadbalancer/app/tf-load-balancer/abc"


def _par():
    priv = ec.generate_private_key(ec.SECP256R1())
    pem_pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pem_pub


def _token(priv, email="Fulano@BV.com.br", signer=SIGNER, exp=None, padding=False):
    dados = {"email": email, "exp": exp or int(time.time()) + 60}
    if not padding:
        return jwt.encode(dados, priv, algorithm="ES256", headers={"signer": signer, "kid": "k1"})
    # Como o ALB faz: base64url COM '=' em cada parte, e a assinatura cobre o texto JÁ com o
    # padding (pego na bancada da training: tirar o '=' antes de conferir quebrava a assinatura
    # de todo login real). Antes este teste punha o '=' depois de assinar — token que não existe.
    def b64(b):
        return base64.urlsafe_b64encode(b).decode()
    cab = b64(json.dumps({"alg": "ES256", "kid": "k1", "signer": signer, "typ": "JWT"}).encode())
    corpo = b64(json.dumps(dados).encode())
    assinatura = ECAlgorithm(ECAlgorithm.SHA256).sign(f"{cab}.{corpo}".encode(), priv)
    return f"{cab}.{corpo}.{b64(assinatura)}"


def test_email_valido_sai_minusculo():
    priv, pub = _par()
    assert auth_alb.email_do_cabecalho(_token(priv), SIGNER, busca_chave=lambda r, k: pub) == "fulano@bv.com.br"


def test_aceita_padding_do_alb():
    priv, pub = _par()
    t = _token(priv, padding=True)
    assert auth_alb.email_do_cabecalho(t, SIGNER, busca_chave=lambda r, k: pub) == "fulano@bv.com.br"


def test_recusa_outro_signer():
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="signer"):
        auth_alb.email_do_cabecalho(_token(priv, signer="arn:outro"), SIGNER, busca_chave=lambda r, k: pub)


def test_recusa_assinatura_de_outra_chave():
    priv, _ = _par()
    _, pub_outra = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="assinatura"):
        auth_alb.email_do_cabecalho(_token(priv), SIGNER, busca_chave=lambda r, k: pub_outra)


def test_recusa_token_vencido():
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida):
        auth_alb.email_do_cabecalho(_token(priv, exp=int(time.time()) - 10), SIGNER,
                                    busca_chave=lambda r, k: pub)


def test_recusa_sem_email():
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="e-mail"):
        auth_alb.email_do_cabecalho(_token(priv, email=""), SIGNER, busca_chave=lambda r, k: pub)


def test_recusa_cabecalho_ausente_e_signer_nao_configurado():
    with pytest.raises(auth_alb.IdentidadeInvalida):
        auth_alb.email_do_cabecalho("", SIGNER)
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="signer"):
        auth_alb.email_do_cabecalho(_token(priv), "", busca_chave=lambda r, k: pub)
```

- [ ] **Step 2: Rodar e ver falhar.** Esperado: `No module named 'auth_alb'`. Se a C3 já estiver aplicada, a falha aparece também no import do `main`, e a ordem C4 → C3 resolve.

- [ ] **Step 3: Implementar** `backend/auth_alb.py`

```python
# -*- coding: utf-8 -*-
"""Identidade vinda do login do load balancer (ADR 0005).

O ALB faz o login do Google e repassa ao app o cabeçalho `x-amzn-oidc-data`: um JWT ES256
assinado pelo PRÓPRIO ALB. Qualquer coisa que alcance o container consegue forjar esse
cabeçalho — por isso a assinatura é conferida com a chave pública regional da AWS e o
`signer` tem de ser o ARN do nosso load balancer. Sem essas duas checagens o e-mail é só
um texto que o cliente mandou.
Doc: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/listener-authenticate-users.html
"""
import base64
import functools
import json
import urllib.request

import jwt  # PyJWT

URL_CHAVE = "https://public-keys.auth.elb.{regiao}.amazonaws.com/{kid}"


class IdentidadeInvalida(Exception):
    pass


def _b64url(s):
    s = s.rstrip("=")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@functools.lru_cache(maxsize=32)
def _chave_publica(regiao, kid):
    with urllib.request.urlopen(URL_CHAVE.format(regiao=regiao, kid=kid), timeout=5) as r:
        return r.read().decode("ascii")


def email_do_cabecalho(token, signer_esperado, regiao="us-east-1", busca_chave=None):
    """E-mail (minúsculo) do usuário logado. Qualquer falha levanta IdentidadeInvalida."""
    if not token:
        raise IdentidadeInvalida("cabeçalho x-amzn-oidc-data ausente")
    partes = token.split(".")
    if len(partes) != 3:
        raise IdentidadeInvalida("JWT malformado")
    try:
        cab = json.loads(_b64url(partes[0]))
    except ValueError as e:
        raise IdentidadeInvalida(f"cabeçalho do JWT ilegível: {e}") from e
    if not signer_esperado or cab.get("signer") != signer_esperado:
        raise IdentidadeInvalida(f"signer inesperado: {cab.get('signer')!r}")
    kid = cab.get("kid")
    if not kid:
        raise IdentidadeInvalida("JWT sem kid")
    pem = (busca_chave or _chave_publica)(regiao, kid)
    # O token vai COMO VEIO: o ALB emite base64url com '=' e assina o texto já com esse
    # padding. Tirar o '=' antes de conferir muda o que foi assinado e reprova todo login real
    # (pego na bancada da training, 14/10/2026).
    try:
        dados = jwt.decode(token, pem, algorithms=["ES256"], options={"verify_aud": False})
    except jwt.PyJWTError as e:
        raise IdentidadeInvalida(f"assinatura/validade do JWT: {e}") from e
    email = (dados.get("email") or "").strip().lower()
    if not email:
        raise IdentidadeInvalida("JWT sem e-mail (o login precisa do escopo 'email')")
    return email
```

- [ ] **Step 4: Rodar e ver passar.** Esperado: `7 passed`.

### Task C5: Identidade, cadastro e acesso no modo Postgres

**Files:**
- Modify: `egps_analysis/app/backend/main.py` (`_sessao` `:376`, `_OBOAuthMiddleware` `:497`, `/api/me` `:686`)
- Modify: `egps_analysis/app/backend/test_acesso_pg.py`

- [ ] **Step 1: Acrescentar os testes** ao fim de `test_acesso_pg.py`:

```python
def _cliente(monkeypatch, papel, somente_leitura=False, email="fulano@bv.com.br"):
    """TestClient no modo PG com identidade dev e cadastro stubado (papel=None: sem cadastro)."""
    monkeypatch.setattr(m.dialeto, "PG", True)
    monkeypatch.setattr(m, "IDENTIDADE", "dev")
    monkeypatch.setattr(m, "DEV_USUARIO", email)
    monkeypatch.setattr(m, "SOMENTE_LEITURA", somente_leitura)
    m._sessoes.clear()

    def fake(stmt, want_rows=True, *, params=None):
        if "from cadastro.usuario" in " ".join(stmt.split()).lower():
            return [{"papel": papel}] if papel else []
        return []
    monkeypatch.setattr(m, "run_sql", fake)
    return TestClient(m.app)


def test_sem_cadastro_nao_entra(monkeypatch):
    c = _cliente(monkeypatch, None)
    assert c.get("/api/config").status_code == 403


def test_health_e_me_sao_livres(monkeypatch):
    c = _cliente(monkeypatch, None)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/me").json()["user"] is None


def test_leitor_ve_o_proprio_papel(monkeypatch):
    c = _cliente(monkeypatch, "leitor")
    assert c.get("/api/me").json() == {"user": "fulano@bv.com.br", "papel": "leitor"}


def _rotas_de_escrita():
    for r in m.app.routes:
        for metodo in sorted(getattr(r, "methods", set()) & {"POST", "PATCH", "PUT", "DELETE"}):
            if getattr(r, "path", "").startswith("/api/"):
                yield metodo, r.path.replace("{", "").replace("}", "")


def test_leitor_nao_escreve_em_rota_nenhuma(monkeypatch):
    c = _cliente(monkeypatch, "leitor")
    rotas = list(_rotas_de_escrita())
    assert len(rotas) >= 28
    for metodo, caminho in rotas:
        r = c.request(metodo, caminho, json={})
        assert r.status_code == 403, f"{metodo} {caminho} -> {r.status_code}"


def test_banco_fora_do_ar_na_checagem_de_acesso_responde_502(monkeypatch):
    """A checagem roda no middleware, FORA dos handlers do FastAPI: sem tratar, a falha do
    banco virava 500 com traceback em vez do 502 "Falha SQL" das rotas."""
    c = _cliente(monkeypatch, "leitor")

    def fora_do_ar(*a, **k):
        raise m.HTTPException(502, "Falha SQL: couldn't get a connection")
    monkeypatch.setattr(m, "run_sql", fora_do_ar)
    r = c.get("/api/config")
    assert r.status_code == 502 and "Falha SQL" in r.json()["detail"]


def test_gestao_tambem_nao_escreve_com_somente_leitura(monkeypatch):
    c = _cliente(monkeypatch, "gestao", somente_leitura=True)
    assert c.patch("/api/inputs", json={}).status_code == 403
```

- [ ] **Step 2: Rodar e ver falhar.** Esperado: `/api/config` responde 200 sem cadastro (ou 502), e o leitor consegue mandar PATCH.

- [ ] **Step 3: Contexto do e-mail e sessão no PG.** Logo antes de `def _sessao()` (`main.py:376`):

```python
# E-mail do usuário quando o app roda na AWS (ADR 0005); o middleware preenche por request.
_usuario_email: contextvars.ContextVar = contextvars.ContextVar("usuario_email", default=None)


def _sessao_pg_de(email):
    """{user, papel, gestao, admin} de quem está ATIVO em cadastro.usuario, ou None.
    Cacheado por e-mail (mesmo TTL da sessão OBO): mudança de papel reflete em até 5 min."""
    now = time.monotonic()
    k = "pg:" + email
    with _cache_lock:
        hit = _sessoes.get(k)
        if hit and hit[0] > now:
            return hit[1]
    rows = run_sql("SELECT papel FROM cadastro.usuario WHERE ativo AND email = " + sql_lit(email))
    val = None
    if rows:
        p = rows[0]["papel"]
        val = {"user": email, "papel": p, "gestao": p in ("gestao", "admin"), "admin": p == "admin"}
    with _cache_lock:
        _sessoes[k] = (now + _SESSAO_TTL, val)
    return val
```

E, como primeiras linhas do corpo de `_sessao()`:

```python
    if dialeto.PG:
        email = _usuario_email.get()
        val = _sessao_pg_de(email) if email else None
        if val is None:
            raise HTTPException(403, "Sem acesso ao app — peça à gestão do projeto para cadastrar seu e-mail.")
        return val
```

- [ ] **Step 4: Middleware.** Antes de `class _OBOAuthMiddleware` (`main.py:497`):

```python
_LIVRES_PG = ("/api/health", "/api/me")
_METODOS_LEITURA = ("GET", "HEAD", "OPTIONS")


def _email_da_requisicao(scope):
    """E-mail na AWS. alb: cabeçalho assinado pelo load balancer (auth_alb confere assinatura
    e signer); dev: DEV_USUARIO, só para rodar local. None se não houver ou não valer."""
    if IDENTIDADE == "dev":
        return DEV_USUARIO.strip().lower() or None
    if IDENTIDADE != "alb":
        return None
    bruto = dict(scope.get("headers", [])).get(b"x-amzn-oidc-data", b"").decode("latin-1")
    try:
        return auth_alb.email_do_cabecalho(bruto, ALB_SIGNER)
    except auth_alb.IdentidadeInvalida as e:
        print(f"[auth] cabeçalho do ALB recusado: {e}", flush=True)
        return None


def _nega_acesso(email, metodo):
    """None = pode; (status, motivo) = recusa. ÚNICO lugar que decide acesso no Postgres:
    cadastro ativo, e nada de escrita para leitor nem com SOMENTE_LEITURA."""
    if not email:
        return 401, "Login ausente ou inválido — recarregue a página."
    s = _sessao_pg_de(email)
    if s is None:
        return 403, "Seu e-mail não tem acesso ao app — peça à gestão do projeto."
    if metodo not in _METODOS_LEITURA and (SOMENTE_LEITURA or s["papel"] == "leitor"):
        return 403, "Somente leitura."
    return None
```

Em `_OBOAuthMiddleware.__call__`, logo depois de `reset = _user_token.set(token)`:

```python
        email = _email_da_requisicao(scope) if dialeto.PG else None
        reset_email = _usuario_email.set(email)
        caminho = scope.get("path", "")
        if dialeto.PG and caminho.startswith("/api/") and caminho not in _LIVRES_PG:
            try:
                negado = await anyio.to_thread.run_sync(_nega_acesso, email, scope.get("method", "GET"))
            except HTTPException as e:  # banco fora do ar: fora dos handlers do FastAPI, viraria 500
                negado = (e.status_code, e.detail)
            if negado:
                _usuario_email.reset(reset_email)
                _user_token.reset(reset)
                await JSONResponse({"detail": negado[1]}, status_code=negado[0])(scope, receive, send)
                return
```

No bloco `finally` do mesmo método, junto de `_user_token.reset(reset)`, acrescente `_usuario_email.reset(reset_email)`. Nos imports do topo: `import anyio`. `JSONResponse` já é importado (`from fastapi.responses import JSONResponse`).

- [ ] **Step 5: `/api/me` com o papel.** Troque o corpo de `me()` (`main.py:686`) por:

```python
    try:
        s = _sessao()
        # papel só existe no Postgres (ADR 0005); no Databricks a resposta segue {user}
        return {"user": s["user"], "papel": s["papel"]} if "papel" in s else {"user": s["user"]}
    except HTTPException:
        return {"user": None}
```

- [ ] **Step 6: Rodar e ver passar**

```bash
python -m pytest -q egps_analysis/app/backend/test_acesso_pg.py
```

Esperado: `23 passed`, e a suíte inteira do backend verde.

- [ ] **Step 7: Checkpoint de commit** (só se pedido): `feat(app): identidade do load balancer e acesso por papel no Postgres`.

### Task C6: `/api/config` com sincronização e filtro do "Com BV"

**Files:**
- Modify: `egps_analysis/app/backend/main.py` (`config()` `:4281`, `gestao_rows()` `:8330`)
- Modify: `egps_analysis/app/backend/test_acesso_pg.py`

- [ ] **Step 1: Testes** (acrescente):

```python
def test_config_traz_sincronizacao_e_modo_leitura(monkeypatch):
    c = _cliente(monkeypatch, "leitor", somente_leitura=True)
    monkeypatch.setattr(m, "_sincronizado_em", lambda: "2026-10-14T12:00:00.000Z")
    cfg = c.get("/api/config").json()
    assert cfg["somente_leitura"] is True and cfg["sincronizado_em"] == "2026-10-14T12:00:00.000Z"


def test_quem_nao_e_gestao_ve_so_o_estado_atual_do_com_bv():
    payload = {"rows": [{"id": "A", "bvEventos": [
        {"id": "1", "comBv": True, "data": "2026-10-01", "autor": "x@indicium.ai"},
        {"id": "2", "comBv": False, "data": "2026-10-05", "autor": "y@indicium.ai"}]},
        {"id": "B", "bvEventos": []}]}
    out = m._sem_historico_com_bv(payload)
    assert out["rows"][0]["bvEventos"] == [{"comBv": False, "data": "2026-10-05"}]
    assert out["rows"][1]["bvEventos"] == []
    assert payload["rows"][0]["bvEventos"][0]["autor"] == "x@indicium.ai"   # original intacto (cache)
```

- [ ] **Step 2: Rodar e ver falhar** (`KeyError: 'somente_leitura'`, `no attribute '_sem_historico_com_bv'`).

- [ ] **Step 3: Implementar.** Antes de `@app.get("/api/config")`:

```python
def _sincronizado_em():
    """Fim da última sincronização boa (só na AWS). O front mostra "dados de HH:MM" e fica
    vermelho quando envelhece — falha da sincronização não pode passar em silêncio."""
    if not dialeto.PG:
        return None
    r = run_sql("SELECT max(concluida_em) AS em FROM historico.publicacao "
                "WHERE ok AND origem = 'sync_databricks'")
    return r[0]["em"] if r else None
```

No dicionário devolvido por `config()`, acrescente:

```python
            "somente_leitura": SOMENTE_LEITURA,
            "sincronizado_em": _sincronizado_em(),
```

Antes de `@app.get("/api/gestao/rows")`:

```python
def _sem_historico_com_bv(payload):
    """Para quem não é da gestão, o registro "Com BV" vira só o ESTADO ATUAL (último evento,
    sem id nem autor). Hoje a tela já esconde o histórico desse público, mas a rota o
    devolvia a qualquer logado. Copia: o payload original está no cache compartilhado."""
    linhas = []
    for r in payload.get("rows", []):
        ev = r.get("bvEventos") or []
        ult = [{"comBv": ev[-1].get("comBv"), "data": ev[-1].get("data")}] if ev else []
        linhas.append({**r, "bvEventos": ult})
    return {**payload, "rows": linhas}
```

E troque o corpo de `gestao_rows` por:

```python
    payload = _cache_endpoint(("gestao_rows", entity), lambda: _gestao_rows_uncached(entity))
    return payload if _is_gestao() else _sem_historico_com_bv(payload)
```

- [ ] **Step 4: Rodar e ver passar.** Esperado: `25 passed` no arquivo e a suíte inteira verde (711 em 2026-10-14).

- [ ] **Step 5: Checkpoint de commit** (só se pedido): `feat(app): config com sincronização; Com BV só para gestão`.

---

## Parte D — Comparador de leituras

### Task D1: Comparador

**Files:**
- Create: `egps_analysis/app/paridade/__init__.py` (vazio)
- Create: `egps_analysis/app/paridade/compara.py`
- Test: `egps_analysis/app/paridade/test_compara.py`

- [ ] **Step 1: Escrever o teste** `paridade/test_compara.py`

```python
# -*- coding: utf-8 -*-
"""Comparador de leituras: normaliza forma, nunca conteúdo; ordem continua contando."""
import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from paridade import compara as c  # noqa: E402


def test_forma_nao_e_diferenca():
    antigo = {"n": "12", "vazio": "", "ts": "2026-10-14T15:04:05.123Z", "flag": "true"}
    novo = {"n": "12.0", "vazio": None, "ts": "2026-10-14 15:04:05+00:00", "flag": "true"}
    assert c.diferencas(c.normaliza(antigo), c.normaliza(novo)) == []


def test_conteudo_e_diferenca():
    dif = c.diferencas(c.normaliza({"n": "12"}), c.normaliza({"n": "13"}))
    assert dif == [("$.n", 12.0, 13.0)]


def test_identificador_com_zero_a_esquerda_continua_texto():
    assert c.normaliza("0012") == "0012"


def test_ordem_diferente_e_diferenca_marcada_como_so_ordem():
    a, b = [{"x": 1}, {"x": 2}], [{"x": 2}, {"x": 1}]
    assert c.diferencas(c.normaliza(a), c.normaliza(b))
    assert c.so_ordem(c.normaliza(a), c.normaliza(b))


def test_compara_registra_erro_de_rota_sem_parar():
    def busca(base, rota):
        if rota == "/api/quebra":
            raise RuntimeError("502")
        return {"ok": True}
    rel = c.compara("http://a", "http://b", ["/api/ok", "/api/quebra"], busca=busca)
    assert rel["/api/ok"]["igual"] and "erro" in rel["/api/quebra"]


def test_rotas_get_ignora_parametro_de_caminho_e_metodo_de_escrita():
    app = NS(routes=[NS(path="/api/a", methods={"GET"}), NS(path="/api/b/{id}", methods={"GET"}),
                     NS(path="/api/c", methods={"PATCH"}), NS(path="/static", methods={"GET"})])
    assert c.rotas_get(app) == ["/api/a"]
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
python -m pytest -q egps_analysis/app/paridade/test_compara.py
```

Esperado: erro de import.

- [ ] **Step 3: Implementar** `paridade/compara.py`

```python
# -*- coding: utf-8 -*-
"""Compara as leituras do app antigo (Databricks) com as do novo (Postgres) — ADR 0005.

Critério de pronto da Fase 1: para cada rota GET, o JSON do app novo é igual ao do antigo
partindo dos mesmos dados. Antes de comparar, normaliza só o que é FORMA e não conteúdo:
texto vazio = nulo (as telas tratam igual), instantes = UTC ao segundo, números = valor.
Ordem de lista NÃO é normalizada — ordem diferente é diferença real (NULLs primeiro no
Spark, por último no Postgres) e aparece marcada como "só ordem" para ajudar o diagnóstico.

Uso: python -m paridade.compara --antigo http://localhost:8000 --novo http://localhost:8001 \
         --saida paridade/relatorio.json [--rota /api/config ...]
"""
import argparse
import datetime
import json
import re
import sys
import urllib.request

_INSTANTE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
_NUMERO = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


def normaliza(v):
    if isinstance(v, dict):
        return {k: normaliza(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [normaliza(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        if _INSTANTE.match(s):
            d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if _NUMERO.match(s) and not (len(s) > 1 and s[0] == "0" and s[1] != "."):
            return float(s)          # "0012" fica texto: é identificador, não número
        return v
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def diferencas(a, b, caminho="$", limite=50):
    """Lista de (caminho, antigo, novo) — no máximo `limite` itens."""
    saida = []

    def anda(x, y, c):
        if len(saida) >= limite:
            return
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                anda(x.get(k, "<ausente>"), y.get(k, "<ausente>"), f"{c}.{k}")
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                saida.append((f"{c}[len]", len(x), len(y)))
            for i, (p, q) in enumerate(zip(x, y)):
                anda(p, q, f"{c}[{i}]")
        elif x != y:
            saida.append((c, x, y))

    anda(a, b, caminho)
    return saida


def so_ordem(a, b):
    """True quando as listas têm os mesmos itens em ordem diferente."""
    if not (isinstance(a, list) and isinstance(b, list)) or len(a) != len(b):
        return False
    chave = lambda x: json.dumps(x, sort_keys=True, default=str)  # noqa: E731
    return sorted(map(chave, a)) == sorted(map(chave, b))


def rotas_get(app):
    """Rotas GET da API sem parâmetro de caminho (as com {id} entram na 1b, com amostras)."""
    rotas = []
    for r in app.routes:
        caminho = getattr(r, "path", "")
        if "GET" in getattr(r, "methods", set()) and caminho.startswith("/api/") and "{" not in caminho:
            rotas.append(caminho)
    return sorted(set(rotas))


def _busca(base, rota):
    with urllib.request.urlopen(base.rstrip("/") + rota, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def compara(antigo, novo, rotas, busca=_busca):
    relatorio = {}
    for rota in rotas:
        try:
            a, b = normaliza(busca(antigo, rota)), normaliza(busca(novo, rota))
        except Exception as e:  # noqa: BLE001 — erro de rota é resultado, não para o resto
            relatorio[rota] = {"erro": f"{type(e).__name__}: {e}"}
            continue
        dif = diferencas(a, b)
        relatorio[rota] = {"igual": not dif, "so_ordem": bool(dif) and so_ordem(a, b),
                           "diferencas": [list(d) for d in dif]}
    return relatorio


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compara leituras do app antigo e do novo")
    ap.add_argument("--antigo", required=True)
    ap.add_argument("--novo", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--rota", action="append", help="rota GET (repita); padrão: todas")
    args = ap.parse_args(argv)
    if args.rota:
        rotas = args.rota
    else:
        sys.path.insert(0, "backend")
        from backend import main as app_main  # import tardio: só para listar as rotas
        rotas = rotas_get(app_main.app)
    rel = compara(args.antigo, args.novo, rotas)
    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump(rel, f, ensure_ascii=False, indent=2, default=str)
    iguais = sum(1 for v in rel.values() if v.get("igual"))
    print(f"[paridade] {iguais}/{len(rel)} rotas iguais — relatório em {args.saida}")
    sys.exit(0 if iguais == len(rel) else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar e ver passar.** Esperado: `6 passed`.

- [ ] **Step 5: Primeira comparação real, só da rota que a fatia já cobre.** O app antigo roda local lendo **dev**, e o novo roda local no Postgres sincronizado a partir de dev (B3, Step 2). Os comandos rodam em terminais separados, a partir de `egps_analysis/app`:

```bash
env PUBLISH_SCHEMA=monitoramento_sas_dev DATABRICKS_CONFIG_PROFILE=bv DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd APP_PORT=8000 FAMILIAS_SAFRA=1 python backend/main.py
```

```bash
env DB_BACKEND=postgres PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento PUBLISH_SCHEMA=compat IDENTIDADE=dev DEV_USUARIO=lucas.muller@indicium.ai APP_PORT=8001 FAMILIAS_SAFRA=1 python backend/main.py
```

Antes, cadastre-se como gestão no banco local:

```bash
docker exec pg17-monitoramento psql -U postgres -d monitoramento -c "UPDATE cadastro.usuario SET papel = 'gestao', ativo = true WHERE email = 'lucas.muller@indicium.ai'"
```

Se a linha não existir, faça `INSERT INTO cadastro.usuario (email, nome, papel) VALUES ('lucas.muller@indicium.ai', 'Lucas Muller', 'gestao')`.

```bash
python -m paridade.compara --antigo http://localhost:8000 --novo http://localhost:8001 --saida /tmp/paridade-config.json --rota /api/config
```

Esperado: as `areas` iguais. As chaves novas (`somente_leitura`, `sincronizado_em`) aparecem como `<ausente>` no antigo, o que é **diferença esperada**: anote no relatório de diferenças aceitas, que nasce aqui e cresce na 1b. Esta é a prova de ponta a ponta de que o caminho Databricks → sincronização → Postgres → API funciona. Resultado de 2026-10-14, já com collation C: `areas` iguais; diferem só `scope` (`compat`), `sincronizado_em` (null no antigo) e `is_admin` (no Postgres o papel vem do cadastro, semeado na H2). As três são diferenças aceitas.

- [ ] **Step 6: Checkpoint de commit** (só se pedido): `feat(app): comparador de leituras antigo x novo`.

---

## Parte E — Front: faixa de sincronização e "sem acesso"

### Task E1: Faixa, tipo e tela de sem acesso

**Files:**
- Modify: `egps_analysis/app/frontend/src/types.ts` (`AppConfig`, `:117`)
- Create: `egps_analysis/app/frontend/src/components/SincronizacaoBanner.tsx`
- Modify: `egps_analysis/app/frontend/src/App.tsx` (`:146`, header)
- Modify: `egps_analysis/app/frontend/src/styles.css`

- [ ] **Step 1: Tipo.** Em `AppConfig`, antes de `}`:

```ts
  // App na AWS (ADR 0005): true = ninguém escreve (Fase 1); horário da última sincronização
  // boa com o Databricks (null fora da AWS).
  somente_leitura?: boolean;
  sincronizado_em?: string | null;
```

- [ ] **Step 2: Componente** `components/SincronizacaoBanner.tsx`

```tsx
// Faixa "dados de HH:MM" do app na AWS (ADR 0005, Fase 1): os dados vêm do Databricks por
// sincronização a cada 15 min, das 8h às 20h. Parada há mais de 1 h no horário comercial, a
// faixa fica vermelha — sincronização que falha não pode passar em silêncio.
import { useEffect, useState } from "react";

const LIMITE_MS = 60 * 60 * 1000;
const SP = "America/Sao_Paulo";

function horarioComercial(agora: Date): boolean {
  const h = Number(new Intl.DateTimeFormat("pt-BR", { hour: "numeric", hourCycle: "h23", timeZone: SP }).format(agora));
  return h >= 8 && h < 20;
}

export default function SincronizacaoBanner({ em }: { em: string }) {
  const [agora, setAgora] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setAgora(new Date()), 60_000);
    return () => window.clearInterval(t);
  }, []);
  const quando = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: SP }).format(new Date(em));
  const atrasada = horarioComercial(agora) && agora.getTime() - new Date(em).getTime() > LIMITE_MS;
  return (
    <div className={atrasada ? "sync-banner sync-banner-atrasada" : "sync-banner"} role="status">
      {atrasada
        ? `Dados desatualizados: a última sincronização foi em ${quando}. Avise a gestão do projeto.`
        : `Dados de ${quando} — atualizados a cada 15 min, das 8h às 20h.`}
    </div>
  );
}
```

- [ ] **Step 3: App.tsx.** Importe o componente (`import SincronizacaoBanner from "./components/SincronizacaoBanner";`) e um estado de acesso. Troque a linha `api.config().then(setCfg).catch(() => {});` (`:146`) por:

```tsx
    api.config().then(setCfg).catch((e: { status?: number }) => {
      if (e?.status === 403) setSemAcesso(true);
    });
```

Junto dos outros `useState` (perto de `:72`): `const [semAcesso, setSemAcesso] = useState(false);`. Logo antes do `return (` principal:

```tsx
  if (semAcesso) {
    return (
      <div className="sem-acesso">
        <h1>Painel de Modernização SAS</h1>
        <p>Seu e-mail não tem acesso a este app. Peça à gestão do projeto para cadastrá-lo.</p>
      </div>
    );
  }
```

E logo depois de `</header>`:

```tsx
      {cfg?.sincronizado_em && <SincronizacaoBanner em={cfg.sincronizado_em} />}
```

- [ ] **Step 4: Estilos.** Ao fim de `styles.css`:

```css
/* App na AWS (ADR 0005): faixa da sincronização e tela de sem acesso */
.sync-banner { padding: 6px 16px; font-size: 13px; background: var(--panel2); color: var(--mut); }
.sync-banner-atrasada { background: var(--tone-cyc-bg); color: var(--tone-cyc-fg); font-weight: 600; }
.sem-acesso { max-width: 560px; margin: 15vh auto; padding: 0 16px; text-align: center; }
```

- [ ] **Step 5: Build** (o `tsc -b` é o teste de tipos do front):

```bash
npm --prefix egps_analysis/app/frontend run build
```

Esperado: build sem erro. Com o backend novo da D1 rodando, abra `http://localhost:8001` (servido pelo próprio backend após o build) e confira a faixa "Dados de …". Mude `DEV_USUARIO` para um e-mail não cadastrado, reinicie e confira a tela de sem acesso.

- [ ] **Step 6: Checkpoint de commit** (só se pedido): `feat(app): faixa de sincronização e tela de sem acesso`.

---

## Parte T — Ensaio diário na training (antes das PRs de produção)

Pedido do usuário: subir primeiro na training e validar, **subindo todo dia** (a conta é apagada à noite), e só depois abrir as PRs de produção. Ordem: **A–E e G1 prontos → Parte T até o critério de pronto → Parte F**. O passo 0 (login) corre em paralelo, porque é PR de produção e não depende disto.

O que a training valida e o que não valida:

| Valida | Não valida (e onde é validado) |
|---|---|
| A imagem sobe no Fargate; o RDS Postgres 17 aceita as migrações; o app roda no modo Postgres com `SET ROLE app_leitura`; papéis, só leitura, faixa de sincronização, front; o caminho de carga (de-para → retrato → carga atômica) com massa sintética | Login do Google (passo 0, na produção — sem domínio na training); sincronização com o Databricks real (dev da AWS, Parte H — dado do BV não entra na training) |

Pré-requisitos: profile SSO **`indicium-training`** na sua máquina (conta `196029031078`, papel **`Learner`**, Identity Center em `us-east-1`) e uma sessão aberta com `aws sso login --profile indicium-training`; seu usuário precisa estar no grupo `IndiciumTraining-Learners` (ou `IndiciumTech-Admins`), o que é pedido ao SecurityBOT. O `Learner` libera tudo que o ensaio cria (só nega criar usuário/chave IAM, organização, faturamento e regiões fora de `us-east-1`/`sa-east-1`). Docker, Terraform ≥ 1.5 e o `.venv` do app com o `requirements.txt` (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, em `egps_analysis/app`; `PYTHON=` troca o interpretador).

**Por que o Terraform do ensaio fica no repo do app, e não no `indicium_infra`:** lá, o merge na `master` dispara o apply de training pelo CI, que quebraria sem a chave de estado do dia; e isto é ferramenta de ensaio, não infraestrutura compartilhada. O estado vai para o bucket protegido do nuke (`indicium-training-tfstate`), um arquivo por dia.

### Task T1: Massa sintética

**Files:**
- Create: `egps_analysis/app/sync/sintetico.py`
- Test: `egps_analysis/app/sync/test_sintetico.py`

- [ ] **Step 1: Teste**

```python
# -*- coding: utf-8 -*-
"""Massa sintética do ensaio: passa pelo caminho real e enche as views compat."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import migra  # noqa: E402
from sync import sintetico  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")


def test_massa_e_deterministica():
    assert sintetico.linhas() == sintetico.linhas()


@pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")
def test_carga_sintetica_enche_o_app():
    import psycopg
    nome = "t_sint_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    base, _, _ = DSN.rpartition("/")
    dsn = f"{base}/{nome}"
    try:
        migra.aplica(dsn, saida=lambda *_: None)
        with psycopg.connect(dsn) as conn:
            resumo = sintetico.carrega_sintetico(conn, gestao="Treino@indicium.ai")
            assert resumo["corpus.egp"] == 40 and resumo["corpus.input"] == 300
            assert resumo["ancoras_acrescentadas"]["input"] == 0
            n, escopo = conn.execute("SELECT count(*), count(*) FILTER (WHERE escopo_indi) "
                                     "FROM compat.sas_inputs_monitor").fetchone()
            assert n == 300 and 0 < escopo < 300
            assert conn.execute("SELECT papel, ativo FROM cadastro.usuario "
                                "WHERE email = 'treino@indicium.ai'").fetchone() == ("gestao", True)
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE {nome} WITH (FORCE)")
```

- [ ] **Step 2: Rodar e ver falhar** — `env PG_TEST_DSN=postgresql://postgres@127.0.0.1:55432/postgres python -m pytest -q egps_analysis/app/sync/test_sintetico.py`. Esperado: `cannot import name 'sintetico'`.

- [ ] **Step 3: Implementar**

```python
# -*- coding: utf-8 -*-
"""Massa SINTÉTICA no formato do Databricks, para o ensaio diário na training (ADR 0005).

A training não recebe dado do BV (é compartilhada e apagada toda noite pelo aws-nuke). Esta
massa passa pelo MESMO caminho da sincronização real (de-para -> retrato -> carga atômica),
então o ensaio exercita o código de verdade, só que com nomes inventados.

Uso: PG_DSN=... python -m sync.sintetico [--gestao fulano@indicium.ai]
"""
import argparse
import os
import random
import uuid

import psycopg

from . import carrega, retrato

AREAS = ("Cobranças", "Riscos", "Jurídico")
ETAPAS = (("A Receber", "A Iniciar"), ("Recebido", "A Iniciar"), ("Pré-Working", "Em Andamento"),
          ("Modernizado", "Concluído"), ("Modernizado", "Sanitizado"))
MOLDES = (("tabela", "LIB{n}.TAB_{i:04d}"), ("arquivo", "ARQ_{i:04d}.CSV"), ("script", "SCRIPT_{i:04d}.SAS"))


def linhas(n_egps=40, n_inputs=300, semente=42):
    """Linhas das 5 tabelas Delta que a fatia 1a sincroniza, todas como TEXTO (igual ao
    Databricks). Determinístico pela semente: o ensaio de hoje é igual ao de ontem."""
    rnd = random.Random(semente)
    egps = [f"{AREAS[i % 3]}__EGP_TREINO_{i:03d}" for i in range(n_egps)]
    inputs = []
    for i in range(n_inputs):
        cat, molde = MOLDES[i % 3]
        art = molde.format(n=i % 7, i=i)
        etapa, status = rnd.choice(ETAPAS)
        inputs.append({
            "chave_canonica": f"{cat}::{art}", "artifact": art, "categoria": cat,
            "source_types": "PROC SQL | DATA", "qtd_projetos": str(rnd.randint(1, 4)),
            "areas": " | ".join(sorted(rnd.sample(AREAS, rnd.randint(1, 2)))),
            "modernizada_auto": "Disponível" if etapa == "Modernizado" else "A ingerir",
            "responsavel": "", "observacao": None, "updated_at": None, "updated_by": None,
            "orfao": "false", "refreshed_at": "2026-10-15T09:00:00.000Z",
            "origem": rnd.choice(("BigQuery", "Transacional", "Arquivo")), "paths_fisicos": None,
            "etapa": etapa, "status": status})
    pares = []
    for p in egps:
        for r in rnd.sample(inputs, rnd.randint(3, 8)):
            pares.append({"projeto": p, "chave_canonica": r["chave_canonica"], "artifact": r["artifact"],
                          "categoria": r["categoria"], "source_types": "PROC SQL"})
    nos = [{"projeto": p, "area": p.split("__")[0], "ciclo_id": "0",
            "n_inputs": str(sum(1 for x in pares if x["projeto"] == p))} for p in egps]
    escopo = [{"id": uuid.UUID(int=rnd.getrandbits(128)).hex, "egp_dor1": p.split("__")[1],
               "area": p.split("__")[0], "status_extracao": "exato", "projeto": p, "origem": "csv",
               "created_by": None, "created_at": "seed", "ativo": "true"}
              for p in egps[: n_egps * 2 // 3]]
    return {"sas_lineage_nodes": nos, "sas_inputs_monitor": inputs, "sas_egp_inputs": pares,
            "sas_escopo": escopo, "sas_analistas": []}


def carrega_sintetico(conn, gestao=None):
    resumo = carrega.carrega(conn, retrato.monta(linhas()), "sintetico")
    if gestao:
        conn.execute("INSERT INTO cadastro.usuario (email, nome, papel) VALUES (%s, %s, 'gestao') "
                     "ON CONFLICT (email) DO UPDATE SET papel = 'gestao', ativo = true",
                     (gestao.strip().lower(), gestao))
        conn.commit()
    return resumo


def main(argv=None):
    ap = argparse.ArgumentParser(description="Carga sintética para o ensaio na training")
    ap.add_argument("--gestao", help="e-mail que entra como gestão (o DEV_USUARIO do ensaio)")
    args = ap.parse_args(argv)
    with psycopg.connect(os.environ.get("PG_DSN") or "") as conn:
        print(f"[sintetico] OK {carrega_sintetico(conn, args.gestao)}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar e ver passar.** Esperado: `2 passed` (40 EGPs, 300 inputs, nenhuma âncora acrescentada, gestão cadastrada).

### Task T2: Teste de fumaça

**Files:**
- Create: `egps_analysis/app/treino/__init__.py` (vazio), `egps_analysis/app/treino/fumaca.py`
- Test: `egps_analysis/app/treino/test_fumaca.py`

- [ ] **Step 1: Teste**

```python
# -*- coding: utf-8 -*-
"""Fumaça: passa com o app saudável e aponta exatamente o que quebrou."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from treino import fumaca  # noqa: E402

SAUDAVEL = {
    ("GET", "/api/health"): (200, "{}"),
    ("GET", "/api/me"): (200, json.dumps({"user": "treino@indicium.ai", "papel": "gestao"})),
    ("GET", "/api/config"): (200, json.dumps({"somente_leitura": True, "sincronizado_em": "2026-10-15T12:00:00.000Z"})),
    ("PATCH", "/api/inputs"): (403, '{"detail": "Somente leitura."}'),
    ("GET", "/"): (200, "<!doctype html><html></html>"),
}


def _pede_de(respostas):
    return lambda base, caminho, metodo="GET": respostas[(metodo, caminho)]


def test_app_saudavel_passa_em_tudo():
    res = fumaca.verifica("http://x", "Treino@indicium.ai", pede=_pede_de(SAUDAVEL))
    assert all(ok for ok, _ in res) and len(res) == 5


def test_escrita_liberada_e_falha():
    r = dict(SAUDAVEL)
    r[("PATCH", "/api/inputs")] = (200, "{}")
    res = fumaca.verifica("http://x", pede=_pede_de(r))
    assert [ok for ok, _ in res] == [True, True, True, False, True]


def test_sem_sincronizacao_e_falha():
    r = dict(SAUDAVEL)
    r[("GET", "/api/config")] = (200, json.dumps({"somente_leitura": True, "sincronizado_em": None}))
    assert not fumaca.verifica("http://x", pede=_pede_de(r))[2][0]


def test_usuario_errado_e_falha():
    assert not fumaca.verifica("http://x", "outro@indicium.ai", pede=_pede_de(SAUDAVEL))[1][0]
```

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest -q egps_analysis/app/treino/test_fumaca.py`. Esperado: erro de import.

- [ ] **Step 3: Implementar**

```python
# -*- coding: utf-8 -*-
"""Teste de fumaça do app no ar — ensaio diário na training e subida de prod (ADR 0005).

Uso: python -m treino.fumaca http://<endereço> [--usuario fulano@indicium.ai]
Imprime uma linha por verificação e sai com 1 se alguma falhar.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


def _pede(base, caminho, metodo="GET"):
    req = urllib.request.Request(base.rstrip("/") + caminho, method=metodo,
                                 data=None if metodo == "GET" else b"{}",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _json(st, corpo):
    try:
        return json.loads(corpo) if st == 200 else {}
    except ValueError:
        return {}


def verifica(base, usuario=None, pede=_pede):
    """Lista de (passou, descrição), na ordem em que um problema costuma aparecer."""
    res = []
    st, _ = pede(base, "/api/health")
    res.append((st == 200, f"/api/health -> {st}"))
    st, corpo = pede(base, "/api/me")
    me = _json(st, corpo)
    ok = bool(me.get("user")) and (usuario is None or me["user"] == usuario.lower())
    res.append((ok, f"/api/me -> {st} {me}"))
    st, corpo = pede(base, "/api/config")
    cfg = _json(st, corpo)
    ok = cfg.get("somente_leitura") is True and bool(cfg.get("sincronizado_em"))
    res.append((ok, f"/api/config -> {st} somente_leitura={cfg.get('somente_leitura')} "
                    f"sincronizado_em={cfg.get('sincronizado_em')}"))
    st, _ = pede(base, "/api/inputs", "PATCH")
    res.append((st == 403, f"PATCH /api/inputs -> {st} (esperado 403: só leitura)"))
    st, corpo = pede(base, "/")
    res.append((st == 200 and "<html" in corpo.lower(), f"/ -> {st} (front)"))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Teste de fumaça do app no ar")
    ap.add_argument("base")
    ap.add_argument("--usuario", help="e-mail esperado em /api/me")
    a = ap.parse_args(argv)
    falhou = False
    for passou, desc in verifica(a.base, a.usuario):
        print(f"[fumaca] {'OK   ' if passou else 'FALHA'} {desc}", flush=True)
        falhou = falhou or not passou
    sys.exit(1 if falhou else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar e ver passar.** Esperado: `4 passed`. A mesma fumaça serve à subida de prod (Task H3), apontando para o endereço de prod depois do login.

### Task T3: Terraform do ensaio

**Files** (em `egps_analysis/app/treino/terraform/`): `provider.tf`, `vars.tf`, `rede.tf`, `banco.tf`, `app.tf`, `outputs.tf`

Diferenças deliberadas para produção: VPC própria (a training não tem uma que sobreviva à noite); ALB **HTTP fechado por IP** e `IDENTIDADE=dev` (sem domínio não há login do Google); RDS acessível só dos IPs permitidos (as migrações e a massa rodam da sua máquina), sem backup e sem proteção de exclusão; nomes com sufixo `MMDD`. Engine, classe, imagem, variáveis do app, `SET ROLE` e o banco sem `db_name` (criado com collation C pelo `--cria-banco`) são os de produção.

- [ ] **Step 1: provider.tf**

```hcl
provider "aws" {
  profile = var.perfil_aws
  region  = "us-east-1"

  default_tags {
    tags = {
      Company   = "IndiciumTech"
      Ensaio    = "monitoramento-sas"
      ManagedBy = "Terraform"
    }
  }
}

terraform {
  # profile e key vêm no init (-backend-config): o profile é o seu SSO da training, e a key é
  # uma por DIA — a training é apagada toda noite pelo aws-nuke, e cada ensaio começa com
  # estado vazio em vez de tropeçar no que o nuke levou. O bucket é protegido do nuke.
  backend "s3" {
    region       = "us-east-1"
    bucket       = "indicium-training-tfstate"
    encrypt      = true
    use_lockfile = true
  }

  # >= 1.10 pelo use_lockfile (trava nativa do S3).
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}
```

- [ ] **Step 2: vars.tf**

```hcl
variable "perfil_aws" {
  description = "Profile SSO local da conta training (aws sso login --profile <este>)."
  type        = string
  default     = "indicium-training"
}

variable "sufixo" {
  description = "MMDD do ensaio: entra em todo nome, para não colidir com sobra do dia anterior."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{4}$", var.sufixo))
    error_message = "sufixo = MMDD (4 dígitos)."
  }
}

variable "ips_permitidos" {
  description = "CIDRs que alcançam o app e o banco do ensaio (seu IP, VPN). Não há login aqui."
  type        = list(string)
  validation {
    condition     = length(var.ips_permitidos) > 0 && !contains(var.ips_permitidos, "0.0.0.0/0")
    error_message = "Informe ao menos um CIDR e nunca 0.0.0.0/0: o ensaio não tem login."
  }
}

variable "dev_usuario" {
  description = "E-mail que o app usa como identidade (IDENTIDADE=dev) e que entra como gestão."
  type        = string
}

locals {
  nome = "monsas-treino-${var.sufixo}"
}
```

- [ ] **Step 3: rede.tf**

```hcl
# A training não tem VPC que sobreviva à noite: o ensaio cria a sua.
resource "aws_vpc" "treino" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = local.nome }
}

resource "aws_internet_gateway" "treino" {
  vpc_id = aws_vpc.treino.id
  tags   = { Name = local.nome }
}

resource "aws_subnet" "publica" {
  for_each                = { a = "10.42.1.0/24", b = "10.42.2.0/24" }
  vpc_id                  = aws_vpc.treino.id
  cidr_block              = each.value
  availability_zone       = "us-east-1${each.key}"
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.nome}-${each.key}" }
}

resource "aws_route_table" "publica" {
  vpc_id = aws_vpc.treino.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.treino.id
  }
  tags = { Name = local.nome }
}

resource "aws_route_table_association" "publica" {
  for_each       = aws_subnet.publica
  subnet_id      = each.value.id
  route_table_id = aws_route_table.publica.id
}

locals {
  subnets = [for s in aws_subnet.publica : s.id]
}
```

- [ ] **Step 4: banco.tf**

```hcl
# Banco do ensaio: mesma engine e classe de produção, mas descartável (o nuke leva à noite) e
# acessível do seu IP — as migrações e a massa sintética rodam da sua máquina. Só dado sintético.
resource "aws_security_group" "banco" {
  name        = "${local.nome}-rds"
  description = "Postgres do ensaio: tarefas do app e os IPs permitidos"
  vpc_id      = aws_vpc.treino.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
    description     = "App"
  }

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.ips_permitidos
    description = "Migracoes e massa sintetica, da maquina de quem ensaia"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_subnet_group" "banco" {
  name       = local.nome
  subnet_ids = local.subnets
}

resource "random_password" "mestre" {
  length  = 32
  special = false # vai num DSN montado pelo script; sem caractere que precise de escape
}

resource "aws_db_instance" "banco" {
  identifier     = local.nome
  engine         = "postgres"
  engine_version = "17"
  instance_class = "db.t3.micro"
  port           = 5432

  # Sem db_name: o banco do app nasce pelo `python -m db.migra --cria-banco`, com collation
  # C (ordem de bytes, como o Spark). O db_name o criaria com a collation de idioma da
  # instância, e as listas do app sairiam em outra ordem.
  username = "mestre"
  password = random_password.mestre.result

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_subnet_group_name   = aws_db_subnet_group.banco.name
  vpc_security_group_ids = [aws_security_group.banco.id]
  publicly_accessible    = true

  backup_retention_period = 0
  deletion_protection     = false
  skip_final_snapshot     = true
  apply_immediately       = true
}

# Para a tarefa do app ler a senha como em produção (secrets do ECS). Sem janela de
# recuperação: o nome do dia seguinte é outro, mas um segredo "em exclusão" não atrapalha.
resource "aws_secretsmanager_secret" "banco" {
  name                    = "${local.nome}/db"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "banco" {
  secret_id     = aws_secretsmanager_secret.banco.id
  secret_string = jsonencode({ db_password = random_password.mestre.result })
}
```

- [ ] **Step 5: app.tf**

```hcl
resource "aws_ecr_repository" "app" {
  name         = local.nome
  force_delete = true
}

resource "aws_iam_role" "execucao" {
  name = "${local.nome}-exec"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "execucao_base" {
  role       = aws_iam_role.execucao.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execucao_segredo" {
  name = "ler-segredo-do-banco"
  role = aws_iam_role.execucao.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.banco.arn] }]
  })
}

resource "aws_ecs_cluster" "treino" {
  name = local.nome
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.nome}"
  retention_in_days = 1
}

resource "aws_security_group" "alb" {
  name        = "${local.nome}-alb"
  description = "ALB do ensaio: HTTP so dos IPs permitidos (sem login, sem dado real)"
  vpc_id      = aws_vpc.treino.id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.ips_permitidos
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "app" {
  name        = "${local.nome}-app"
  description = "Tarefas do app: entrada so do ALB do ensaio"
  vpc_id      = aws_vpc.treino.id
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "treino" {
  name               = local.nome
  load_balancer_type = "application"
  subnets            = local.subnets
  security_groups    = [aws_security_group.alb.id]
}

resource "aws_lb_target_group" "app" {
  name        = local.nome
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.treino.id
  health_check {
    path    = "/api/health"
    matcher = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.treino.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# Mesma imagem e mesmas variáveis de produção, exceto a identidade: aqui não há login do
# Google (sem domínio), então IDENTIDADE=dev — o login é validado pela PR do passo 0.
resource "aws_ecs_task_definition" "app" {
  family                   = local.nome
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execucao.arn
  container_definitions = jsonencode([{
    name         = "app"
    image        = "${aws_ecr_repository.app.repository_url}:treino"
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "DB_BACKEND", value = "postgres" },
      { name = "PUBLISH_SCHEMA", value = "compat" },
      { name = "IDENTIDADE", value = "dev" },
      { name = "DEV_USUARIO", value = var.dev_usuario },
      { name = "SOMENTE_LEITURA", value = "1" },
      { name = "FAMILIAS_SAFRA", value = "1" },
      { name = "APP_PORT", value = "8000" },
      { name = "PGHOST", value = aws_db_instance.banco.address },
      { name = "PGPORT", value = "5432" },
      { name = "PGDATABASE", value = "monitoramento" },
      { name = "PGUSER", value = "mestre" },
      { name = "PG_PAPEL", value = "app_leitura" },
      { name = "PGSSLMODE", value = "require" },
    ]
    secrets = [
      { name = "PGPASSWORD", valueFrom = "${aws_secretsmanager_secret.banco.arn}:db_password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.app.name
        "awslogs-region"        = "us-east-1"
        "awslogs-stream-prefix" = "app"
      }
    }
  }])
}

resource "aws_ecs_service" "app" {
  name            = local.nome
  cluster         = aws_ecs_cluster.treino.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.subnets
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}
```

- [ ] **Step 6: outputs.tf**

```hcl
output "url" {
  value = "http://${aws_lb.treino.dns_name}"
}

output "ecr_url" {
  value = aws_ecr_repository.app.repository_url
}

output "rds_host" {
  value = aws_db_instance.banco.address
}

output "rds_senha" {
  value     = random_password.mestre.result
  sensitive = true
}

output "nome" {
  value = local.nome
}
```

- [ ] **Step 7: Validar** (estes 6 arquivos passaram em `validate` e `fmt -check` em 2026-10-14, provider AWS 6.69; backend com `use_lockfile`, Terraform ≥ 1.10):

```bash
terraform -chdir=egps_analysis/app/treino/terraform init -backend=false -input=false
```

```bash
terraform -chdir=egps_analysis/app/treino/terraform validate
```

```bash
terraform fmt -check egps_analysis/app/treino/terraform
```

Esperado: `Success! The configuration is valid.` e nenhum arquivo listado pelo `fmt`. Acrescente ao `.gitignore` do app `treino/terraform/.terraform` e `treino/terraform/*.tfplan`; o plan salvo carrega valores sensíveis. O `.terraform.lock.hcl` **é versionado**, como no `indicium_infra`, para todo ensaio usar a mesma versão do provider. Acrescente `treino` ao `.dockerignore`, porque o ensaio roda da máquina e não da imagem.

### Task T4: Script do ensaio diário

**Files:**
- Create: `egps_analysis/app/treino/confere_plano.py`, `egps_analysis/app/treino/test_confere_plano.py`
- Create: `egps_analysis/app/treino/sobe_treino.sh`

- [ ] **Step 0: Guarda do plan.** Nada de `apply -auto-approve`: o script salva o plan, e esta guarda recusa o apply se ele destruir ou substituir algo. O ensaio só cria (subida do zero) ou não muda nada (2ª rodada do dia). Teste:

```python
# -*- coding: utf-8 -*-
"""Guarda do ensaio: o plan só pode criar ou não mudar nada; destruir ou substituir para tudo."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from treino import confere_plano  # noqa: E402


def _plano(*acoes):
    return {"resource_changes": [{"address": f"aws_x.r{i}", "change": {"actions": a}}
                                 for i, a in enumerate(acoes)]}


def test_criar_e_nao_mudar_passam():
    assert confere_plano.destrutivos(_plano(["create"], ["no-op"], ["update"])) == []


def test_destruir_e_substituir_sao_apontados():
    p = _plano(["create"], ["delete"], ["delete", "create"], ["create", "delete"])
    assert confere_plano.destrutivos(p) == ["aws_x.r1", "aws_x.r2", "aws_x.r3"]


def test_plano_sem_mudanca_nenhuma_passa():
    assert confere_plano.destrutivos({}) == []


def test_main_sai_com_erro_e_nomeia_o_recurso(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(_plano(["delete"]))))
    with pytest.raises(SystemExit) as e:
        confere_plano.main()
    assert "aws_x.r0" in str(e.value)
```

Implementação (`4 passed` no teste acima):

```python
# -*- coding: utf-8 -*-
"""Guarda do ensaio diário: recusa aplicar plan que destrua ou substitua recurso.

O ensaio só cria (subida do zero) ou não muda nada (2ª rodada no mesmo dia, mesmo estado).
Destruir ali é sinal de estado ou sufixo errado — melhor parar do que aplicar às cegas.
Uso: terraform show -json <plan> | python -m treino.confere_plano
"""
import json
import sys


def destrutivos(plano):
    """Endereços dos recursos que o plan destruiria (inclui substituição: delete + create)."""
    return [r["address"] for r in plano.get("resource_changes", [])
            if "delete" in r["change"]["actions"]]


def main():
    ruins = destrutivos(json.load(sys.stdin))
    if ruins:
        sys.exit(f"ERRO: o plan destruiria ou substituiria {ruins}. Nada foi aplicado.")
    print("[treino] plan só cria ou não muda nada", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 1: Script** (passou em `bash -n`)

```bash
#!/bin/bash
# Ensaio diário do app na conta TRAINING (ADR 0005; plano 1a, Parte T).
# A training é apagada toda noite pelo aws-nuke: este script sobe TUDO do zero — infra,
# imagem, migrações e massa sintética — e termina no teste de fumaça. Nunca com dado do BV.
#
# Uso (a partir de egps_analysis/app), depois de `aws sso login --profile indicium-training`:
#   IPS='["203.0.113.7/32"]' DEV_USUARIO=fulano@indicium.ai bash treino/sobe_treino.sh
# PERFIL_AWS troca o profile (padrão indicium-training). O script confere a conta antes.
# PYTHON troca o interpretador (padrão .venv/bin/python, com o requirements.txt instalado).
set -euo pipefail
cd "$(dirname "$0")/.."

: "${IPS:?defina IPS, ex.: IPS='[\"203.0.113.7/32\"]' (seu IP e/ou a VPN)}"
: "${DEV_USUARIO:?defina DEV_USUARIO (o e-mail que entra como gestão no ensaio)}"
PERFIL="${PERFIL_AWS:-indicium-training}"
# Python com as dependências do app (requirements.txt); padrão: o .venv do app.
PY="${PYTHON:-.venv/bin/python}"
if ! command -v "$PY" > /dev/null; then
  echo "ERRO: sem $PY. Crie: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt (ou passe PYTHON=...)" >&2
  exit 1
fi
TF=treino/terraform
SUFIXO="$(date +%m%d)"
CONTA_TREINO=196029031078

conta=$(aws sts get-caller-identity --profile "$PERFIL" --query Account --output text)
if [ "$conta" != "$CONTA_TREINO" ]; then
  echo "ERRO: o profile '$PERFIL' aponta para a conta $conta, não para a training ($CONTA_TREINO). Abortado." >&2
  exit 1
fi

echo "[treino] infra do dia $SUFIXO"
terraform -chdir="$TF" init -reconfigure -input=false \
  -backend-config="profile=$PERFIL" \
  -backend-config="key=deploy/terraform/training-acc/monitoramento_sas_treino/$SUFIXO.tfstate"
# Nada de apply às cegas: o plan vai para arquivo, a guarda recusa se ele destruir ou
# substituir algo (o ensaio só cria, ou não muda nada na 2ª rodada do dia), e só ENTÃO se
# aplica exatamente aquele plan.
terraform -chdir="$TF" plan -input=false -out=treino.tfplan -var "perfil_aws=$PERFIL" \
  -var "sufixo=$SUFIXO" -var "ips_permitidos=$IPS" -var "dev_usuario=$DEV_USUARIO"
terraform -chdir="$TF" show -json treino.tfplan | "$PY" -m treino.confere_plano
terraform -chdir="$TF" apply -input=false treino.tfplan
rm -f "$TF/treino.tfplan"

ECR=$(terraform -chdir="$TF" output -raw ecr_url)
URL=$(terraform -chdir="$TF" output -raw url)
NOME=$(terraform -chdir="$TF" output -raw nome)
RDS=$(terraform -chdir="$TF" output -raw rds_host)
# senha só em variável de ambiente (nunca na linha de comando nem no log)
PGPASSWORD=$(terraform -chdir="$TF" output -raw rds_senha)
export PGPASSWORD
export PG_DSN="host=$RDS dbname=monitoramento user=mestre sslmode=require"

echo "[treino] imagem"
aws ecr get-login-password --profile "$PERFIL" --region us-east-1 \
  | docker login --username AWS --password-stdin "${ECR%%/*}"
docker build -t "$ECR:treino" .
docker push "$ECR:treino"

echo "[treino] banco, migrações e massa sintética"
# --cria-banco: o RDS nasce sem o banco do app (collation C só se escolhe ao criar)
"$PY" -m db.migra --cria-banco
"$PY" -m sync.sintetico --gestao "$DEV_USUARIO"

echo "[treino] serviço"
aws ecs update-service --profile "$PERFIL" --region us-east-1 --cluster "$NOME" \
  --service "$NOME" --force-new-deployment > /dev/null
aws ecs wait services-stable --profile "$PERFIL" --region us-east-1 --cluster "$NOME" --services "$NOME"

echo "[treino] fumaça em $URL"
"$PY" -m treino.fumaca "$URL" --usuario "$DEV_USUARIO"
echo "[treino] ensaio $SUFIXO OK — $URL (some à noite com o aws-nuke)"
```

- [ ] **Step 2: Primeiro ensaio** (a partir de `egps_analysis/app`; troque pelo seu IP):

```bash
aws sso login --profile indicium-training
```

```bash
env IPS='["203.0.113.7/32"]' DEV_USUARIO=lucas.muller@indicium.ai bash treino/sobe_treino.sh
```

Esperado, ao fim: cinco linhas `[fumaca] OK` e `[treino] ensaio MMDD OK — http://...`. Abra o endereço no navegador: o app com a faixa "Dados de …" e os 40 EGPs sintéticos. A 1ª execução do dia leva ~15 min (o RDS é o mais lento).

- [ ] **Step 3: Se falhar**, o log da tarefa está em `aws logs tail /ecs/monsas-treino-MMDD --profile indicium-training --since 30m`. Corrija, rode o script de novo (é idempotente no mesmo dia: mesmo estado, mesmo sufixo).

- [ ] **Step 4: Derrubar no mesmo dia** (para a 2ª subida do zero da T5, ou para não esperar o nuke). O `init` do script já deixou o backend apontando para o estado do dia:

```bash
terraform -chdir=treino/terraform destroy -input=false -auto-approve -var perfil_aws=indicium-training -var sufixo=MMDD -var ips_permitidos='["203.0.113.7/32"]' -var dev_usuario=lucas.muller@indicium.ai
```

### Task T5: Critério de pronto do ensaio (libera a Parte F)

- [ ] O script roda **do zero até a fumaça OK duas vezes**, sem intervenção manual, com um `terraform destroy` completo entre as duas (no mesmo dia ou não): prova que a subida não depende de sobra da anterior. Isso libera a Parte F. Decidido em 14/10, no lugar de "dois dias diferentes", para não perder um dia. O ensaio do dia seguinte continua, mas só para conferir a convivência com o aws-nuke, sem travar nada.
- [ ] Nenhum erro no log do app durante uma navegação pelas abas cobertas pela fatia (Resumo/Inputs com a massa sintética; as demais podem dar erro de SQL até a 1b — anote quais, é insumo da 1b).
- [ ] Memória e CPU observadas no ensaio anotadas para dimensionar a task de prod (F2 Step 5).
- [ ] Resultado registrado na spec (data, duração, o que quebrou e como foi corrigido).

**Ensaio 1 — 2026-10-14 (sufixo 1014): passou.** Do zero à fumaça 5/5 em 9,5 min, sem intervenção. Antes dele, a execução local corrigiu a collation do banco (C, igual ao Spark) e a resposta da checagem de acesso com o banco fora do ar (502, não 500). Das 48 rotas GET sem parâmetro de caminho, 22 respondem 200, 6 pedem parâmetro e 19 caem em view `compat` da 1b. Uma é dialeto: `split(...)[0]` em `/api/egp-readiness`. Memória e CPU com massa sintética não servem para dimensionar prod (detalhe na spec).

**Ensaio 2 — 2026-10-14, depois de um `destroy` completo: passou.** O `destroy` levou os 26 recursos. Cluster, serviço e task definition do ECS ficam como `INACTIVE`, que é como a AWS registra o que foi apagado. Do zero à fumaça 5/5 em 9,3 min, com os mesmos nomes, o que prova que os nomes liberados voltam a ser criados. **O critério da T5 está cumprido e a Parte F está liberada.**

---

## Parte F — Infra de produção (PRs, nesta ordem)

Ordem: **F1 (banco) → apply → F2 (app completo) → apply → F3 (rotação)**. F4 (conta de deploy) e F5 (conta de serviço no Databricks) correm em paralelo, mas precisam estar aplicadas antes da Parte H. Antes de cada PR: `git -C ~/indicium/indicium_infra pull` na `master`, e uma branch nova a partir dela.

> **Estado em 2026-10-14:** já há branches prontas, com commit local, para F1 (`aws/production-acc/rds/monitoramento-sas`), F4 (`aws/production-acc/IAM/monitoramento-sas-deploy`) e F5 (`feat/monitoramento-sas-sync-sp`, a partir da `main` do `indicium_databricks_aws_infra`, que não usa `master`). Cada uma tem `validate`, `tflint` e pre-commit verdes. F2 e F3 dependem de applies anteriores. No `IAM/variables.tf` da `master`, o `tflint` aponta uma variável sem uso (`restart_tag`); ela já estava lá antes desta mudança.

> **Revisão de boas práticas de Terraform (2026-10-14).** Já está nas branches e nos blocos abaixo:
> - `use_lockfile = true` no backend, com Terraform ≥ 1.10, como `lambda/indiguesser`;
> - provider `aws ~> 6.0`, para a próxima versão maior ser uma decisão e não um `init -upgrade`;
> - `prevent_destroy` no RDS, como segunda trava além do `deletion_protection`;
> - validações em `ambientes` (só as chaves prod e dev, `somente_leitura` só "0"/"1", prioridade única) e em `email_alarme`.
>
> Na bancada: o plan normal deu "No changes", inclusive depois da rotação; `plan -destroy` do banco parou em "Instance cannot be destroyed"; `somente_leitura = "sim"` reprovou o plan.
>
> O checkov apontou 29 itens, todos aceitos e com motivo:
> - **escolhas da ADR ou do plano:** sem Multi-AZ, senha mestre girada em vez de IAM auth, tags `:prod`/`:dev` móveis;
> - **padrão do repo:** saída liberada nos SGs, IP público em subnet pública sem NAT, HTTP entre o ALB e a tarefa;
> - **falsos positivos de outro root:** rotação na F3, SGs usados na F2 e no agendador;
> - **custo sem ganho aqui:** KMS próprio em log, ECR, SNS e agendador; retenção de 1 ano; Performance Insights.

### Task F1: Banco em root próprio (PR 1)

**Files** (em `indicium_infra/aws/production-acc/rds/monitoramento_sas/`): `provider.tf`, `main.tf`, `outputs.tf`

- [ ] **Step 1: provider.tf**

```hcl
provider "aws" {
  profile = "indicium"
  region  = "us-east-1"

  default_tags {
    tags = {
      Company = "IndiciumTech"
    }
  }
}

terraform {
  # >= 1.10 pelo use_lockfile (trava nativa do S3), como lambda/indiguesser.
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  backend "s3" {
    profile      = "indicium"
    bucket       = "indicium-data"
    key          = "deploy/terraform/rds/monitoramento_sas.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

- [ ] **Step 2: main.tf** (molde de `rds/knowledge_hub_mcp/main.tf`)

```hcl
# Postgres do app monitoramento-sas (ADR 0005). Instância própria: dado do cliente isolado,
# criptografado e com backup próprio. Dois bancos dentro dela: monitoramento (prod) e
# monitoramento_dev (dev), criados à mão (Parte H).

data "aws_vpc" "indicium_main" {
  filter {
    name   = "tag:Name"
    values = ["indicium-main-vpc"]
  }
}

data "aws_subnet" "indicium_main_public_1" {
  filter {
    name   = "tag:Name"
    values = ["indicium_main_public_1"]
  }
}

data "aws_subnet" "indicium_main_public_2" {
  filter {
    name   = "tag:Name"
    values = ["indicium_main_public_2"]
  }
}

data "aws_instance" "vpn_dsaas" {
  filter {
    name   = "tag:Name"
    values = ["pritunl-node-us"]
  }
}

# Quem está neste SG alcança o banco. O root do app (ecs_applications/monitoramento_sas)
# põe aqui as tarefas do app e da sincronização — e mais ninguém: diferente do ecs-sg, que
# abriria o banco para todo app do cluster compartilhado.
resource "aws_security_group" "cliente" {
  name        = "monitoramento-sas-db-client-sg"
  description = "Membros alcancam o Postgres do monitoramento-sas (app e sincronizacao)"
  vpc_id      = data.aws_vpc.indicium_main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = { Name = "monitoramento-sas-db-client-sg", ManagedBy = "Terraform" }
}

resource "aws_security_group" "banco" {
  name        = "monitoramento-sas-rds-sg"
  description = "Postgres do monitoramento-sas: so membros do client-sg e a VPN"
  vpc_id      = data.aws_vpc.indicium_main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.cliente.id]
    description     = "App e sincronizacao (membros do client-sg)"
  }

  # Pritunl faz NAT para o próprio IP privado (ver rds/knowledge_hub_mcp/main.tf).
  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["${data.aws_instance.vpn_dsaas.private_ip}/32"]
    description = "Postgres from the Pritunl VPN server (NAT), for admin access"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = { Name = "monitoramento-sas-rds-sg", ManagedBy = "Terraform" }
}

resource "aws_db_subnet_group" "banco" {
  name       = "monitoramento-sas-db-subnet-group"
  subnet_ids = [data.aws_subnet.indicium_main_public_1.id, data.aws_subnet.indicium_main_public_2.id]
  tags       = { Name = "monitoramento-sas-db-subnet-group", ManagedBy = "Terraform" }
}

resource "random_password" "mestre" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>?"
}

resource "random_id" "snapshot" {
  byte_length = 4
}

resource "aws_db_instance" "banco" {
  identifier = "monitoramento-sas-db"

  engine         = "postgres"
  engine_version = "17"
  instance_class = "db.t3.micro"
  port           = 5432

  # Sem db_name: os bancos do app (monitoramento e monitoramento_dev) nascem na H1 por
  # `python -m db.migra --cria-banco`, com collation C (ordem de bytes, como o Spark). O
  # db_name criaria o banco com a collation de idioma da instância.
  username = "mestre"
  password = random_password.mestre.result

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  multi_az               = false # simples por decisão (ADR 0005); backup diário cobre
  db_subnet_group_name   = aws_db_subnet_group.banco.name
  vpc_security_group_ids = [aws_security_group.banco.id]
  publicly_accessible    = false

  backup_retention_period = 7
  backup_window           = "02:00-03:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"
  copy_tags_to_snapshot   = true

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "monitoramento-sas-db-final-${random_id.snapshot.hex}"

  enabled_cloudwatch_logs_exports = ["postgresql"]
  monitoring_interval             = 0

  tags = {
    "Name"                     = "monitoramento-sas-db",
    "workload-type"            = "other",
    "ManagedBy"                = "Terraform",
    "backstage.spec.lifecycle" = "production",
    "backstage.spec.owner"     = "bv",
    "backstage.spec.system"    = "monitoramento-sas",
  }

  lifecycle {
    # random_password só semeia a senha na criação; depois ela é do indicium-secret-rotation
    # (Task F3). Sem isto, cada apply voltaria a senha do banco para a semente.
    ignore_changes = [password]
    # Segunda trava, além do deletion_protection: um plan que destrua ou SUBSTITUA o banco
    # (mudança de atributo que força recriação) falha já no plan da PR, não no apply.
    prevent_destroy = true
  }
}

# Chave `db_password`: é a que o indicium-secret-rotation sabe girar. O conteúdo é semeado
# uma vez aqui e depois pertence ao rotacionador (ignore_changes).
resource "aws_secretsmanager_secret" "credenciais" {
  name                    = "indicium-infra/rds/monitoramento-sas/credentials"
  description             = "Master credentials for monitoramento-sas-db (ADR 0005)"
  recovery_window_in_days = 7
  tags                    = { ManagedBy = "Terraform" }
}

resource "aws_secretsmanager_secret_version" "credenciais" {
  secret_id = aws_secretsmanager_secret.credenciais.id
  secret_string = jsonencode({
    engine      = "postgres"
    host        = aws_db_instance.banco.address
    port        = aws_db_instance.banco.port
    username    = aws_db_instance.banco.username
    db_password = random_password.mestre.result
    dbname      = "monitoramento"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
```

- [ ] **Step 3: outputs.tf**

```hcl
output "endpoint" {
  value = aws_db_instance.banco.address
}

output "client_sg_id" {
  value = aws_security_group.cliente.id
}
```

- [ ] **Step 4: Validar e abrir a PR** (`aws/production-acc/rds/monitoramento-sas`)

```bash
terraform -chdir=aws/production-acc/rds/monitoramento_sas init -backend=false
```

```bash
terraform -chdir=aws/production-acc/rds/monitoramento_sas validate
```

```bash
make -C ~/indicium/indicium_infra hooks
```

Esperado: válido e hooks verdes. O plano deve mostrar 2 SGs, 1 subnet group, 1 instância, 1 segredo com versão e 2 recursos `random`.

### Task F2: App completo (PR 2, depois do apply da F1)

> **Testado na training em 2026-10-14, antes de qualquer PR.** Montei uma bancada com réplicas, com os mesmos nomes e tags, do que as PRs leem da produção: VPC e sub-redes, a "VPN", o cluster e o ALB compartilhados, segredos de teste e a zona `training-indicium.com` no lugar de `hub.indicium.ai`. Apliquei os arquivos das PRs sem alteração (só uma camada `*_override.tf` troca conta, estado e domínio), na ordem F1 → passo 0 → F2 por cima do estado do passo 0. O teste pegou **dois bugs**, já corrigidos no texto abaixo:
> 1. A descrição do `aws_security_group.sync` tinha `->`, que a AWS recusa em SG (`InvalidParameterValue`). Agora: `Databricks para Postgres`. O `validate` não pega isso.
> 2. A política do agendador liberava `ecs:RunTask` no ARN da task definition **sem** revisão, mas a ECS autoriza o ARN **com** revisão: o agendador falhava a cada 15 min (`TargetErrorCount`) e a sincronização nunca rodava, sem linha de log nem alarme. Agora: `"${aws_ecs_task_definition.sync.arn_without_revision}:*"`. Confirmado no simulador de IAM e no agendador real.
>
> O resto passou:
> - Os `moved` levam a regra e o registro A do passo 0 sem destruir nada. No apply da transição, o provider avisa uma vez que o `fixed_response` antigo ficou no estado; o refresh seguinte limpa o aviso.
> - Os dois hosts mandam quem não tem login para o Google, com o `redirect_uri` certo. Os serviços ficam saudáveis atrás do ALB.
> - A política da F4 basta para o deploy do CI: login no ECR, push de `:prod`/`:dev`, `update-service` e espera.
> - As migrações rodam por **tarefa avulsa no ECS**, sem VPN (ver H1).
> - A falha da sincronização chega ao alarme e ao SNS.
>
> **Rodada 2, mesmo dia: login de ponta a ponta e rotação.** Com um Cognito da bancada no lugar do Google (só os endpoints OIDC da regra trocam), o login chega ao app com o `x-amzn-oidc-data` real assinado pelo ALB. Isso pegou o **terceiro bug**, o mais grave: o `auth_alb` tirava o padding `=` do JWT antes de conferir. O ALB assina o texto *com* o padding, então **todo login real era recusado**. O teste escondia o bug porque montava o token de outro jeito. Corrigido na C4. Depois disso:
> - gestão (prod) vê o papel e leva 403 ao escrever (só leitura);
> - leitor (dev) leva 403 pelo papel;
> - quem está fora do cadastro leva 403 em tudo.
>
> A rotação da F3 também passou, com o rotacionador da plataforma aplicado só com o nosso alvo: senha nova em 64 s, os dois serviços reiniciados e o app seguindo no banco. No RDS de verdade, `SET ROLE app_leitura` lê e é barrado ao escrever (`InsufficientPrivilege`), mesmo com o mestre no `rds_superuser`.

**Files** (em `indicium_infra/aws/production-acc/ecs_applications/monitoramento_sas/`):
- Modify: `data.tf`, `alb.tf` (o `provider.tf` do passo 0 fica como está)
- Create: `vars.tf`, `ecr.tf`, `iam.tf`, `ecs.tf`, `sync.tf`, `alarm.tf`, `policies/ecs_task_assume_role.json`, `policies/execution_secrets_policy.json`, `policies/scheduler_assume_role.json`

- [ ] **Step 1: vars.tf**

```hcl
variable "ambientes" {
  # dev com somente_leitura = "0" é o laboratório da Fase 2. Na 1a a sessão do dev também
  # baixa para app_leitura (PG_PAPEL), então escrever lá falha no banco até a Fase 2.
  description = "Instâncias do app: prod (só leitura na Fase 1) e dev (laboratório de escrita)."
  type = map(object({
    host            = string
    prioridade      = number
    banco           = string
    somente_leitura = string
  }))
  default = {
    prod = { host = "monitoramento-sas.hub.indicium.ai", prioridade = 150, banco = "monitoramento", somente_leitura = "1" }
    dev  = { host = "monitoramento-sas-dev.hub.indicium.ai", prioridade = 151, banco = "monitoramento_dev", somente_leitura = "0" }
  }

  # ecs.tf chama de "monitoramento-sas-dev" toda chave que não seja prod: uma terceira chave
  # colidiria com o serviço do dev.
  validation {
    condition     = toset(keys(var.ambientes)) == toset(["prod", "dev"])
    error_message = "ambientes tem exatamente as chaves prod e dev."
  }

  # O app só reconhece "1"/"true"/"yes" como só leitura: um "sim" deixaria prod gravável calado.
  validation {
    condition     = alltrue([for a in values(var.ambientes) : contains(["0", "1"], a.somente_leitura)])
    error_message = "somente_leitura é \"1\" (só leitura) ou \"0\"."
  }

  validation {
    condition     = length(distinct([for a in values(var.ambientes) : a.prioridade])) == length(var.ambientes)
    error_message = "Cada ambiente precisa de uma prioridade própria no listener."
  }
}

variable "email_alarme" {
  description = "Quem recebe o alarme de falha da sincronização (confirmação por e-mail na 1ª vez)."
  type        = string
  default     = "lucas.muller@indicium.ai"

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.email_alarme))
    error_message = "email_alarme precisa ser um e-mail."
  }
}

variable "databricks_host" {
  type    = string
  default = "https://dbc-5626df64-1b10.cloud.databricks.com"
}

variable "databricks_warehouse_id" {
  type    = string
  default = "5922c26f81f1bbdd"
}
```

- [ ] **Step 2: data.tf** — acrescente ao do passo 0:

```hcl
data "aws_vpc" "indicium_main_vpc" {
  filter {
    name   = "tag:Name"
    values = ["indicium-main-vpc"]
  }
}

data "aws_subnet" "indicium_main_public_1" {
  filter {
    name   = "tag:Name"
    values = ["indicium_main_public_1"]
  }
}

data "aws_subnet" "indicium_main_public_2" {
  filter {
    name   = "tag:Name"
    values = ["indicium_main_public_2"]
  }
}

data "aws_ecs_cluster" "indicium" {
  cluster_name = "tf-indicium-ecs"
}

# Do root rds/monitoramento_sas (F1) — lidos, nunca recriados aqui.
data "aws_db_instance" "banco" {
  db_instance_identifier = "monitoramento-sas-db"
}

data "aws_secretsmanager_secret" "banco" {
  name = "indicium-infra/rds/monitoramento-sas/credentials"
}

data "aws_security_group" "cliente_banco" {
  name = "monitoramento-sas-db-client-sg"
}

# Criado À MÃO (Task F5).
data "aws_secretsmanager_secret" "databricks_sync" {
  name = "indicium-infra/ecs/monitoramento-sas/databricks-sync"
}
```

E troque o `locals` do passo 0 por este (já no alinhamento do `terraform fmt`):

```hcl
locals {
  host_prod    = "monitoramento-sas.hub.indicium.ai"
  google_oauth = jsondecode(data.aws_secretsmanager_secret_version.google_oauth.secret_string)
  subnets      = [data.aws_subnet.indicium_main_public_1.id, data.aws_subnet.indicium_main_public_2.id]
}
```

Os três roots de produção (passo 0 sozinho, banco e app completo, montados com os blocos deste plano) passaram em `terraform validate` e `terraform fmt -check` em 2026-10-14, com o provider AWS 6.68.

- [ ] **Step 3: ecr.tf**

```hcl
resource "aws_ecr_repository" "app" {
  name                 = "monitoramento-sas"
  image_tag_mutability = "MUTABLE" # tags :prod e :dev são móveis; o commit vai em tag própria
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = { ManagedBy = "Terraform" }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Mantem as 30 imagens mais recentes"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }
      action       = { type = "expire" }
    }]
  })
}
```

- [ ] **Step 4: policies e iam.tf**

`policies/ecs_task_assume_role.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Principal": { "Service": "ecs-tasks.amazonaws.com" }, "Action": "sts:AssumeRole" }
  ]
}
```

`policies/execution_secrets_policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"], "Resource": ${secret_arns} }
  ]
}
```

`policies/scheduler_assume_role.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Principal": { "Service": "scheduler.amazonaws.com" }, "Action": "sts:AssumeRole" }
  ]
}
```

`iam.tf`:

```hcl
resource "aws_iam_role" "execucao" {
  name               = "monitoramento-sas-execution"
  assume_role_policy = file("${path.module}/policies/ecs_task_assume_role.json")
  tags               = { ManagedBy = "Terraform" }
}

resource "aws_iam_role_policy_attachment" "execucao_base" {
  role       = aws_iam_role.execucao.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execucao_segredos" {
  name = "ler-segredos-monitoramento-sas"
  role = aws_iam_role.execucao.id
  policy = templatefile("${path.module}/policies/execution_secrets_policy.json", {
    secret_arns = jsonencode([data.aws_secretsmanager_secret.banco.arn, data.aws_secretsmanager_secret.databricks_sync.arn])
  })
}

# O app e a sincronização não chamam API da AWS: o papel da tarefa existe vazio.
resource "aws_iam_role" "tarefa" {
  name               = "monitoramento-sas-task"
  assume_role_policy = file("${path.module}/policies/ecs_task_assume_role.json")
  tags               = { ManagedBy = "Terraform" }
}

resource "aws_iam_role" "agendador" {
  name               = "monitoramento-sas-scheduler"
  assume_role_policy = file("${path.module}/policies/scheduler_assume_role.json")
  tags               = { ManagedBy = "Terraform" }
}

resource "aws_iam_role_policy" "agendador_run_task" {
  name = "rodar-sincronizacao"
  role = aws_iam_role.agendador.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecs:RunTask"], Resource = ["${aws_ecs_task_definition.sync.arn_without_revision}:*"] },
      { Effect = "Allow", Action = ["iam:PassRole"], Resource = [aws_iam_role.execucao.arn, aws_iam_role.tarefa.arn] },
    ]
  })
}
```

- [ ] **Step 5: ecs.tf**

```hcl
resource "aws_security_group" "app" {
  name        = "monitoramento-sas-app-sg"
  description = "Tarefas do app: entrada so do ALB compartilhado"
  vpc_id      = data.aws_vpc.indicium_main_vpc.id
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = data.aws_lb.indicium_lb.security_groups
    description     = "App via ALB compartilhado"
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Imagem (ECR), RDS, chave publica do ALB"
  }
  tags = { Name = "monitoramento-sas-app-sg", ManagedBy = "Terraform" }
}

resource "aws_security_group" "sync" {
  name        = "monitoramento-sas-sync-sg"
  description = "Sincronizacao Databricks para Postgres: sem entrada"
  vpc_id      = data.aws_vpc.indicium_main_vpc.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Databricks (HTTPS), RDS, ECR"
  }
  tags = { Name = "monitoramento-sas-sync-sg", ManagedBy = "Terraform" }
}

resource "aws_cloudwatch_log_group" "app" {
  for_each          = var.ambientes
  name              = "/ecs/monitoramento-sas-${each.key}"
  retention_in_days = 30
  tags              = { ManagedBy = "Terraform" }
}

resource "aws_ecs_task_definition" "app" {
  for_each                 = var.ambientes
  family                   = "monitoramento-sas-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 2048 # medir no dev (Parte H) e ajustar
  execution_role_arn       = aws_iam_role.execucao.arn
  task_role_arn            = aws_iam_role.tarefa.arn
  container_definitions = jsonencode([{
    name         = "app"
    image        = "${aws_ecr_repository.app.repository_url}:${each.key}"
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "DB_BACKEND", value = "postgres" },
      { name = "PUBLISH_SCHEMA", value = "compat" },
      { name = "IDENTIDADE", value = "alb" },
      { name = "ALB_SIGNER_ARN", value = data.aws_lb.indicium_lb.arn },
      { name = "SOMENTE_LEITURA", value = each.value.somente_leitura },
      { name = "FAMILIAS_SAFRA", value = "1" },
      { name = "APP_PORT", value = "8000" },
      { name = "PGHOST", value = data.aws_db_instance.banco.address },
      { name = "PGPORT", value = tostring(data.aws_db_instance.banco.port) },
      { name = "PGDATABASE", value = each.value.banco },
      { name = "PGUSER", value = data.aws_db_instance.banco.master_username },
      # Entra como mestre (o único que a plataforma gira) e baixa a sessão (db_pg._configura).
      { name = "PG_PAPEL", value = "app_leitura" },
      { name = "PGSSLMODE", value = "require" },
    ]
    secrets = [
      { name = "PGPASSWORD", valueFrom = "${data.aws_secretsmanager_secret.banco.arn}:db_password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.app[each.key].name
        "awslogs-region"        = "us-east-1"
        "awslogs-stream-prefix" = "app"
      }
    }
  }])
  tags = { ManagedBy = "Terraform", "backstage.spec.system" = "monitoramento-sas" }
}

resource "aws_ecs_service" "app" {
  for_each                          = var.ambientes
  name                              = each.key == "prod" ? "monitoramento-sas" : "monitoramento-sas-dev"
  cluster                           = data.aws_ecs_cluster.indicium.id
  task_definition                   = aws_ecs_task_definition.app[each.key].arn
  desired_count                     = 1
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 120

  network_configuration {
    subnets          = local.subnets
    security_groups  = [aws_security_group.app.id, data.aws_security_group.cliente_banco.id]
    assign_public_ip = true # sub-redes públicas, sem NAT (molde do passbolt)
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app[each.key].arn
    container_name   = "app"
    container_port   = 8000
  }

  tags = { ManagedBy = "Terraform", "backstage.spec.system" = "monitoramento-sas" }
}
```

- [ ] **Step 6: alb.tf** — mantenha o certificado do passo 0 e **troque** a regra `teste_login` e o registro `prod` por estes. Os `moved` evitam destruir e recriar o que já está no ar:

```hcl
moved {
  from = aws_lb_listener_rule.teste_login
  to   = aws_lb_listener_rule.app["prod"]
}

moved {
  from = aws_route53_record.prod
  to   = aws_route53_record.app["prod"]
}

resource "aws_lb_target_group" "app" {
  for_each    = var.ambientes
  name        = "monitoramento-sas-${each.key}"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = data.aws_vpc.indicium_main_vpc.id
  health_check {
    path                = "/api/health"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  tags = { ManagedBy = "Terraform" }
}

# Público e protegido por LOGIN, não por IP como os outros apps deste ALB: o BV entra de
# fora da VPN. Sem login, nenhuma requisição chega ao app; o app ainda confere a assinatura
# do cabeçalho e o cadastro (backend/auth_alb.py, main._nega_acesso).
resource "aws_lb_listener_rule" "app" {
  for_each     = var.ambientes
  listener_arn = data.aws_lb_listener.tf_lb_https.arn
  priority     = each.value.prioridade

  action {
    type  = "authenticate-oidc"
    order = 1
    authenticate_oidc {
      authorization_endpoint     = "https://accounts.google.com/o/oauth2/v2/auth"
      token_endpoint             = "https://oauth2.googleapis.com/token"
      user_info_endpoint         = "https://openidconnect.googleapis.com/v1/userinfo"
      issuer                     = "https://accounts.google.com"
      client_id                  = local.google_oauth.client_id
      client_secret              = local.google_oauth.client_secret
      scope                      = "openid email"
      session_timeout            = 28800
      on_unauthenticated_request = "authenticate"
    }
  }

  action {
    type             = "forward"
    order            = 2
    target_group_arn = aws_lb_target_group.app[each.key].arn
  }

  condition {
    host_header {
      values = [each.value.host]
    }
  }

  tags = { ManagedBy = "Terraform" }
}

resource "aws_route53_record" "app" {
  for_each = var.ambientes
  zone_id  = data.aws_route53_zone.hub.zone_id
  name     = each.value.host
  type     = "A"
  alias {
    name                   = data.aws_lb.indicium_lb.dns_name
    zone_id                = data.aws_lb.indicium_lb.zone_id
    evaluate_target_health = false
  }
}
```

- [ ] **Step 7: sync.tf**

```hcl
resource "aws_cloudwatch_log_group" "sync" {
  name              = "/ecs/monitoramento-sas-sync"
  retention_in_days = 30
  tags              = { ManagedBy = "Terraform" }
}

resource "aws_ecs_task_definition" "sync" {
  family                   = "monitoramento-sas-sync"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execucao.arn
  task_role_arn            = aws_iam_role.tarefa.arn
  container_definitions = jsonencode([{
    name      = "sync"
    image     = "${aws_ecr_repository.app.repository_url}:prod"
    essential = true
    command   = ["python", "-m", "sync.sincroniza"]
    environment = [
      { name = "ORIGEM_SCHEMA", value = "bv_dev_db.monitoramento_sas" },
      { name = "DATABRICKS_HOST", value = var.databricks_host },
      { name = "DATABRICKS_WAREHOUSE_ID", value = var.databricks_warehouse_id },
      { name = "PGHOST", value = data.aws_db_instance.banco.address },
      { name = "PGPORT", value = tostring(data.aws_db_instance.banco.port) },
      { name = "PGDATABASE", value = "monitoramento" },
      { name = "PGUSER", value = data.aws_db_instance.banco.master_username },
      { name = "PG_PAPEL", value = "sincronizador" },
      { name = "PGSSLMODE", value = "require" },
    ]
    secrets = [
      # A senha é lida a cada execução: a rotação (F3) chega na rodada seguinte sem reinício.
      { name = "PGPASSWORD", valueFrom = "${data.aws_secretsmanager_secret.banco.arn}:db_password::" },
      { name = "DATABRICKS_CLIENT_ID", valueFrom = "${data.aws_secretsmanager_secret.databricks_sync.arn}:client_id::" },
      { name = "DATABRICKS_CLIENT_SECRET", valueFrom = "${data.aws_secretsmanager_secret.databricks_sync.arn}:client_secret::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.sync.name
        "awslogs-region"        = "us-east-1"
        "awslogs-stream-prefix" = "sync"
      }
    }
  }])
  tags = { ManagedBy = "Terraform", "backstage.spec.system" = "monitoramento-sas" }
}

# A cada 15 min, das 8h às 19h45 (Brasília), todos os dias. Só prod: o dev não sincroniza
# (edições do laboratório seriam apagadas).
resource "aws_scheduler_schedule" "sync" {
  name                         = "monitoramento-sas-sync"
  schedule_expression          = "cron(0/15 8-19 * * ? *)"
  schedule_expression_timezone = "America/Sao_Paulo"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = data.aws_ecs_cluster.indicium.arn
    role_arn = aws_iam_role.agendador.arn
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.sync.arn_without_revision
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = local.subnets
        security_groups  = [aws_security_group.sync.id, data.aws_security_group.cliente_banco.id]
        assign_public_ip = true
      }
    }
    retry_policy {
      maximum_retry_attempts = 0 # a próxima rodada é em 15 min; o alarme avisa da falha
    }
  }
}
```

- [ ] **Step 8: alarm.tf**

```hcl
resource "aws_sns_topic" "alarme" {
  name = "monitoramento-sas-alarme"
  tags = { ManagedBy = "Terraform" }
}

resource "aws_sns_topic_subscription" "alarme_email" {
  topic_arn = aws_sns_topic.alarme.arn
  protocol  = "email"
  endpoint  = var.email_alarme
}

resource "aws_cloudwatch_log_metric_filter" "sync_falha" {
  name           = "monitoramento-sas-sync-falha"
  log_group_name = aws_cloudwatch_log_group.sync.name
  pattern        = "\"[sync] FALHA\""
  metric_transformation {
    name      = "SyncFalha"
    namespace = "MonitoramentoSAS"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "sync_falha" {
  alarm_name          = "monitoramento-sas-sync-falhou"
  alarm_description   = "A sincronizacao Databricks -> Postgres falhou (ver /ecs/monitoramento-sas-sync)"
  namespace           = "MonitoramentoSAS"
  metric_name         = "SyncFalha"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarme.arn]
  tags                = { ManagedBy = "Terraform" }
}
```

- [ ] **Step 9: Validar e abrir a PR** (`aws/production-acc/ecs_applications/monitoramento_sas/phase1a`)

```bash
terraform -chdir=aws/production-acc/ecs_applications/monitoramento_sas init -backend=false
```

```bash
terraform -chdir=aws/production-acc/ecs_applications/monitoramento_sas validate
```

```bash
make -C ~/indicium/indicium_infra hooks
```

Esperado: válido e hooks verdes. `email_alarme` tem valor padrão, porque o CI do `indicium_infra` não passa variável por root. Na 1ª vez o SNS manda um e-mail de confirmação, que precisa ser aceito. O plano deve mostrar os dois `moved` (sem destruir a regra do passo 0), 1 ECR, 2 SGs, 3 task definitions, 2 serviços, 2 target groups, a regra de dev, o registro de dev, 1 agendamento e o alarme. Os serviços sobem com 0 tarefas saudáveis até existir imagem no ECR (Parte G); é esperado.

*Opcional:* ensaios do Terraform podem rodar na training no mesmo dia (apply local liberado, tudo some à noite), sem DNS e sem dado.

### Task F3: Senha do banco na rotação (PR 3, depois do apply da F2)

**Files:**
- Modify: `indicium_infra/aws/production-acc/lambda/secret-rotation/variables.tf` (`var.targets`)
- Modify: `indicium_infra/aws/production-acc/lambda/secret-rotation/README.md` (tabela)

- [ ] **Step 1: Entrada nova** em `default` de `variable "targets"`:

```hcl
    "indicium-infra/rds/monitoramento-sas/credentials" = {
      db_instance_identifier = "monitoramento-sas-db"
      ecs_cluster            = "tf-indicium-ecs"
      ecs_service            = ["monitoramento-sas", "monitoramento-sas-dev"]
    }
```

A sincronização não é serviço: ela lê a senha no início de cada execução, então não precisa ser reiniciada.

- [ ] **Step 2: Linha na tabela do README**: `indicium-infra/rds/monitoramento-sas/credentials` | `db_password` | `rds:ModifyDBInstance` on `monitoramento-sas-db` | `monitoramento-sas`, `monitoramento-sas-dev`.

- [ ] **Step 3: PR** (`aws/production-acc/lambda/secret-rotation/monitoramento-sas`). Depois do apply, faça a **primeira rotação à mão**, olhando o app, como manda o README do rotacionador:

```bash
aws --profile indicium secretsmanager rotate-secret --secret-id indicium-infra/rds/monitoramento-sas/credentials
```

```bash
aws --profile indicium logs tail /aws/lambda/indicium-secret-rotation --since 10m
```

Esperado: as 4 etapas sem erro, os dois serviços reiniciados e saudáveis, e a próxima sincronização com `[sync] OK`.

### Task F4: Conta de deploy do CI

**Files:**
- Modify: `indicium_infra/aws/production-acc/IAM/service_accounts.auto.tfvars`
- Create: `indicium_infra/aws/production-acc/IAM/modules/service-accounts/policies/svc_inline/monitoramento_sas_deploy_policy.json`

- [ ] **Step 1: Política** (só empurrar imagem e reiniciar os dois serviços):

```json
{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "EcrLogin",
        "Effect": "Allow",
        "Action": "ecr:GetAuthorizationToken",
        "Resource": "*"
      },
      {
        "Sid": "PushAppImage",
        "Effect": "Allow",
        "Action": [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          "ecr:BatchGetImage"
        ],
        "Resource": "arn:aws:ecr:us-east-1:835825599161:repository/monitoramento-sas"
      },
      {
        "Sid": "RestartAppServices",
        "Effect": "Allow",
        "Action": [
          "ecs:UpdateService",
          "ecs:DescribeServices"
        ],
        "Resource": [
          "arn:aws:ecs:us-east-1:835825599161:service/tf-indicium-ecs/monitoramento-sas",
          "arn:aws:ecs:us-east-1:835825599161:service/tf-indicium-ecs/monitoramento-sas-dev"
        ]
      }
    ]
  }
```

- [ ] **Step 2: Conta** (dentro de `service_accounts = { ... }`):

```hcl
  monitoramento_sas_deploy = {
    custom_policies    = ["monitoramento_sas_deploy_policy"]
    owner              = ["lucas.muller@indicium.ai"]
    automatic_rotation = false
    deactivated        = false
  }
```

- [ ] **Step 3: PR** (`aws/production-acc/IAM/monitoramento-sas-deploy`). Depois do merge, a chave chega pelo Keeper ao `owner`. Ela vai para as variáveis **seguras** do repo do app, nas deployments `aws-development` e `aws-production` (Parte G): `AWS_ACCESS_KEY_ID` e `AWS_SECRET_ACCESS_KEY`.

### Task F5: Conta de serviço da sincronização no Databricks

> **Substituída em 2026-10-15 (decisão do usuário):** a sincronização lê com o **token pessoal** de quem cuida do app, porque é temporária: tudo sai do Databricks no fim. Não abra a PR da F5 (a branch `feat/monitoramento-sas-sync-sp` fica sem uso) nem peça os grants. Só o Step 4 continua, com outro conteúdo. Crie o token no Databricks, em User Settings → Developer → Access tokens, com prazo de validade. Ele vai para `databricks-sync.json` = `{"token": "<token>"}` pelo mesmo `create-secret` (F2 lê a chave `token` para `DATABRICKS_TOKEN`). Anote na spec a data em que o token vence. O token nunca passa pelo chat nem pelo histórico do shell.

**Files:**
- Modify: `indicium_databricks_aws_infra/configs/principal_configs.yml`

- [ ] **Step 1: Atualizar a `master`** e conferir que o grupo existe (o clone local estava defasado):

```bash
git -C ~/indicium/indicium_databricks_aws_infra pull
```

```bash
grep -n "bv_monitoramento_sas_apps" ~/indicium/indicium_databricks_aws_infra/configs/principal_configs.yml
```

Esperado: a definição do grupo. Se não aparecer, pare e confirme com a plataforma onde o grupo é declarado.

- [ ] **Step 2: Acrescentar a SP** na lista de service principals, ao lado de `bv-prod-sp`:

```yaml
    - name: bv-monitoramento-sync-sp
      meta:
        purpose: Read-only sync of the monitoramento_sas Delta tables to the app's AWS Postgres (monitoramento-sas moving to ECS, ADR 0005 in sas_assessment_tool)
        owner: lucas.muller@indicium.tech
        category: automation
        lifecycle: temporary
        end_date: "2026-12-31"
      groups:
        - bv_monitoramento_sas_apps
      permissions:
        - role: [Manage, Use]
          principals:
            - type: user
              name: lucas.muller@indicium.tech
```

```bash
uvx pre-commit run --files configs/principal_configs.yml
```

Esperado: passa (valida o schema do YAML). O grupo dá `USE_CATALOG` em `bv_dev_db` e `CAN_USE` no warehouse, de forma durável. A SP é **temporária**, com o mesmo `end_date` do grupo: a sincronização acaba quando o app deixa de ler o Databricks. A finalidade do grupo ganha uma frase citando a SP. O dono da conta de deploy (F4) usa `@indicium.ai`, como os demais donos do `service_accounts`, e aqui segue `@indicium.tech`, que é a identidade no Databricks.

- [ ] **Step 3: PR** (`feat/monitoramento-sas-sync-sp`). Depois do apply, um admin do workspace concede, **fora do repo** (grant de schema é por SP, como os dos apps), só leitura:

```sql
GRANT USE SCHEMA ON SCHEMA bv_dev_db.monitoramento_sas TO `<application-id da bv-monitoramento-sync-sp>`;
GRANT SELECT ON SCHEMA bv_dev_db.monitoramento_sas TO `<application-id da bv-monitoramento-sync-sp>`;
```

- [ ] **Step 4: Segredo OAuth da SP** (admin da conta Databricks) para o Secrets Manager de produção, por arquivo temporário:

```bash
aws secretsmanager create-secret --profile indicium --name indicium-infra/ecs/monitoramento-sas/databricks-sync --secret-string file://databricks-sync.json
```

`databricks-sync.json` = `{"client_id": "<application-id>", "client_secret": "<segredo>"}`; apague com `shred -u databricks-sync.json`. As chaves não são `db_password` nem `access_token`, então o rotacionador não toca nele. O segredo OAuth da SP vence conforme a política do Databricks: anote a data de vencimento na spec.

---

## Parte G — Imagem e CI

### Task G1: Dockerfile

**Files:**
- Create: `egps_analysis/app/Dockerfile`
- Create: `egps_analysis/app/.dockerignore`

- [ ] **Step 1: Dockerfile**

```dockerfile
# Imagem única do app na AWS (ADR 0005): front buildado + backend FastAPI + sincronização.
# App: CMD padrão. Sincronização: command ["python", "-m", "sync.sincroniza"] na task definition.
FROM node:20-slim AS front
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite.config.ts: outDir "../static" -> /app/static
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY db/ db/
COPY sync/ sync/
COPY paridade/ paridade/
COPY --from=front /app/static static/
ENV PYTHONUNBUFFERED=1 APP_PORT=8000
EXPOSE 8000
USER nobody
CMD ["python", "backend/main.py"]
```

- [ ] **Step 2: .dockerignore**

```text
frontend/node_modules
static
treino
.venv
**/__pycache__
**/.pytest_cache
docs
genie
*.md
.app.yaml.prod.bak
```

- [ ] **Step 3: Construir e subir local contra o Postgres da preparação**

```bash
docker build -t monitoramento-sas:local egps_analysis/app
```

```bash
docker run --rm --network host -e APP_PORT=8002 -e DB_BACKEND=postgres -e PG_DSN=postgresql://postgres@127.0.0.1:55432/monitoramento -e PUBLISH_SCHEMA=compat -e IDENTIDADE=dev -e DEV_USUARIO=lucas.muller@indicium.ai -e SOMENTE_LEITURA=1 -e FAMILIAS_SAFRA=1 monitoramento-sas:local
```

```bash
python -m treino.fumaca http://localhost:8002 --usuario lucas.muller@indicium.ai
```

(`curl` é bloqueado pela política da organização para o agente; ver `egps_analysis/app/CLAUDE.md`.) `--network host` porque o Postgres da preparação só escuta em `127.0.0.1`. Esperado: cinco linhas `[fumaca] OK` (passou em 2026-10-14). Abrir `http://localhost:8002` mostra o app com a faixa.

### Task G2: Pipeline

**Files:**
- Modify: `bitbucket-pipelines.yml` (raiz do repo do app)

- [ ] **Step 1: Postgres de serviço para os testes.** Em `definitions:`, acrescente:

```yaml
  services:
    postgres:
      image: postgres:17
      variables:
        POSTGRES_HOST_AUTH_METHOD: trust
```

No step `&testes`, acrescente `services: [postgres]` e, no `script`, antes do `pytest` do backend:

```yaml
          - export PG_TEST_DSN=postgresql://postgres@localhost:5432/postgres
          - export PG_TEST_OBRIGATORIO=1
```

E, depois do `pytest` do backend (ainda dentro de `egps_analysis/app/backend`):

```yaml
          - cd .. && python -m pytest -q db sync paridade treino && cd backend
```

- [ ] **Step 2: Steps de deploy na AWS** — **só depois do apply da F2 e do Step 3**: antes disso não há ECR, serviço nem variáveis, e todo merge na `develop`/`main` quebraria no deploy. (O Step 1 foi feito em 2026-10-14 e não depende da infra.) Em `definitions.steps`:

```yaml
    - step: &deploy-aws
        name: Build + deploy AWS
        image: atlassian/default-image:4
        services: [docker]
        script:
          - curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
          - unzip -q awscliv2.zip
          - ./aws/install
          - export ECR_REPO=835825599161.dkr.ecr.us-east-1.amazonaws.com/monitoramento-sas
          - aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 835825599161.dkr.ecr.us-east-1.amazonaws.com
          - docker build -t $ECR_REPO:$BITBUCKET_COMMIT -t $ECR_REPO:$AWS_TAG egps_analysis/app
          - docker push $ECR_REPO:$BITBUCKET_COMMIT
          - docker push $ECR_REPO:$AWS_TAG
          - aws ecs update-service --region us-east-1 --cluster tf-indicium-ecs --service $AWS_SERVICE --force-new-deployment
          - aws ecs wait services-stable --region us-east-1 --cluster tf-indicium-ecs --services $AWS_SERVICE
```

Nos `pipelines.branches`, acrescente na `develop` e na `main` (com a mesma `condition: *so-app` dos deploys de hoje):

```yaml
      - step:
          <<: *deploy-aws
          name: Build + deploy AWS dev
          deployment: aws-development
          condition: *so-app
```

```yaml
      - step:
          <<: *deploy-aws
          name: Build + deploy AWS prod
          deployment: aws-production
          condition: *so-app
```

- [ ] **Step 3: Deployments no Bitbucket** (Repository settings → Deployments). Crie `aws-development` (tipo Staging) e `aws-production` (tipo Production). Uma deployment só aparece **uma vez** por pipeline, por isso as de hoje (`development` e `production`) não servem. Variáveis **seguras** em cada uma: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (Task F2); não seguras: `AWS_TAG` (`dev`/`prod`), `AWS_SERVICE` (`monitoramento-sas-dev`/`monitoramento-sas`).

- [ ] **Step 4: Checkpoint de commit** (só se pedido): `ci: testes com Postgres e deploy do app na AWS`.

---

## Parte H — Subida (dev, depois prod), ainda fechada ao BV

### Task H1: Banco de dev e migrações (manual, pela VPN, admin do RDS)

Não há usuário de login avulso: o app e a sincronização entram como `mestre` (senha girada pela plataforma, F3) e baixam a sessão com `SET ROLE` (`PG_PAPEL`). A 0004 dá ao mestre a participação nos papéis. Isso foi provado com um mestre sem superusuário, em dois bancos do mesmo servidor.

- [ ] Conectado à VPN da Indicium, crie um `~/.pgpass` temporário (`chmod 600`) com a linha `<endpoint do RDS>:5432:*:mestre:<db_password do segredo indicium-infra/rds/monitoramento-sas/credentials>`. A senha não vai para a linha de comando.

- [ ] Crie os dois bancos (collation C) e rode as migrações, a partir de `egps_analysis/app`. O RDS nasce sem banco do app (F1):

```bash
env PG_DSN="host=<endpoint do RDS> dbname=monitoramento user=mestre sslmode=require" python -m db.migra --cria-banco
```

```bash
env PG_DSN="host=<endpoint do RDS> dbname=monitoramento_dev user=mestre sslmode=require" python -m db.migra --cria-banco
```

Esperado, em cada um: `[migra] banco ... criado (collation C)` e `[migra] 4 nova(s); 4 no total`.

Sem VPN, o mesmo resultado sai de uma tarefa avulsa no cluster, com a task definition do app. Ela alcança o RDS pelo `monitoramento-sas-db-client-sg` e lê a senha pelo segredo, como o serviço. Foi o caminho testado na bancada:

```bash
aws ecs run-task --profile indicium --cluster tf-indicium-ecs --launch-type FARGATE --task-definition monitoramento-sas-prod --network-configuration "awsvpcConfiguration={subnets=[<public_1>,<public_2>],securityGroups=[<monitoramento-sas-app-sg>,<monitoramento-sas-db-client-sg>],assignPublicIp=ENABLED}" --overrides '{"containerOverrides":[{"name":"app","command":["python","-m","db.migra","--cria-banco"],"environment":[{"name":"PG_DSN","value":"host=<endpoint do RDS> dbname=monitoramento user=mestre sslmode=require"}]}]}'
```

(Para o dev, troque a task definition por `monitoramento-sas-dev` e o `dbname` por `monitoramento_dev`. O resultado sai no log `/ecs/monitoramento-sas-prod` ou `-dev`.)

- [ ] Confira o papel de leitura no banco de prod:

```bash
psql "host=<endpoint do RDS> dbname=monitoramento user=mestre sslmode=require" -c "SET ROLE app_leitura" -c "SELECT current_user"
```

Esperado: `app_leitura`. Depois, apague o `~/.pgpass` (`shred -u ~/.pgpass`).

### Task H2: Cadastro inicial de papéis

- [ ] No banco `monitoramento` (e igual no `monitoramento_dev`), cadastre a gestão e os admins **com o e-mail que o login do Google devolve (`@indicium.ai`)**. A lista sai do `bv_users` e do `bv_admins` em `principal_configs.yml`. O BV entra só na 1b:

```sql
SELECT set_config('app.usuario', 'lucas.muller@indicium.ai', false);
INSERT INTO cadastro.usuario (email, nome, papel) VALUES
  ('lucas.muller@indicium.ai', 'Lucas Muller', 'admin')
ON CONFLICT (email) DO UPDATE SET papel = EXCLUDED.papel, ativo = true;
```

Repita a linha `VALUES` para cada pessoa da gestão (`'gestao'`) e para os 6 admins (`'admin'`).

### Task H3: Primeira sincronização e smoke test

- [ ] Com o consentimento do usuário (é a primeira escrita no banco de prod da AWS e a primeira leitura com o token guardado no segredo), dispare a sincronização fora do agendamento:

```bash
aws ecs run-task --profile indicium --cluster tf-indicium-ecs --launch-type FARGATE --task-definition monitoramento-sas-sync --network-configuration "awsvpcConfiguration={subnets=[<public_1>,<public_2>],securityGroups=[<sg monitoramento-sas-sync-sg>,<sg monitoramento-sas-db-client-sg>],assignPublicIp=ENABLED}"
```

```bash
aws logs tail /ecs/monitoramento-sas-sync --profile indicium --since 15m
```

Esperado: `[sync] OK {...}`. Guarde o resumo (âncoras acrescentadas, pares duplicados, trabalho órfão) na spec, como a **auditoria de integridade de prod**.

- [ ] Smoke em `https://monitoramento-sas.hub.indicium.ai`, com sua conta `@indicium.ai`:
  1. o login do Google aparece e volta para o app;
  2. `/api/me` mostra `{"user": "lucas.muller@indicium.ai", "papel": "admin"}`;
  3. a faixa "Dados de …" aparece com o horário da sincronização;
  4. uma edição qualquer devolve 403 "Somente leitura";
  5. numa janela anônima com uma conta **não cadastrada**, aparece a tela de sem acesso.
- [ ] Repita no dev (`monitoramento-sas-dev.hub.indicium.ai`), carregando o banco de dev **uma vez**, com cópia de prod: o mesmo `run-task`, acrescentando `--overrides '{"containerOverrides":[{"name":"sync","environment":[{"name":"PGDATABASE","value":"monitoramento_dev"}]}]}'`. Sem agendamento.
- [ ] Meça memória e CPU das tarefas no CloudWatch Container Insights, ou em `aws ecs describe-tasks`, durante 1 dia de uso da gestão. Ajuste `cpu` e `memory` na F1, se preciso, por PR.

### Task H4: Fechamento do 1a

- [ ] Rode a suíte inteira local (backend, db, sync e paridade) com `PG_TEST_OBRIGATORIO=1`. Esperado: tudo verde.
- [ ] Registre na spec o resultado do passo 0, a auditoria de integridade de prod e as diferenças aceitas encontradas até aqui.
- [ ] Escreva o **plano 1b** a partir da `main` do momento. Insumos:
  - o relatório do agente de schema, com o de-para das ~40 tabelas restantes;
  - o catálogo de reescritas portáveis já conhecidas:
    - `current_timestamp()` → `current_timestamp`;
    - `current_date()` → `current_date`;
    - `transform(split(areas, '[|]'), x -> trim(x))` → `split(regexp_replace(trim(areas), ' *[|] *', '|'), '[|]')`;
    - `arrays_overlap(X, array(a, b))` → `(array_contains(X, a) OR array_contains(X, b))`;
    - `split(x, …)[0]` → `element_at(split(x, …), 1)`;
    - `ORDER BY` com `NULLS FIRST` explícito;
    - divisão com `CAST(… AS DOUBLE)`;
  - a comparação rodando sobre **todas** as rotas GET.

## Saída do 1a

- Passo 0 respondido: o login de uma conta `@bv.com.br` num app novo da Indicium funciona, ou temos o bloqueio documentado.
- Stack de prod e dev no ar no ECS Fargate, com login, papéis, só leitura, faixa de sincronização e alarme.
- Sincronização rodando a cada 15 min para as 5 primeiras tabelas, com a auditoria de integridade de prod registrada.
- Backend servindo os dois bancos com o mesmo código, com a suíte verde no CI contra um Postgres de verdade.
- O BV ainda **não** entra: o app só serve as rotas que a fatia cobre. O cadastro do BV e o JIT são da 1b.
