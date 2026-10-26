# Migração do app para a AWS — ECS Fargate + Postgres (RDS)

Data: 2026-10-14. Status: design aprovado; planos 1a, 1b e 2a escritos (2a em execução em 15/10). Decisão e
alternativas rejeitadas: [ADR 0005](../../../../../docs/adr/0005-app-sai-do-databricks.md).

## Problema

1. **Compliance.** A plataforma da Indicium vai restringir o Databricks a identidades da
   Indicium (JIT + SSO da Indicium). Com isso nenhuma conta do BV entra no app, que hoje é
   um Databricks App. O JIT foi revertido provisoriamente para o BV não perder o acesso; a
   migração existe para religá-lo o quanto antes.
2. **Custo.** ~US$ 935 em 30 dias a preço de tabela (tabela abaixo), quase tudo uso do
   próprio app.
3. **Desempenho.** Piso medido de ~1 s por statement no SQL Warehouse; o app faz ~13 mil
   consultas por dia.

## Estado medido (2026-10-14)

**Custo, últimos 30 dias** (`system.billing.usage` × `list_prices`, preço de tabela):

| Recurso | US$ |
|---|---:|
| Warehouse `monitoramento-sas` (`5922c26f81f1bbdd`) | 601 |
| App `monitoramento-sas` | 272 |
| App `monitoramento-sas-dev` | 62 |

**Uso do warehouse, últimos 30 dias** (`system.query.history`): app com usuários da
Indicium 380 mil consultas / 72 h; app com usuários do BV 17 mil / 3 h; CLI (publish,
scripts, sessões) 41 mil / 6 h; Genie 1 mil / 0,5 h. Tudo isso sai com a migração.

**Acoplamento ao Databricks** (`egps_analysis/app/backend`):
- ~300 statements montados com f-string, executados por dois pontos únicos
  (`run_sql` `main.py:606`, `_run_sp` `main.py:661`).
- 75 `current_user()` gravando autoria dentro do SQL; grupos checados com
  `is_account_group_member` (`main.py:376-391`); parte da autorização de escrita vem de
  grant do Unity Catalog, não do código.
- 20+ `MERGE` com `t.col` no `SET`, `REPLACE WHERE`, `count_if`, lambdas de array,
  `split()[0]`, `date_format`, 78 `current_timestamp()`, ~230 `STRING`.
- **O escape de literais (`\'`, `sql_lit` `main.py:544` e mais 4 cópias) é inseguro no
  Postgres**: `x\' OR 1=1 --` sai da string. Hoje nenhum valor de requisição chega ao SQL
  sem passar por ele.

**Problemas de dados encontrados em prod** (consulta só leitura):
- 16 leituras dispensadas apontam para pares (EGP, input) que não existem mais; 16
  recebimentos de output e 1 escolha de produtor apontam para outputs que sumiram.
- 13 comentários da Gestão presos a aliases já colapsados — a recusa do colapso só olha 4
  colunas do monitor (`identidade_reaplica.py:53`).
- 72 eventos `desativar` do Escopo exibidos como "adicionado" no Histórico
  (`main.py:8047-8049`); 48 mudanças de etapa gravadas como `etapa_migracao`
  (`main.py:5653/5696`), invisíveis para o Tempo por Etapa, que lê só `campo='etapa'`
  (`main.py:6670`).
- O publish grava valores padrão nas colunas humanas (`publish_to_databricks.py:1474`):
  9.359 `'A Receber'` não se distinguem de uma decisão.
- Prod tem objetos que este worktree não cria (`sas_gestao_revisao`, `carga_fria` e
  `cf_*` em `sas_outputs_pipeline`): vêm de branches que estão em outros worktrees. O port
  parte da `main` mais recente.

## Arquitetura alvo

Tudo na conta de produção da Indicium (`835825599161`), Terraform no `indicium_infra`.

