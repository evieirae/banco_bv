# Ingestão in-app — Design Spec

- **Data:** 2026-07-03
- **App:** `monitoramento-sas` (`egps_analysis/app/`)
- **Status:** design aprovado no ambiente; aguardando revisão do spec antes do plano de implementação
- **Autor:** Lucas Müller (+ Claude Code)

## 1. Objetivo

Permitir que um membro do time faça, **direto no app**, o que hoje exige rodar 4 scripts locais:

1. **Subir `chameleon.csv`** (o catálogo de ingestões do Chameleon, hoje exportado do BigQuery localmente).
2. **Subir um `.egp`** e o app extrair os inputs daquele EGP, recalcular o inventário corpus-wide e publicar nas tabelas Delta — "carrego o EGP e o app faz tudo".

Sem GCP em nenhum ponto (o `chameleon.csv` chega **por upload**, não é regenerado no app).

## 2. Decisões (com o porquê)

Todas confirmadas com o usuário via perguntas dirigidas:

| Decisão | Escolha | Porquê |
|---|---|---|
| **Onde roda o pipeline pesado** | **Dentro do container do app** | Escolha do usuário: dispatch simples, sem montar infra de Job. Trade-off aceito: restart do app mata o job em andamento. |
| **Estado durável** | **UC Volume** `bv_dev_db.monitoramento_sas.pipeline` | FS do container é efêmero (apagado a cada restart/redeploy). O Volume sobrevive e é acessível pelo SP do app. |
| **Disparo do recálculo** | **Stage + botão "Processar & publicar"** | O `orchestrator` é corpus-wide (~5.5min sobre todos os 1741 arquivos); não dá pra rodar por arquivo. Sobe-se um lote, depois roda 1 recálculo. |
| **Acesso** | **Só `bv_users`** | Mesma trava da aba Gestão (`is_account_group_member('bv_users')`). Processar reescreve tabelas de prod. |
| **Identidade do job em background** | **Service principal do app** (não OBO) | Um job de 5.5min sobreviveria ao token OBO do usuário (curto). O SP tem grants duráveis. |

## 3. Ambiente verificado (2026-07-03)

Checagens já executadas (profile `bv`):

- **App:** `monitoramento-sas`, compute **Medium (2 vCPU, 6 GB, 0.5 DBU/h)**. 6 GB acomoda o pico do orchestrator (~1–2 GB, em subprocess separado).
- **Service principal do app:** `app-3a6zfb monitoramento-sas`, client id `5b524c4c-c116-4de7-b414-01f719e49d0d`.
- **Volume criado:** `bv_dev_db.monitoramento_sas.pipeline` (MANAGED, vazio) — escrita + leitura validadas.
- **Grants do SP (concedidos na verificação):**
  - `USE_CATALOG` em `bv_dev_db` (faltava; sem isso o SP não alcança nem tabelas nem `/Volumes/...`).
  - `READ_VOLUME` + `WRITE_VOLUME` no volume `pipeline`.
  - Já possuía `ALL_PRIVILEGES` no schema `monitoramento_sas` → publish-como-SP escreve/cria tabelas sem novo grant.
- **Warehouse:** `5922c26f81f1bbdd` (env `DATABRICKS_WAREHOUSE_ID`).

## 4. Arquitetura & fluxo de dados

```
Upload .egp  ─► extrai 1 EGP (subprocess, rápido) ─► grava text_egps/<key>.txt no Volume
             └► parse do header I/O ─► preview dos inputs na tela + linha em sas_ingest_stage

Upload chameleon.csv ─► valida colunas ─► grava src/chameleon.csv no Volume (substitui)

[Processar & publicar]  (bv_users) ─► job background como SP:
   1. sync Volume → workdir local (text_egps/ + src/)
   2. orchestrator_inventory.py  (corpus inteiro, ~5.5min) ─► out/01..06.csv
   3. publish_to_databricks.py   ─► MERGE nas tabelas Delta (preserva colunas humanas)
   4. sync out/ CSVs de volta ao Volume (auditoria)
   5. bump da geração do cache de linhagem ─► UI reflete dados novos
   6. atualiza sas_ingest_jobs (status=done) e marca stage como processado
```

## 5. Armazenamento — Volume `bv_dev_db.monitoramento_sas.pipeline`

