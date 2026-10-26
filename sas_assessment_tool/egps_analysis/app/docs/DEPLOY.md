# Deploy — app `monitoramento-sas`

Como o app vai para o ar. Dois ambientes, dois caminhos:

| Ambiente | App | Schema (`bv_dev_db`) | Como deploya |
|---|---|---|---|
| **Produção** | `monitoramento-sas` | `monitoramento_sas` | **CI/CD** ao integrar na `main` (SP no grupo `bv_admins` = workspace admin). Também manual local. |
| **Dev** | `monitoramento-sas-dev` | `monitoramento_sas_dev` | **CI/CD** ao integrar na `develop` (SP dedicada em `bv_users`, sem acesso a prod). Também manual local: `bash deploy_dev.sh`. |

> **Regra que continua valendo:** deploy em produção é evento sério. O CI/CD só roda no merge para `main` — ou seja, o gate humano é o **merge do PR**. Nada de escrever em prod por fora. Nunca commite `git`/`push` em nome do usuário sem pedido.

O deploy de ambos faz a **mesma sequência**: `npm run build` (bundle do front) → `databricks sync` da pasta `app/` para o workspace → `databricks apps deploy`. A diferença é só qual `app.yaml` (schema) e qual app.

> **`static/` não é versionado.** É saída do build do Vite (`outDir: ../static`). Como o deploy (e o CI) sempre roda `npm run build` antes do sync, o bundle que vai pro ar é sempre reconstruído — a cópia no git nunca seria usada e só gerava conflito de hash entre branches. Por isso `static/` está no `.gitignore`. **Consequência:** num clone novo a pasta não existe até você buildar. O dev normal usa o Vite (`npm run dev`, serve o fonte) e não precisa dela; só se for rodar o backend standalone (`python backend/main.py`, que serve `static/`) rode antes `cd frontend && npm run build`.

---

## Produção — CI/CD (Bitbucket Pipelines)

**Fluxo:** abra PR → merge na `main`. Se o merge tocou `egps_analysis/app/**`, o pipeline dispara sozinho:

1. **Testes** — `pytest` da lógica de priorização (`backend/test_priorizacao_logic.py`, puro, sem Databricks).
2. **Build + deploy** — instala a Databricks CLI, `npm ci` + `deploy_prod.sh` (build → sync → deploy → **verificação do bundle deployado**).

Config: [`bitbucket-pipelines.yml`](../../../bitbucket-pipelines.yml) (raiz do repo). Script: [`deploy_prod.sh`](../deploy_prod.sh).

### Setup uma-vez (antes do 1º deploy pela pipeline)

1. **Service principal (OAuth M2M).** Crie um SP no workspace (ou reuse um de CI) e um **OAuth secret** (client id + secret). É a identidade que a pipeline usa — não é um usuário.
2. **Permissões do SP:**
   - **CAN_MANAGE no app** `monitoramento-sas` (Compute → Apps → Permissions) — para `apps deploy`.
   - **Write no caminho do workspace** onde o app é sincronizado (o `WS_PROD`; default = pasta do app do lucas). Se o SP não puder escrever lá, defina `WS_PROD` para um caminho que ele possa (ex.: pasta do próprio SP ou `/Workspace/Shared/...`) — o `apps deploy` aceita qualquer `--source-code-path` legível pelo deployer.
   - **Não precisa** de grants de Unity Catalog para o SP: o app roda com `REQUIRE_OBO=true`, então quem lê/escreve dado é **o usuário logado** (grants por usuário/grupo — ver README §Deploy). O SP só publica o código.
3. **Variáveis de repositório** (Repository settings → Repository variables, **Secured**; de preferência com escopo no *deployment* `production`):
   | Variável | Valor |
   |---|---|
   | `DATABRICKS_HOST` | `https://<workspace>.cloud.databricks.com` |
   | `DATABRICKS_CLIENT_ID` | client id do SP |
   | `DATABRICKS_CLIENT_SECRET` | secret do SP |
   | `WS_PROD` *(opcional)* | caminho de sync, se diferente do default |
   A CLI lê `DATABRICKS_HOST`/`DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET` do ambiente automaticamente (auth M2M) — o `deploy_prod.sh` detecta o `CLIENT_ID` e **não** usa profile.