```
navegador ──HTTPS──▶ ALB compartilhado tf-load-balancer
                      regra host + /login/google: authenticate-oidc (Google) ▶ forward
                      regra host monitoramento-sas.hub.indicium.ai
                      ├─ authenticate-oidc (Google), allow  ← sem login passa SEM identidade
                      └─ forward ▶ target group (ip)          e o app manda para /login
                                    ▶ serviço ECS Fargate (FastAPI + bundle React)
                                        SG próprio
                                          │ 5432
                                          ▼
                                    RDS Postgres 17 (db.t3.micro, criptografado)
                                        SG aceita: membros do client-sg (app e sync) + VPN
EventBridge Scheduler (8h–20h BRT, a cada 15 min) ▶ tarefa Fargate de sincronização (fase 1)
Secrets Manager: indicium-infra/rds/monitoramento-sas/credentials (mestre, girado a cada 80
  dias pelo indicium-secret-rotation), .../ecs/monitoramento-sas/google-oauth, .../databricks-sync
ECR: imagem do app · CloudWatch: logs + alarme (SNS por e-mail)
```

- **Banco em root próprio** (`aws/production-acc/rds/monitoramento_sas/`, molde de
  `rds/knowledge_hub_mcp`): instância, SG do banco e um **SG de clientes** — só as tarefas
  do app e da sincronização entram nele. Os roots dependentes abrem PR só depois do apply
  do anterior (o CI aplica em ordem alfabética).
- **Usuário do banco = mestre**, o único que o `indicium-secret-rotation` gira, e ele reinicia
  os serviços. Cada sessão baixa os privilégios com `SET ROLE` (`PG_PAPEL`: `app_leitura` no
  app da Fase 1 e `app_escrita` no dev a partir do 2a (depois da Parte E) e na prod a partir
  da virada (2c), `sincronizador` na carga). Isso barra escrita por engano, não quem já
  injeta SQL (`RESET ROLE` desfaz) — essa barreira é o escape/parâmetros e o middleware.
  Provado com um mestre sem superusuário, em dois bancos do mesmo servidor.

- **Fargate, não o cluster compartilhado**: cada tarefa tem security group próprio, então o
  banco aceita só este app — no `tf-indicium-ecs` o banco teria de aceitar o SG do
  cluster inteiro. Sem máquina para gerenciar. Precedente de Fargate no repo:
  `ecs_applications/passbolt/ecs.tf`.
- **Um load balancer só** (o compartilhado). O ALB é público; os outros apps nele se
  restringem por IP de origem, este se restringe por login. Login pelo Google (OIDC); o
  Cognito fica como plano B (ver Riscos) — o "não adicione Cognito" do README do Knowledge
  Hub vale para aquele root, não é regra geral.
- Estimativa (não medida): Fargate 1 vCPU / 2 GB, prod 24/7 ≈ US$ 36/mês e dev ≈ US$ 4;
  RDS `db.t3.micro` ≈ US$ 16/mês; sincronização ≈ US$ 1; segredos e logs ≈ US$ 3. Total
  previsto ≈ US$ 60/mês. Na fase 1 os dois mundos coexistem.

## Identidade e papéis

- O ALB faz o login do Google e repassa ao app o cabeçalho `x-amzn-oidc-data` (JWT ES256
  assinado pelo ALB). O app **verifica a assinatura** com a chave pública regional e o ARN
  do `signer` antes de confiar no e-mail, e exige `email_verified` (o Google atesta que a
  pessoa é dona do e-mail). Sem cabeçalho válido → 401.
- **Página de login (decisão de 15/10/2026).** A pessoa clica em "Entrar com Google" em vez
  de cair direto no Google. A regra do app no ALB deixa passar quem não está logado (`allow`)
  sem a identidade. Sem login, o app só serve `/login` e `/api/health`. Qualquer outro
  endereço vai para `/login?volta=<endereço>`, inclusive os arquivos do front, e a API
  responde 401 com `entrar`. O botão leva a `/login/google`, a única regra que força o
  Google. Ela tem prioridade menor que a do app e usa o mesmo cookie de sessão. Depois do
  login, a pessoa volta ao endereço guardado; logado, ninguém vê mais `/login`
  (`main._desvio_de_login`). Testado de ponta a ponta na bancada da training com Cognito
  em 15/10.