```
/Volumes/bv_dev_db/monitoramento_sas/pipeline/
  text_egps/                      corpus (seed único: 1741 .txt atuais; cresce a cada upload)
  src/chameleon.csv               (upload pela UI)
  src/inventario_transacional.csv (seed único, 36.9MB, raramente muda)
  src/inputs_modernizados.csv     (seed único)
  out/01..06.csv                  (gerados pelo orchestrator; snapshot p/ auditoria)
```

**I/O:** via **Files API do `databricks-sdk`** (já dependência) usando a auth default = SP. Preferência de execução: sincronizar Volume→workdir local temporário, rodar o pipeline no FS local (rápido pro pandas), e subir de volta o que mudou. (Alternativa: rodar direto no mount `/Volumes/...` se o FUSE estiver gravável — a decidir na implementação por um probe; o default do plano é sync local.)

**Seed inicial (setup 1x):** subir o corpus e os `src/` atuais da máquina local para o Volume (`databricks fs cp -r`). ~140MB, uma vez.

## 6. Backend (`main.py` + pipeline embutido)

### 6.1 Dependências e deploy
- `app/requirements.txt` += `pandas`, `openpyxl`, `pyarrow`.
- Copiar os scripts do pipeline para dentro do deploy do app: `app/pipeline/{egps_extractor.py, orchestrator_inventory.py, publish_to_databricks.py, libname_resolver.py}`. **Fonte da verdade continua em `egps_analysis/`**; `app/pipeline/` é cópia deployável (definir sincronização — symlink no dev / cópia no build; a evitar divergência).

### 6.2 Endpoints (todos com `_require_gestao`)
- `POST /api/ingest/egp` (multipart: arquivo `.egp` + `area`) — salva num tmp, roda extrator p/ 1 arquivo, sobe `.txt` ao Volume, registra em `sas_ingest_stage`, devolve **preview** dos inputs extraídos. Rápido.
- `POST /api/ingest/chameleon` (multipart: `chameleon.csv`) — valida presença das colunas esperadas (`NmTabela`, `NmTabelaOrigem`, `DsOrigem`, `NmFonteDados`, …), grava em `src/chameleon.csv` no Volume, marca "chameleon pendente".
- `GET /api/ingest/stage` — lista o que está staged: EGPs novos/atualizados não processados + se há chameleon novo desde o último `Processar`.
- `POST /api/ingest/processar` — se não houver job `running`, cria linha `running` em `sas_ingest_jobs`, dispara o pipeline em **thread/subprocess** de background, retorna `job_id`. Se já houver, 409.
- `GET /api/ingest/status?job_id=` — estado atual (`queued|running|<etapa>|done|error|interrupted`), timestamps, contadores, mensagem de erro.
- `DELETE /api/ingest/stage/{egp_key}` — remove um EGP do stage antes de processar (apaga o `.txt` do Volume + linha do stage). *(nice-to-have; incluir se barato.)*

### 6.3 Tabelas de controle (novas)
- `sas_ingest_jobs` — histórico/estado de execuções: `job_id, status, etapa, started_at, finished_at, started_by, n_egps, erro`.
- `sas_ingest_stage` — uploads pendentes: `egp_key, area, uploaded_by, uploaded_at, processed BOOLEAN, job_id`.
- Criadas laz­y por helpers `_ensure_*` (padrão já usado no app).

### 6.4 Execução & concorrência
- **Um processamento por vez** (lock em processo + guarda pela linha `running` em `sas_ingest_jobs`).
- Se o app reinicia no meio: jobs `running` órfãos aparecem como `interrupted` na UI e podem ser re-disparados. O pipeline é **idempotente** — extrator re-chaveia por `PROJECT`; publish faz `MERGE` preservando `status_humano/responsavel/observacao`.
- **Auth do publish:** adaptar `publish_to_databricks.py` para autenticar pela auth default do SDK (SP do app) em vez de `--profile bv`.

## 7. Frontend — nova aba `Ingestão` (só `bv_users`)

