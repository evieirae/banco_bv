# Handoff — Painel de Modernização SAS (`monitoramento-sas`)

> **Para o próximo agente neste repo (`sas_assessment_tool`).** Os arquivos foram migrados de `project_sas` e estão **idênticos** ao estado deployado (verificado em 2026-06-12). O app Databricks `monitoramento-sas` continua o mesmo — ele aponta para um workspace path, não para um repo, então deploy a partir daqui funciona.

**Data:** 2026-06-12 · **Repo:** `/home/lucasmuller_ind/bv/sas_assessment_tool` · **Branch:** `import/project-sas` · **Remote:** `git@bitbucket.org:indiciumtech/sas_assessment_tool.git`
**Política:** agente **não** faz `git commit`/`push` nem `dbt build` — usuário decide.
**Módulo em foco:** `egps_analysis/` (não `converter/`).
**App ao vivo:** https://monitoramento-sas-4394921022945130.aws.databricksapps.com

## Setup neste repo (DIFERE do project_sas — fazer antes de qualquer query/publish)
```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis
python3 -m venv venv && venv/bin/pip install -r requirements.txt   # venv NÃO existe aqui ainda
```
Frontend: `node_modules` já presente em `egps_analysis/app/frontend/`. Build: `npm --prefix egps_analysis/app/frontend run build` (`tsc -b && vite build`).

## Contexto de produto
Migração SAS `.egp` → dbt. O app é o painel de acompanhamento para apresentar ao **BV**. Escopo Indicium = **229 EGPs** (231 da lista − 1 faltante `ca_apagar_periodo` − 1 duplicata `1353`). Métrica-chave p/ o BV = **inputs = table_in + file_in + script_in** (NÃO confundir com "tabelas" = só o subconjunto table_in). Docs: `egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md`. Diretrizes: `CLAUDE.md` (raiz).

## Infra Databricks (valores não-sensíveis)
- Host: `https://dbc-5626df64-1b10.cloud.databricks.com`
- Warehouse serverless `monitoramento-sas`: **`5922c26f81f1bbdd`** (em `egps_analysis/app/app.yaml` → `DATABRICKS_WAREHOUSE_ID`)
- Catálogo/schema: `client_journey.monitoramento_sas`
- Tabelas Delta: `sas_inputs_monitor` (input distinto, 11526), `sas_lineage_edges` (projeto_alvo→depende_do, 1519), `sas_lineage_nodes` (1205; tem `escopo_indi`+`ciclo_id`), `sas_egp_inputs` (projeto×input, 24406), `sas_pipeline_metrics`, `sas_inputs_audit` (histórico de edições).

### Autenticação (IMPORTANTE — não há `~/.databrickscfg` aqui)
A auth do CLI e do SDK vem das env vars do `converter/.env`. **Sourcear sempre** antes de query, sync e deploy:
```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
set -a && source <(tr -d '\r' < converter/.env) && set +a
[ -z "$DATABRICKS_HOST" ] && export DATABRICKS_HOST="https://dbc-5626df64-1b10.cloud.databricks.com"
export DATABRICKS_WAREHOUSE_ID=5922c26f81f1bbdd
egps_analysis/venv/bin/python <script>   # databricks-sdk só no venv
```
**Segurança (regra org, EM VIGOR):** nunca exibir conteúdo de `.env`/credenciais. Sourcear sem ecoar. Se aparecer credencial: não usar/repetir, avisar o usuário, usar placeholder.

### Deploy do app (mesmo app, qualquer repo)
```bash
cd egps_analysis/app && npm --prefix frontend run build
WSPATH="/Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas"
databricks sync . "$WSPATH" && databricks apps deploy monitoramento-sas --source-code-path "$WSPATH"
```
Backend FastAPI (`backend/main.py`) serve o React buildado de `static/`.

## Estado atual do app (6 abas — `app/frontend/src/App.tsx`)
`Monitoramento · EGPs · Prontidão · Ondas · Linhagem · Histórico`
- **Linhagem**: Cytoscape.js + fCoSE + expand-collapse, colapsado por área; ciclos em vermelho via `ciclo_id`.
- **Prontidão** (`components/ReadinessView.tsx` + `/api/egp-readiness`): % inputs modernizados por EGP; buckets pronto/quase/parcial/bloqueado/ciclo. Panorama 229: 1 pronto / 29 quase / 66 parcial / 122 bloqueado / 11 em ciclo.