- `cadastro.usuario` é ao mesmo tempo a lista de quem entra e o **papel** de cada um
  (`CONTEXT.md`): **leitor** (BV; vê as abas que não são da gestão, não escreve nada),
  **gestão** (edita; abas Gestão e Tempo por Etapa), **admin** (snapshot da priorização,
  correções retroativas). E-mail fora da tabela → página "sem acesso". Admin edita a tabela
  no app. Semente: `bv_users` (~24), `bv_admins` (6), `bv_external_users` (19) do
  `principal_configs.yml`.
- **Toda rota de escrita exige gestão ou admin**, inclusive as que hoje não checam grupo
  (contam com o grant do Unity Catalog);
  o registro "Com BV", que hoje sai inteiro em `/api/gestao/rows` para qualquer logado,
  passa a sair só como estado atual (último evento, sem autor) para quem não é da gestão.
  A tela esconde os controles de edição do leitor.
- Autoria: em toda transação de escrita o app faz
  `SELECT set_config('app.usuario', <email>, true)`; defaults e o trigger de carimbo leem
  daí (`cadastro.usuario_atual()`), substituindo `current_user()`.
- E-mails da Indicium normalizados para `@indicium.ai` (o que o login do Google devolve) em
  todas as tabelas, na migração da Fase 3.
- **Risco**: a TI do BV pode ter liberado só o client OAuth antigo da Indicium. Por isso o
  passo 0 do plano é o teste de login com uma conta `@bv.com.br`. Se falhar: pedir ao BV que
  confie no client novo, ou **Cognito com e-mail e senha** no ALB, combinado com a
  plataforma (o Google pode ser ligado ao mesmo Cognito depois, sem mudar o app).
- **O JIT do Databricks não afeta este login.** O SSO do Databricks usa outro cadastro OAuth
  da Indicium, do tipo "Internal" (só contas da organização — foi o erro que a conta do BV
  levou); o app usa um cadastro novo do tipo "External".

## Schema

> **Desde 15/10/2026 este modelo é a Fase 3** (ver Fases). Nas Fases 1 e 2 o app lê, e depois
> escreve, o espelho `legado` pelas views `compat`; o modelo abaixo continua sendo o destino
> do de-para com as correções, se ele ainda valer a pena depois de o Databricks sair.

DDL: [`2026-10-14-migracao-aws-schema.sql`](2026-10-14-migracao-aws-schema.sql). Aplicado
num Postgres 17 em 2026-10-14: 44 tabelas, 6 views, 44 PK, 44 FK, 55 CHECK, 5 UNIQUE.
Testes de comportamento em
[`2026-10-14-migracao-aws-schema-comportamento.sql`](2026-10-14-migracao-aws-schema-comportamento.sql),
todos com o resultado esperado: apagar âncora com estado humano falha; re-key da âncora se
propaga; comentário com dois alvos é recusado; prefixo de chave ≠ categoria é recusado;
autoria vem de `app.usuario`.

**Camadas** (um schema por dono e ciclo de vida):

| Schema | Conteúdo | Quem escreve |
|---|---|---|
| `cadastro` | usuários e papéis, Responsável BV, vocabulários de etapa/status, parâmetros | admin / migração |
| `corpus` | âncoras `egp`, `input`, `output`; fatos `egp_input`, `egp_output`, `aresta_linhagem`, `resumo_*` | só o publish (fase 1: a sincronização; na Fase 2 o publish grava em `legado`, e o `corpus` só passa a ser escrito na Fase 3) |
| `trabalho` | estado humano: pipeline do EGP, Vínculo, estado do input, leitura dispensada, dependência mantida, profundidades, preworking, Gestão, plano de priorização, decisões de identidade | o app |
| `historico` | `evento` (auditoria única), publicações e métricas | o app e o publish, só inserção |
| `atualizados` | versões recebidas (ADR 0001) | script local |
| `derivado` | views (Escopo efetivo, funil por área, trabalho órfão) | ninguém |
| `compat` | views com nome e forma das tabelas antigas (Fases 1 a 3; somem no fim da Fase 3) | ninguém |
| `legado` | cópia fiel de cada tabela Delta que o app lê; as views `compat` leem daqui (Fases 1 a 3, decisão de 14/10; some no fim da Fase 3) | a sincronização (Fase 1); o app e o publish (Fase 2) |