- Registrada em `routes.ts` como `/ingestao`, escondida quando `!config.is_gestao` (reusa o gate já existente; renomear/generalizar de `is_gestao` se fizer sentido).
- **Upload** (drag-drop):
  - `.egp` com **seletor de Área** obrigatório → ao subir, mostra card de **preview** com os inputs daquele EGP (origem/tabela/status).
  - `chameleon.csv` → confirma substituição + mostra nº de linhas validadas.
- **Stage:** lista dos EGPs staged + indicador de "chameleon novo pendente".
- **Botão `Processar & publicar`** com aviso claro ("~5.5 min; reescreve as tabelas") + **barra de progresso** (poll de `/api/ingest/status`): etapas extraindo → orchestrator → publicando → pronto. Bloqueia novo disparo enquanto `running`.
- Ao concluir: toast de sucesso + invalidação das queries do React Query (os dados novos aparecem nas outras abas).

## 8. Adaptações nos scripts existentes

- `publish_to_databricks.py`: aceitar auth via SDK default (SP) além de `--profile`; permitir apontar `BASE`/paths de entrada para o workdir.
- `egps_extractor.py`: garantir modo "1 arquivo → 1 `.txt`" com `--area` explícito e diretório de saída parametrizável (já suporta path arg + `EGP_BUSINESS_AREA`; confirmar flags na implementação).
- `orchestrator_inventory.py`: parametrizar diretórios de entrada (`text_egps/`, `src/`) e saída (`out/`) para o workdir (hoje relativos ao cwd — rodar com `cwd=workdir` já resolve; preferir args explícitos).

## 9. Segurança & concorrência

- Endpoints de escrita/processamento gated por `_require_gestao` (grupo `bv_users`), reforço no backend (não só esconder no front).
- O **SP do app** ganhou capacidade de reescrever o schema `monitoramento_sas` (já tinha `ALL_PRIVILEGES`; agora com `USE_CATALOG` isso é efetivo) e o Volume. O gatilho é sempre um membro `bv_users`, mas a escrita ocorre como SP — documentar.
- `publish` faz `MERGE` seletivo → **não apaga** colunas humanas (`status_humano/responsavel/observacao`).
- Validação de upload: só aceitar `.egp` (zip válido) e `.csv` com colunas esperadas; limitar tamanho.

## 10. Riscos & mitigação

| Risco | Mitigação |
|---|---|
| OOM no orchestrator | **Resolvido**: 6 GB de container vs ~1–2 GB de pico em subprocess isolado. |
| Restart mata job em andamento | Status `interrupted` + re-disparo; pipeline idempotente. |
| `app/pipeline/` divergir de `egps_analysis/` | Definir sync (symlink dev / cópia no deploy) e documentar como armadilha. |
| FUSE `/Volumes` não gravável no runtime | Default = sync via Files API para workdir local; probe decide. |
| Upload malicioso/errado | Validação de tipo/colunas/tamanho + gate `bv_users`. |

## 11. Fora de escopo (YAGNI)

- Regenerar `chameleon.csv` via BigQuery no app (sem creds; continua upload).
- Upload de `inventario_transacional.csv` / `inputs_modernizados.csv` pela UI (residentes no Volume, editados fora).
- Recompute incremental de 1 EGP (continua corpus-wide).
- Migrar a execução para um Databricks Job (revisitar só se o modelo in-container mostrar limitação real).

## 12. Setup / provisionamento

1. ✅ Criar Volume `bv_dev_db.monitoramento_sas.pipeline` (feito).
2. ✅ Grants ao SP: `USE_CATALOG` (catálogo) + `READ/WRITE VOLUME` (volume) (feito).
3. ⏳ Seed do Volume: subir `text_egps/` + `src/{inventario_transacional.csv, inputs_modernizados.csv}` (escrita real; fazer na implementação com ok do usuário).
4. ⏳ `app/requirements.txt` + `app/pipeline/` no deploy.

## 13. Critérios de aceitação

- Membro `bv_users` sobe um `.egp` → vê o preview dos inputs em segundos; o `.txt` fica no Volume.
- Sobe `chameleon.csv` → validado e persistido no Volume.
- `Processar & publicar` → progresso visível; ao fim, as tabelas Delta refletem o novo EGP e o novo chameleon, **sem perder** edições humanas.
- Não-membro não vê a aba e recebe 403 nos endpoints.
- Restart no meio do job → UI mostra `interrupted`; re-disparo conclui.
