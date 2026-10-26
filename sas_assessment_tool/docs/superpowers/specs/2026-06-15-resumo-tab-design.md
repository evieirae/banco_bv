# Design — Nova aba "Resumo" (funil por área + inputs por origem)

**Data:** 2026-06-15
**Componente:** `egps_analysis` (publish) + `egps_analysis/app` (FastAPI + React/TS)
**Status:** aprovado para implementação

## 1. Problema / objetivo

Reproduzir, **como uma aba do app** (não um arquivo solto), as duas tabelas-resumo que hoje
são montadas à mão em planilha:

- **Tabela 1 — Funil por área:** por área → `Qtd. Projetos DOR 1`, `EGPs Enviados`,
  `EGPs Analisados`, `Inputs não Modernizados` (+ linha Total).
- **Tabela 2 — Inputs por origem:** inputs DOR1 classificados em `BigQuery` / `Libname_in` /
  `Arquivo` / `Transacional` / `SAS/Local`, agrupados em **Modernizado / Não Modernizado** (+ totais).

Os números devem ser **recalculados dos dados atuais** (não transcritos do print) e **ao vivo**
(refletindo o status humano editado no app).

## 2. Decisões (do brainstorming)

| Tema | Decisão |
|---|---|
| Freshness | **Ao vivo** — `status_humano` prevalece sobre `modernizada_auto`. |
| Definição de "modernizado" | **Status efetivo** ∈ {`Disponível`, `Sanitizada`}. Origem é só dimensão de breakdown. |
| Funil (DOR1/Enviados/Analisados) | **Estático**, do `docs/analises/indi_231_vs_extracao_06.csv`. |
| Escopo | **DOR1 / Indicium**, fixo (sem seletor — o funil vem do `indi_231`, que só tem os 231 projetos DOR1; "todos" não se aplica). |
| Arquitetura | Tabela dedicada `sas_resumo_inputs` no publish (evita mexer no `sas_inputs_monitor`, que **exclui `libname_in`** e é lido pelas outras abas). |
| Aba | **"Resumo"**, primeira aba (rota `/resumo`), **read-only**. |

## 3. Definições exatas (a "spec" dos números)

**Status efetivo** (por `chave_canonica`):
`efetivo = coalesce(nullif(monitor.status_humano,''), monitor.modernizada_auto, resumo.modernizada_auto)`.
**Modernizado** = `efetivo ∈ {'Disponível','Sanitizada'}`. (Linhas `libname_in` não existem no monitor →
caem no `modernizada_auto` da própria `sas_resumo_inputs`.)

**`origem_bucket`** (por input distinto; prioridade, agregando as ocorrências do input):
1. algum `source_type` contém `BIGQUERY` → **BigQuery**
2. `categoria == 'libname_in'` → **Libname_in**
3. `categoria == 'file_in'` (arquivo) → **Arquivo**
4. algum `source_type` ∈ {`POSTGRES`,`SYBASE`,`SYBASEIQ`,`IQ`,`SQLSVR`,`DBCON`,`DBCONN`,`ASE`} → **Transacional**
5. resto (inclui `script_in`, `SAS/Local`, `Avaliar`, vazio) → **SAS/Local**

**`area_principal`** (1 área por input distinto): área mais frequente entre as ocorrências do input;
desempate alfabético. *(Regra calibrada na implementação para reproduzir os totais do print —
ver §7.)*

**Funil por área** (de `indi_231`, coluna `area` + `status_extracao`):
- `qtd_dor1` = nº de linhas da área
- `egps_enviados` = linhas com `status_extracao ≠ 'faltante'`
- `egps_analisados` = linhas com `status_extracao ∈ {'exato','variante','confirmado_area'}`

**Inputs não Modernizados (Tabela 1)** = inputs DOR1 com status efetivo ∉ {Disponível,Sanitizada},
contados por `area_principal`.

## 4. Arquitetura

### 4.1 Publish — `egps_analysis/publish_to_databricks.py` (re-publish necessário)
Em `build()`, derivar e, no `--apply`, gravar duas tabelas novas (full replace):