**Princípios**:
- **Âncoras nunca são apagadas.** O publish faz `MERGE … WHEN NOT MATCHED BY SOURCE THEN
  UPDATE SET orfao = true`. Fatos derivados são `DELETE` + `COPY` na mesma transação.
  Estado humano aponta só para âncoras (o par EGP–input aponta para as duas âncoras, nunca
  para a linha do par). Estado humano cujo par sumiu aparece em `derivado.v_trabalho_orfao`,
  contado e registrado pelo publish.
- FKs `ON UPDATE CASCADE` (um re-key é um `UPDATE` na âncora), `ON DELETE` padrão (apagar
  falha alto), `DEFERRABLE INITIALLY IMMEDIATE` (cargas adiam a checagem na transação).
- **O papel de banco do publish não tem permissão de escrita em `trabalho`**: a proteção das
  colunas humanas vira estrutural.
- O publish inteiro é **uma transação**; guarda falhou → `ROLLBACK` (hoje ele sai com
  `exit 1` depois de já ter escrito, `publish_to_databricks.py:1659`). O publish passa a
  **aplicar** `trabalho.egp_decisao_identidade` em vez de desfazê-la (re-key do
  CPF_Contrato, remoção de duplicados).
- Etapa e status viram tabelas de vocabulário (chave = o próprio rótulo, sem join para
  exibir); `Desatualizado` continua derivado. JSONs de config e do plano viram linhas
  (`plano_priorizacao` versionado com exatamente um vigente).
- `historico.evento` substitui as 8 tabelas de auditoria; o app escreve explicitamente
  (entidade, campo, valor antigo/novo, lote, ator), porque as métricas leem esses campos.

**Deixado sem normalizar de propósito**: a família de safras (camada de contagem, ADR
0002 — estado segue por safra); a Linha de base (CSV, trocá-la é ato deliberado); o estado
efetivo do input (seria a 3ª cópia da regra de `input_state.py`); `resumo_*` (relatório com
universo próprio); as 26 colunas de métricas do EGP.

**Mapeamento antigo → novo**: no relatório do agente de schema (resumo): `sas_inputs_monitor`
→ `corpus.input` + `trabalho.estado_input`; pares e linhagem → `corpus.*` (sem as colunas
copiadas); `sas_egp_pipeline` → `trabalho.pipeline_egp` + `trabalho.vinculo`;
`sas_egp_input_link` → `trabalho.leitura_dispensada`; `sas_gestao_*` →
`trabalho.gestao_*` com alvo exclusivo (EGP **ou** input **ou** família); 8 auditorias →
`historico.evento`; `sas_priorizacao_snapshot` → `trabalho.plano_priorizacao(_egp)`;
`sas_app_config` → `cadastro.parametro` + linhas; `sas_analistas` → `cadastro.usuario`.
Strings `'true'`/`'false'` → boolean, `AAAAMM` → date, listas `' | '` → `text[]`,
timestamps em texto → `timestamptz` (UTC).

**Correções na migração** (cada uma entra no relatório de números que mudaram):
`etapa_migracao` → `etapa`; `desativar` exibido como desativar; os 13 comentários repostos
na chave canônica; estado humano solto ligado à âncora marcada órfã. **Valores padrão do
publish nas colunas humanas migram como estão** — trocá-los por vazio muda regra, fica
para outra decisão.

**Não migram** (ficam no schema Databricks, congelado para sempre): `sas_indicium_egps`,
`sas_ingest_jobs`/`_stage`, `sas_egp_prioridades` (e suas rotas, que não têm tela),
backups (`bkp_*`, `_colapso_*`, `*_bak_*`), `otel_*`, `sas_consulta_*`,
`sas_egp_atualizados_pipeline`/`_audit` (aba aposentada).

**Migrações de schema**: arquivos `.sql` numerados (`0001_schema_inicial.sql`, …) com um
executor de ~50 linhas e tabela de controle. Regra para o time: **tabela ou coluna nova no
app só entra junto com a migração correspondente**. Os `_ensure_*` e as sondas
`ALTER ADD COLUMNS` (113 chamadas) saem.