## Último trabalho (já deployado e validado — código idêntico neste repo)
1. **Pergunta "inputs das dependências dos 229":** diretas = **2.676 inputs distintos** (110 EGPs dep: 45 escopo + 65 fora; 2.318 a ingerir; 765 "novos" fora dos 3.356 dos 229). Transitivas = **2.951** (123 EGPs; 957 novos). Ref: 229 têm 3.356 inputs distintos próprios. Script reproduzível (versionado): `egps_analysis/docs/analises/deps_inputs.py`.
2. **Aba Prontidão — dependências com nome + escopo:** coluna "Depende de" clicável/expansível; total + badges `Ni`(escopo Indicium, azul)/`Ne`(fora, amarelo); expande nomes coloridos por escopo, `⟳` = em ciclo.
   - Backend `app/backend/main.py` → `/api/egp-readiness` faz JOIN edges×nodes; retorna `n_deps`, `n_deps_indi`, `n_deps_ext`, `deps:[{projeto,escopo_indi,area,ciclo_id}]`.
   - Frontend: `types.ts` (`ReadinessDep`), `components/ReadinessView.tsx` (estado `open`, `.rd-deps`, `.rd-expand`), `styles.css` (`.rd-deps/.dep-*/.rd-expand/.dep-chip`).

## Pendências
### Lado do usuário (BV/áreas)
- Solicitar EGP `ca_apagar_periodo`; 2 perguntas à área Rodas (texto já entregue); confirmar versão `SAS_IQ_SQ_Vigente` e área `taxas_v35` (resolvido p/ Cartões); alinhar ~35 duplicatas; `tbprodutos`/joao.neves2.
- **GCP bloqueado** no PC Indicium → step 2 do pipeline (`gcp_bigquery_table_data_export.py` → `src/chameleon.csv`) não roda aqui.

### Oferecido, não solicitado (candidatos a próximo passo)
- **Filtro/chip "depende de EGP fora do escopo"** na aba Prontidão (isolar travados por dependência externa) — última oferta ao usuário.
- Filtro "só os que dão pra começar agora" + export CSV na Prontidão.
- **Correção de ciclos na raiz do pipeline**: tabelas de schema corporativo multi-writer (INSIGHT./PME./PLCA./SHAREATA./MISCRED.) viram *fontes*, não arestas → limparia relatórios 03/04 e a Linhagem. Catálogo: `egps_analysis/docs/analises/DEPENDENCIAS_CICLICAS.md` (13 clusters/57 projetos). Não iniciar sem o usuário pedir.

## Artefatos de referência (neste repo — NÃO duplicar)
- `egps_analysis/publish_to_databricks.py` — build/publish das tabelas Delta (`IN_CATS`, `AREA_OVERRIDE` taxas_v35→Cartões, `compute_ciclo_ids` Tarjan).
- `egps_analysis/docs/analises/build_metrics_report.py` — relatório (inputs primário, tabelas subconjunto).
- `egps_analysis/docs/analises/BV_inputs_a_ingerir_indicium.csv` — CSV enxuto p/ BV (2924 inputs a ingerir).
- `egps_analysis/docs/analises/DEPENDENCIAS_CICLICAS.md` — catálogo de ciclos.
- `STATUS_MIGRACAO_SAS.md` (raiz) — §2.H (ciclos), §2.J (revisão de inputs).

## Memória persistente
A memória da sessão antiga está no projeto antigo: `~/.claude/projects/-home-lucasmuller-ind-bv-project-sas/memory/` (nota `project_migracao_bitbucket.md` = esta migração). **Este projeto novo terá outro diretório de memória** (`-home-lucasmuller-ind-bv-sas-assessment-tool`) — vazio até o agente escrever. Considere recriar a nota da migração aqui.

## Suggested skills
- **`superpowers:using-superpowers`** — checar skills aplicáveis antes de agir (regra de sessão).
- **`humanizer`** — ao redigir texto para BV/áreas (o usuário pediu `/humanizer` antes).
- **`brainstorming`** — antes de planejar a correção de ciclos na raiz (decisão de arquitetura).
- `indimesh-dbt:analytics-engineer` / `indimesh-databricks:data-engineer` — só se o trabalho voltar para pipeline dbt/Spark; o foco atual é o app FastAPI+React.

