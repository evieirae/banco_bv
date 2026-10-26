# App dev (mirror completo) — `monitoramento-sas-dev` — Design Spec

- **Data:** 2026-07-07
- **Objetivo:** ambiente dev isolado do app `monitoramento-sas` pra testar mudanças (a começar pelo sub-projeto 1: grafo determinístico/completo) **antes** de tocar prod, sem impactar os usuários que já usam o app.
- **Status:** design aprovado ("Pode seguir").

## 1. Isolamento (ponto crítico)

O app já é parametrizado por env: `PUBLISH_CATALOG`/`PUBLISH_SCHEMA`/`DATABRICKS_WAREHOUSE_ID` (`app.yaml`). Backend (`main.py`), `ingest.py` (Processar) e `publish` **todos** derivam catalog/schema/Volume do env → apontar o dev pra outro schema isola 100% dos dados.

- **Schema dev:** `bv_dev_db.monitoramento_sas_dev` (tabelas + Volume `/Volumes/bv_dev_db/monitoramento_sas_dev/pipeline`).
- **App dev:** `monitoramento-sas-dev` (URL + service principal próprios).
- **Compartilhado:** só o SQL Warehouse `5922c26f81f1bbdd` (compute sem estado). Estado mutável compartilhado com prod: **zero**.
- Prod (`monitoramento_sas`) nunca é referenciada pelo dev.

## 2. Passos

1. `CREATE SCHEMA bv_dev_db.monitoramento_sas_dev` + `CREATE VOLUME .../pipeline` (owner = lucas.muller).
2. Copiar corpus prod→dev **server-side** no Volume (`text_egps/`, `src/`).
3. `databricks apps create monitoramento-sas-dev` → nasce com SP próprio (client-id descoberto após criar).
4. Grants ao SP do dev: warehouse `CAN_USE`; `USE_CATALOG` em `bv_dev_db`; `USE_SCHEMA`+`MANAGE`+`ALL_PRIVILEGES` no schema dev; `READ/WRITE VOLUME` no volume dev. (Ver [[monitoramento-sas-sp-pipeline-barriers]] — mesmas 6 barreiras.)
5. Deploy do working tree (inclui sub-projeto 1 vendored) com `app.dev.yaml` (schema dev), via `deploy_dev.sh` (trap-restore do `app.yaml` prod).
6. Semear + testar: publish local `--catalog bv_dev_db --schema monitoramento_sas_dev` (grafo novo 392/ambiguidade) para dados imediatos; corpus no Volume pronto pra clicar **Processar** no dev e testar o pipeline in-container.
7. Verificar: URL dev renderiza 392/ambiguidade; prod intacto (URL separada, 201).

## 3. `app.yaml` — proteção contra vazamento dev→prod

`app.yaml` (prod) fica intocado no repo. `app.dev.yaml` = dev (só `PUBLISH_SCHEMA` muda). `deploy_dev.sh` faz backup do `app.yaml`, troca pra dev, sync+deploy, e **sempre restaura** o prod no `trap EXIT` (mesmo em falha). Deploy de prod (`README §Deploy`) nunca pega schema dev por engano.

## 4. Fora de escopo

- Warehouse separado pro dev (compartilhar é suficiente; separar depois se houver contenção).
- Promoção automatizada dev→prod (continua manual, com consentimento).
- Mudanças no código do app (sub-projeto 1 é só pipeline; o dev valida o render + o Processar).

## 5. Critérios de aceitação

- App dev responde numa URL própria, lendo `monitoramento_sas_dev`.
- Processar no dev popula o schema dev (não o prod) com o grafo novo.
- Prod (`monitoramento-sas`) inalterado durante todo o processo (URL, 201, tabelas).
- `app.yaml` do repo permanece prod após qualquer deploy dev.

## 6. Riscos

- Criação de recursos (schema/volume/app) + grants RBAC podem exigir permissão elevada → autorização explícita na hora (classificador bloqueia).
- Custo: 2º app = compute extra enquanto ligado (parar o dev quando ocioso).
- Deploy concorrente mata job de Processar (rodar teste em janela sem deploy).