## SQL

- **Um código, dois bancos na Fase 1.** O app do Databricks segue no ar recebendo o mesmo
  código; `DB_BACKEND` (`databricks`|`postgres`), `IDENTIDADE` (`obo`|`alb`|`dev`) e
  `SOMENTE_LEITURA` escolhem o comportamento. No Postgres, o schema `compat` imita as tabelas
  Delta pelo nome e as funções do Spark pela assinatura: com `search_path = compat, derivado,
  pg_catalog, public`, uma função de `compat` sombreia a do sistema (verificado no PG 17 —
  `regexp_replace` passa a trocar todas as ocorrências), e os domínios `string`/`double`
  fazem `CAST(x AS STRING)` funcionar. O driver devolve cada célula como texto, no formato do
  Databricks, então a API não muda. O que não dá para imitar é reescrito na forma que roda
  nos dois bancos (catálogo no plano 1a, Task H4).
- **Antes da primeira consulta no Postgres**: `sql_lit` e as 4 cópias passam a usar o
  escape do próprio driver (`psycopg.sql.Literal`); os 2 literais de regex de
  `familias.py:377-378` também.
- `run_sql(statement, want_rows, *, params=None)`; parâmetros só onde compensa: escritas
  com valor de requisição (~25 statements), filtros com lista (`= ANY(%s)`), cargas em
  lote (`COPY`), laços de auditoria e `_persist_pins`. Um statement é todo parametrizado
  ou todo inline, nunca misturado (`%` literal quebra o misto).
- Port de dialeto: `MERGE` sem `t.` no `SET`; `current_timestamp()` → `now()`;
  `STRING` → `text`; `count_if(x)` → `count(*) FILTER (WHERE x)`; lambdas/`arrays_overlap`
  → operadores de array; `split()[0]` → `split_part(…, 1)`; `date_format` → `to_char`;
  `regexp_replace` com flag `'g'`; fallbacks por código de erro do Spark → `SQLSTATE`.
- psycopg 3 com pool dimensionado para o fan-out de `_parallel` (19 chamadas).
- **Fase 1 não muda o formato das respostas da API** (booleanos e datas saem como hoje):
  o front fica intocado e a comparação de leituras fica limpa.
- **Texto ordena como no Spark**: o banco do app usa collation `C` (ordem de bytes, a do
  Spark). Com a collation de idioma, `TI`/`Teste` e `Ágil`/`Zeta` saem em outra ordem; isso
  apareceu na primeira comparação real, em 14/10. A collation só se escolhe ao criar o banco:
  `python -m db.migra --cria-banco` cria, o RDS nasce sem `db_name`, e o `migra` recusa banco
  com outra collation.

## Fases

**Passo 0** — teste de login: client OAuth "External" (só `openid email`) no Google da
Indicium + uma **PR mínima na produção**: certificado, regra no ALB compartilhado (login e
página fixa) e registro DNS de `monitoramento-sas.hub.indicium.ai`. Depois, entrar com uma
conta `@bv.com.br`. A regra nasce no root definitivo do app e vira "encaminhar para o app" na
PR completa. A conta training **não** serve: é apagada toda noite pelo `aws-nuke`, e
delegar um subdomínio da produção para ela deixaria uma delegação órfã. Ela fica só para
ensaio de Terraform no mesmo dia, sem DNS e sem dado.

**Planos de implementação**: [1a — fundação](../plans/2026-10-14-migracao-aws-fase1a.md)
(passo 0, infra, migrações, sincronização das 5 primeiras tabelas, backend em modo Postgres,
CI, subida fechada ao BV); [1b](../plans/2026-10-14-migracao-aws-fase1b.md) — espelho fiel
das demais tabelas, port das rotas GET até a comparação zerar, front sem escrita para o
leitor, cadastro do BV e JIT; [2a](../plans/2026-10-15-migracao-aws-fase2a.md) — escrita
no Postgres sobre o espelho; 2b — publish do pacote do orchestrator dentro do app; 2c — a
virada; 2d — o pipeline inteiro (extractor e orchestrator) dentro do app. O de-para para o
schema novo com as correções é a Fase 3 (decisão de 15/10, abaixo).