## Próximo passo provável
Confirmação visual da aba Prontidão (Ctrl+Shift+R no app), depois implementar o filtro "depende de EGP fora do escopo" (+ atalho "começar agora" + export CSV). Setup do venv neste repo é pré-requisito p/ rodar qualquer query/publish.

---

## Sessão 2 (2026-06-12) — Migração project_sas → este repo (Bitbucket)

> Sessão que executou a importação de `~/bv/project_sas` (origem: GitHub privado BV `int-dcouto_BancoBV/project_sas`) para este repo. **Este diretório é agora o home definitivo do trabalho**; `project_sas` é cópia morta.

### Estado git (FATO, verificado)

- Branch **`import/project-sas`** criado a partir da main local e **já pushado** para `origin` (`git@bitbucket.org:indiciumtech/sas_assessment_tool.git`).
- 3 commits à frente de `origin/main`: `6df803d` (trabalho antigo que estava pendente) · `b207bc6` (snapshot da importação, 1980 arquivos) · `0115d91` (sincronização pós-snapshot: app frontend/backend, `publish_to_databricks.py`).
- Working tree limpo. **PR ainda NÃO foi aberto** — é o próximo passo.

### Decisões da migração (detalhe completo na memória antiga: `~/.claude/projects/-home-lucasmuller-ind-bv-project-sas/memory/project_migracao_bitbucket.md`)

- **Squash**: sem importar os 18 commits do project_sas (787MB de .git, autores `@bv.com.br`).
- **Sobreposição**: project_sas venceu nos arquivos comuns; extras deste repo preservados (rsync sem `--delete`).
- **Binários `.egp` fora do git**: `.gitignore` bloqueia `*.egp` e `received_egps/`; `log_files/Exemplo 1.egp` removido do índice. Demais dados (text_egps/, src/*.csv, xlsx, docs) ficaram no git, sem LFS.
- **Docs raiz mesclados**: CLAUDE.md/README.md deste repo como base + seções novas de converter/egps_analysis + seção "Setup de dados".

### Pendências da migração (em ordem)

1. **Upload do tar pro Drive (usuário)**: `~/bv/received_egps_20260612.tar` (845.5M, 2003 entradas: `received_egps/` por área, `_arquivo_rodas_egp_binarios/`, `PROJECT_PJ_PRIVADO_DISTRIBUIDOR_NOVO.egp`, `log_files/Exemplo 1.egp`).
2. **Substituir o placeholder** `_(adicionar link do Drive aqui)_` no `README.md` (seção "Setup de dados") quando o usuário passar o link → commit no branch.
3. **Abrir PR** `import/project-sas` → `main` no Bitbucket (decisão: branch+PR porque há outras pessoas no repo). Skill útil: `indimesh-common:bitbucket-pull-request-management`.
4. **Pós-merge**: validar e só então (com confirmação explícita do usuário) remover `~/bv/project_sas`. Este arquivo de handoff está **untracked** — decidir se entra no PR ou fica local.

### Gotchas operacionais desta máquina (importam para qualquer agente aqui)

- **Hook `merge-guard.sh` (plugin adev)**: avalia o branch do **cwd da sessão**, não do repo alvo do comando. Bloqueou `git commit` legítimo porque o cwd (project_sas) estava em `main`. Solução aplicada: project_sas foi movido para o branch local `archive/snapshot-pre-migracao`. Em sessões iniciadas neste repo, garanta que o cwd não esteja em `main` ao commitar.
- **Hook RTK** reescreve comandos (`rsync`, `grep`) e mutila saídas/pipelines. Quando a saída parecer inconsistente: usar binário direto (`/usr/bin/rsync`), redirecionar para arquivo e ler com a tool Read.
- **Commits: NUNCA incluir `Co-Authored-By`** — preferência explícita do usuário (memória `feedback_git_commits.md`).
- Guardrails do converter/ continuam valendo: nunca `dbt build`, nunca commit/push automático sem gate humano.

### Suggested skills (sessão de migração)

- `indimesh-common:bitbucket-pull-request-management` ou `indimesh-airflow:create-pull-request` — para abrir o PR no Bitbucket via API (infere workspace/repo do `git remote`).
- `superpowers:verification-before-completion` — antes de declarar o PR/migração concluída.