- **`sas_resumo_inputs`** — grão = input distinto. Universo = inputs já catalogados
  (`table_in`/`file_in`/`script_in`) **+** `libname_in` (re-incluído só para esta visão).
  Colunas: `chave_canonica STRING, area_principal STRING, origem_bucket STRING,
  escopo_indi BOOLEAN, modernizada_auto STRING`.
- **`sas_funil_area`** — grão = área. Colunas: `area STRING, qtd_dor1 INT,
  egps_enviados INT, egps_analisados INT`.

`sas_inputs_monitor` e demais tabelas: **inalteradas** (sem regressão nas outras abas).

### 4.2 Backend — `egps_analysis/app/backend/main.py`
Novo endpoint **`GET /api/resumo`** (sem parâmetro de escopo — fixo DOR1). Tabelas novas:
`T_RES = …sas_resumo_inputs`, `T_FUN = …sas_funil_area`.

- `efetivo = coalesce(nullif(i.status_humano,''), i.modernizada_auto, r.modernizada_auto)`,
  via `T_RES r LEFT JOIN T_IN i ON r.chave_canonica = i.chave_canonica`, sempre filtrando
  `r.escopo_indi = true`.
- **origem**: `GROUP BY r.origem_bucket` → `{bucket, total, modernizado, nao_modernizado}` +
  totais gerais (modernizado/não/total).
- **funil**: `T_FUN` (filtrado por escopo via join/flag) + a contagem ao vivo de não-modernizados
  por `r.area_principal`; devolve linhas por área + linha Total.
- Resposta: `{ "funil": {rows:[…], total:{…}}, "origem": {rows:[…], total:{…}} }`.

### 4.3 Frontend — `egps_analysis/app/frontend/`
- `api.ts`: `resumo()` → `GET api/resumo`.
- `types.ts`: `ResumoFunilRow`, `ResumoOrigemRow`, `ResumoPayload`.
- `components/ResumoView.tsx`: as 2 tabelas no formato do print
  (funil com linha Total; origem com blocos Modernizado/Não-Modernizado e totais). Read-only, DOR1-only.
- `App.tsx`: novo `View "resumo"`, **primeiro** item de `TABS` (`slug: "resumo"`, label `"Resumo"`),
  render `{view === "resumo" && <ResumoView cfg={cfg} />}`.
- `styles.css`: classes da aba (reuso de `.filters`/`.rd-bar` quando fizer sentido).

## 5. Fluxo de dados

```
indi_231.csv ─┐                              (publish)        (app, ao vivo)
06_prontidao ─┼─> build() ─> sas_resumo_inputs ──┐
              │             sas_funil_area ───────┼─> GET /api/resumo ─> ResumoView
sas_inputs_monitor (status_humano) ──────────────┘   (LEFT JOIN p/ status efetivo)
```

## 6. Fora de escopo (YAGNI)
- Edição inline (read-only). Gráficos. Layout mobile.
- Mudança em `sas_inputs_monitor` ou nas outras abas.
- Persistir as tabelas-resumo em CSV (só Delta + app).

## 7. Verificação
- **Calibração contra o print:** ajustar as regras de `origem_bucket` e `area_principal` até a
  *estrutura* dos números bater (BigQuery 309 / Libname_in 104 / Arquivo 780 / Transacional 91 /
  SAS-Local 1900; Inputs não Modernizados por área somando 2771). Deltas residuais explicáveis
  pelo refresh dos dados são aceitáveis e devem ser anotados.
- **Funções puras** (classificação de bucket, escolha de área) testáveis em Node/Python.
- **Build** `npm run build` verde; `publish --apply` dry-run + apply ok.
- **Manual:** aba abre na rota `/resumo`; marcar um input como Disponível no Monitoramento
  reduz "Inputs não Modernizados" ao recarregar a aba (prova do "ao vivo").
- **Revisão adversarial** do diff (publish + backend + frontend).

## 8. Custo
Toca **publish + backend + frontend**; exige **re-publish** (regravar as 2 tabelas novas) +
**redeploy** do app. Passos de operação disparados após a verificação manual (não fazem parte do plano).