**Decisão de 14/10 (1b): na Fase 1, cópia fiel em vez de de-para.** O inventário de prod
mostrou caso especial demais para normalizar e remontar byte a byte já na Fase 1: 17 colunas
de data/hora em texto, 8 auditorias com 8 formatos, chaves `familia::` em 4 tabelas,
recebimentos de outputs que não existem, nomes de Responsável BV fora do cadastro, JSON de
configuração. Cada tabela que o app lê entra no schema `legado` como cópia fiel, e a view
`compat` só lê de lá. O de-para com as correções vai para a Fase 3, grupo a grupo. A
auditoria de integridade (FKs) vai junto para a Fase 3. As 5 tabelas do 1a continuam sendo
normalizadas também, e as views do 1a passam a ler o espelho, como as demais. Resultado em
14/10:
- 33/33 tabelas iguais célula a célula contra prod;
- 82/82 rotas iguais entre o app do Databricks e o do Postgres, lendo o mesmo dev;
- sincronização completa em 32 s, com pico de 198 MB.

**Ensaio diário na training** (antes das PRs de produção, a pedido do usuário): um script
sobe do zero, todo dia, VPC, RDS, Fargate, ALB fechado por IP, imagem, migrações e massa
**sintética**, e termina num teste de fumaça. Valida tudo menos o login do Google (sem
domínio lá — validado pelo passo 0) e a sincronização real (dado do BV não entra na
training — validada no dev da AWS). Libera as PRs quando passar do zero duas vezes, com um
`destroy` completo entre elas. O ensaio do dia seguinte confere a convivência com o
aws-nuke, mas não trava as PRs. O Terraform do ensaio mora no repo do app, não no `indicium_infra`.

*Ensaio 2 (2026-10-14, depois de `destroy` completo dos 26 recursos):* passou do zero à fumaça
5/5 em 9,3 min, com os mesmos nomes. O critério está cumprido, e as PRs de produção estão
liberadas.

*Ensaio 1 (2026-10-14, sufixo 1014):* passou do zero ao teste de fumaça em
9,5 min (26 recursos; RDS criado sem `db_name`, banco com collation C, 4 migrações como
mestre sem superusuário, `SET ROLE app_leitura` na tarefa). Fumaça 5/5. Das 48 rotas GET sem
parâmetro de caminho, 22 respondem 200; 6 pedem parâmetro de query; 19 caem na view `compat`
que ainda não existe (as ~40 tabelas da 1b); 1 é dialeto (`split(...)[0]` em
`/api/egp-readiness`, já listado no port). Todas as falhas são 502 explícitos. Memória ~100 MB
e CPU com pico de 36% de 0,5 vCPU na subida (antes da decisão de 1 vCPU, em Decisões de
15/10 (infra)), com massa sintética (40 EGPs): não serve para
dimensionar prod — isso sai do dev da AWS, com dado real.

**Fase 1 — o BV sai do Databricks**
1. Infra (`indicium_infra`): RDS, SGs, ECR, serviço Fargate, regra no ALB com OIDC, DNS,
   Secrets, agendamento da sincronização, alarme. A sincronização lê o Databricks com o
   **token pessoal** de quem cuida do app (decisão de 15/10/2026: é temporário, até tudo
   sair do Databricks), guardado em `.../databricks-sync` com a chave `token`. A chave não
   é `access_token`, que o rotacionador da plataforma trata como valor a sortear. A SP de
   sincronização (F5, `indicium_databricks_aws_infra`) fica de fora. Riscos aceitos:
   - o token vence: crie-o com prazo e anote a data aqui; quando vencer, a sincronização
     falha alto e o alarme avisa;
   - ele lê com as permissões da pessoa, não só o schema do app;
   - ele para se a pessoa sair do projeto.