4. **Environment `production` no Bitbucket** (Repository settings → Deployments) — o step usa `deployment: production`. Crie-o (pode escopar os secrets acima só nele). Se preferir não usar environments, remova a linha `deployment: production` do `bitbucket-pipelines.yml`.

### Acompanhar / rodar sob demanda / rollback

- **Acompanhar:** Bitbucket → Pipelines (log do step mostra `[prod] ... deploy verificado OK`).
- **Redeploy sem novo commit:** Pipelines → Run pipeline → **custom: `deploy-prod-manual`**.
- **Rollback:** reverta o commit na `main` (o merge do revert re-dispara o deploy com o código anterior). O app do Databricks também guarda deployments anteriores — dá para promover um antigo pelo painel de Apps, mas o caminho canônico é reverter na `main` para o git e o app não divergirem.

### Fallback: deploy de prod manual (mesma lógica)

Se a pipeline estiver indisponível e precisar subir prod na mão, o **mesmo script** roda local com profile:

```bash
cd egps_analysis/app
DATABRICKS_PROFILE=bv bash deploy_prod.sh      # bv e o default; pode omitir
```

Exige o "ok" humano explícito (é escrita em prod). O script tem a guarda anti-corrida e a verificação do bundle embutidas.

---

## Dev — `monitoramento-sas-dev` (manual)

Ambiente isolado (schema `monitoramento_sas_dev`) para testar mudanças **sem tocar prod**. Deploy local, sempre manual:

```bash
cd egps_analysis/app
bash deploy_dev.sh
```

O [`deploy_dev.sh`](../deploy_dev.sh):
- troca `app.yaml` → `app.dev.yaml` (que só muda `PUBLISH_SCHEMA` para `monitoramento_sas_dev`);
- faz `sync` + `deploy` do app `monitoramento-sas-dev`;
- **sempre restaura** o `app.yaml` de prod no fim (via `trap EXIT`), mesmo se o deploy falhar — deixa `.app.yaml.prod.bak` só durante a janela.

### Cuidados no dev

- **Pré-requisito (1ª vez):** o app `monitoramento-sas-dev` precisa existir (`databricks apps create monitoramento-sas-dev -p bv`) e, como app criado por CLI **não herda os `user_api_scopes`**, é preciso setar os escopos (`sql` + reads de catálogo) senão o OBO devolve 403. O schema `monitoramento_sas_dev` e suas grants por usuário também precisam existir.
- **Corrida com prod:** enquanto o `deploy_dev.sh` roda, o `app.yaml` fica apontando para dev por alguns segundos. Um deploy de **prod manual** nessa janela apontaria prod para o schema dev — por isso o `deploy_prod.sh` **aborta** se achar `.app.yaml.prod.bak` ou o schema errado no `app.yaml`. Não rode os dois em paralelo.
- **Dev não espelha prod automaticamente** — o schema dev tem seus próprios dados (popule com o publish local em `PUBLISH_SCHEMA=monitoramento_sas_dev`, ou com `sync_dev.py`).
- **Flag de feature nasce no `app.dev.yaml` e só depois gradua para o `app.yaml`.** A `FAMILIAS_SAFRA` (família de safras como unidade de input — ver `README.md` §Decisões de design) seguiu esse caminho: dev em 15/09/2026, prod em 17/09/2026, e hoje está **ligada nos dois** manifestos. Desligar = remover as duas linhas e redeployar (nada é materializado). Como o `trap` do `deploy_dev.sh` restaura o `app.yaml` de prod, a flag não vaza para prod por acidente — mas confira o `env` deployado na verificação abaixo quando o comportamento contado (nº de inputs) não for o esperado.

---

## Verificação (vale para os dois)

Um `SUCCEEDED` do `apps deploy` **não garante** que o código novo está no ar (o sync pode ter servido bundle velho). Por isso os scripts conferem, ao final, se o **hash do bundle** (`static/assets/index-*.js`) no workspace bate com o local. Se quiser conferir à mão:

```bash
WS=/Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas   # ou o dev
grep -o 'assets/index-[^"]*\.js' static/index.html                                    # local
databricks workspace export "$WS/static/index.html" -p bv | grep -o 'assets/index-[^"]*\.js'  # deployado
databricks workspace export "$WS/app.yaml" -p bv | grep -A1 PUBLISH_SCHEMA             # schema certo?
```

Os dois hashes têm de ser iguais e o `PUBLISH_SCHEMA` tem de ser o do ambiente esperado.