2. Schema: `0001_schema_inicial.sql` + views `compat` sobre o espelho `legado` (`0005`).
3. Sincronização Databricks → Postgres (tarefa Fargate): uma transação; copia fiel para
   `legado` cada tabela que o app lê e normaliza as 5 do 1a (âncoras = chaves do corpus ∪
   chaves referenciadas pelo estado humano); grava `historico.publicacao`. O de-para das
   demais e a auditoria de integridade passam para a Fase 3 (decisões de 14/10 e 15/10, acima).
4. App de prod na AWS **só leitura para todos**, lendo pelas views `compat`: port de dialeto
   das rotas GET, login, papéis, faixa "dados de HH:MM" (vermelha após 1 h de atraso no
   horário comercial).
5. Dev na AWS só leitura, como a prod, até o plano 2a. Com o 2a ele passa a ter escrita
   (`app_escrita`), mas só depois da Parte E do 2a (deploy da imagem, migrações 0006/0007 e
   a troca do `somente_leitura` do dev), sem sincronização agendada, carregado uma vez com cópia de prod. É o
   laboratório da Fase 2. Nasce desligado (0 tarefas) e só sobe com o deploy da
   develop; ver "Decisões de 15/10 (infra)".
6. Comparação das leituras; cadastro do BV como leitor; comunicação do endereço novo.
7. **JIT volta** quando: o teste de login passou, a comparação das leituras bateu, o BV está
   cadastrado como leitor e já entrou no endereço novo.

**Decisão de 15/10 (Fase 2): o espelho vira a fonte.** Na virada, o app e o publish passam
a escrever nas MESMAS tabelas do `legado`, pelas views `compat`, só com o SQL traduzido. O
Postgres aceita INSERT/UPDATE/DELETE/MERGE nas views simples de uma tabela, e o SQL muda de
dialeto, não de tabela. O de-para para o schema novo com as correções vira a Fase 3, já num
sistema só e sem sincronização no meio. Fazer o de-para antes atrasaria a saída do Databricks
sem mudar o que o usuário vê. Decidido na mesma rodada:
- a virada da escrita acontece num momento só, e não por grupo;
- o publish entra no próprio app: primeiro o pacote do orchestrator, depois o pipeline
  inteiro. Os textos extraídos vão para o Postgres e os binários `.egp` para um S3 privado.
  A VPN fica para ajuste manual, como exceção;
- o botão "Sincronizar grupo" da Gestão sai, e os analistas passam a ser cadastrados à mão;
- não há data alvo.

**Decisões de 15/10 (infra).** Tomadas durante a execução do 2a, depois do plano:
- **Tamanho: Fargate com 1 vCPU / 2 GB.** O app é um processo Python só (uvicorn sem
  workers) e usa um núcleo por vez; com 0,5 vCPU as telas que calculam em Python ficariam até
  2x mais lentas. Mais que 1 vCPU só com workers, e cada um teria o seu cache. Contra EC2
  dedicada e Lambda: com o dev ligado ~10% do tempo, o Fargate empata ou ganha; a Lambda
  esbarra no limite de 1 MB de resposta pelo ALB, no cold start e no publish/pipeline do
  2b/2d.
- **Prod 24/7.** O uso do BV em 30 dias (até 15/10): 4 contas `@bv.com.br`, ~14,8 mil
  consultas, zero no fim de semana, dia mediano das 9h26 às 17h13. O usuário preferiu não
  desligar a prod.
- **Dev desligado por padrão.** Nasce com 0 tarefas; o deploy da develop (pipeline do app,
  `--desired-count 1`) o liga. Uma Lambda às 12h, 15h e 18h (horário de Brasília) desliga se a implantação tem ≥ 2 h
  e o ALB não teve requisição em 2 h; às 22h desliga incondicionalmente.
- **RDS próprio mantido**, depois da revisão do PR de infra, que sugeriu a instância
  compartilhada `indicium-internal-db`. As instâncias compartilhadas aceitam o security group
  do cluster ECS inteiro, e os apps nelas entram com o usuário mestre. Dado de cliente fica
  isolado, com backup e descarte próprios, por ~US$ 16/mês.
- **Custo rastreado.** Todo recurso leva a tag `backstage.spec.system = monitoramento-sas`
  (tag de alocação de custo já ativa). Orçamento de US$ 100/mês com alertas; gasto previsto
  ~US$ 60/mês (RDS ~16, app ~36, dev ~4, sincronização ~1, segredos e logs ~3).

**Fase 2 — o Postgres vira a fonte da verdade**
1. **2a, escrita.** Entram no espelho as 7 tabelas que as escritas e o publish usam: os 4
   audits que faltavam, `sas_resumo_proj`, `sas_pipeline_metrics` e
   `sas_input_alias_canonico`. As escritas são traduzidas: quem grava sai de `_ator()`, a
   hora sai de `AGORA`, e a coluna-alvo do SET perde o `t.`. O papel `app_escrita` só grava
   nas 33 views que o app grava. A prova é um roteiro fixo de edições nos dois lados.
2. **2b, publish no app.** O publish do pacote do orchestrator roda numa transação, com
   prévia, e `publish_egps_atualizados.py` e `identidade_*.py` vêm junto. `sync_dev.py` vira
   `pg_dump`/`pg_restore`. Os scripts de `docs/analises` são histórico e não são portados.
3. **2c, virada.** A gestão passa a editar no app AWS e a sincronização para de vez. Saem a
   aba Perguntas, a pasta `genie/` e a rotina de consulta (ADR 0004). O app do Databricks é
   desligado, e o schema `monitoramento_sas` fica só leitura para sempre.
4. **2d, pipeline no app.** Extractor e orchestrator rodam na AWS, a partir do `.egp` que a
   pessoa sobe.

**Fase 3 (se ainda valer a pena) — o modelo novo.** É o de-para do espelho para o schema da
seção Schema, por grupo, com as correções, o relatório de números que mudaram, a
normalização dos e-mails e a auditoria de integridade. As rotas saem das views `compat`,
`legado` encolhe até sumir, e as escritas passam para `trabalho`/`historico` com
`app.usuario`.

## Critérios de verificação

- **Leitura**: para cada rota GET e conjunto de parâmetros, o JSON do app novo é igual ao do
  antigo partindo dos mesmos dados; diferenças aceitas = as do relatório de correções.
- **Escrita**: um roteiro fixo de edições aplicado no dev antigo e no dev novo, partindo dos
  mesmos dados, produz as mesmas tabelas (`paridade.escritas` e depois
  `paridade.tabelas --escritas`: o instante gravado e o id gerado comparam pela classe do
  valor). Toda rota de escrita tem teste contra um Postgres de verdade
  (`backend/test_escritas_pg.py`, com guarda de cobertura).
- **Testes**: a suíte do backend roda contra um Postgres de verdade no CI (service
  container do Bitbucket); os testes que hoje validam o texto do SQL Spark são reescritos.
- **Papel**: teste automático percorre todas as rotas de escrita e exige 403 para o leitor.
- **Login**: sem login, o app só serve `/login` e `/api/health` (o resto vai para `/login` e
  a API responde 401); cabeçalho OIDC com assinatura inválida, ou com e-mail não verificado
  → 401.
- **Sincronização** (Fase 1; para na virada, 2c): contagem por tabela igual à do Databricks; falha → faixa vermelha +
  alarme.

## Riscos

- A TI do BV bloquear o client OAuth novo (passo 0 existe por isso).
- Booleanos reais quebrando comparações com string: `if v != "true"` (`main.py:8643`) faria
  o checklist nunca completar e parar o avanço automático para Ingestão UAT, em silêncio.
- Formato de timestamp de que o front depende (`fmtTsBR`, `substr(ts,1,7)`).
- Paridade da regex de famílias no Postgres (flag `'g'`, alternância ARE × Python).
- Alvo móvel: outras sessões mudando o app durante o port (regra das migrações).
- Prazo das PRs de infra, que dependem do time de plataforma.

## Dependências externas

- **Time de plataforma**: PRs no `indicium_infra` e no `indicium_databricks_aws_infra`;
  client OAuth "External" no Google da Indicium; registro DNS; religar o JIT.
- **BV**: nada, a menos que o teste de login falhe.

## Fora de escopo

Parâmetros em todos os statements; renomear "Desvincular" na tela;
substituto para o Genie.
