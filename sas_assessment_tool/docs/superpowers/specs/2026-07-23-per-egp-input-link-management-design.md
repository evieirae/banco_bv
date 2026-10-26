# Spec — Per-EGP Input Link Management

**Data:** 2026-07-23
**App:** `egps_analysis/app` (Painel de Modernização SAS — FastAPI + React, Databricks App OBO)
**Status:** aguardando revisão do usuário

## 1. Problema

Hoje o estado humano de um input (`status_humano` em `sas_inputs_monitor`) é **global**:
um input tem um único status compartilhado por todos os EGPs que o consomem. Para um
input ser "Sanitizado" na prática — sair das contagens de pendência — a sanitização
precisa valer para **todos** os consumidores.

Isso quebra quando o negócio declara, para um EGP específico, que ele **não depende**
de um input particular (ex.: `EGP_A` não usa mais `Input_1`), mas o mesmo `Input_1`
ainda alimenta `EGP_B` (sobre o qual não temos autoridade). Não podemos:

- Marcar `Input_1` como `Sanitizado` globalmente (`EGP_B` continua precisando).
- Deixar `Input_1` contando como pendência de `EGP_A` (o negócio já resolveu).

Precisamos de um estado **per-(EGP, Input)** que declare "este vínculo está quebrado" —
equivalente a `Sanitizado` apenas para aquele EGP.

## 2. Decisões (respostas do usuário na sessão de brainstorming)

| Ponto | Decisão |
|---|---|
| Propagação | Aplicar no nível dos **predicados SQL** — todo lugar que faz `T_EGP × T_IN` com `_modern`/`_sanitizado` passa a considerar o vínculo. Cobre: EGPs tab, drawer, EGP detail, Priorização, Waves, Landing/Resumo/Funis "+dependências", Blocking (🔒). |
| Permissão de escrita | Apenas gestão (`bv_users`). Mesma regra do 📌 pin de mês na Priorização. |
| Campo de motivo | Nenhum. Toggle simples chain⇄broken. |
| Badge para não-gestão (EGP detail) | Visível, não-clicável. |
| Filtro "Vínculos quebrados" na aba EGPs | Visível para todos os usuários logados. |
| Ícones | Emoji: `🔗` (linked) e `⛓️‍💥` (broken). Renderização é aceitável no VSCode e Slack; validar em browser (Chrome/Firefox no Databricks App) antes do merge. **Fallback**: se a fonte do app renderizar `⛓️‍💥` de forma pobre (ex.: two-glyph fallback), trocar por `components/LinkIcon.tsx` inline SVG (elo + elo quebrado com sparks, matching imagens de referência). Definido durante o PR do front (§5.1). |
| Ordenação em EGP detail | Inputs com vínculo quebrado descem para o fim da lista, renderizados esmaecidos (mesmo tratamento visual de `Sanitizado`). |
| Header de contagem em EGP detail | `Inputs / necessidades (N-X)` — mostra apenas o número de inputs **linkados**. |
| CSV de Inputs (grain EGP × Input) | **Não exporta** linhas com vínculo quebrado. Filtro server-side em `/api/inputs-egps`. |
| CSV de EGPs | Ganha coluna `Vínculos quebrados` (contagem). |
| Áudito | Nova tabela `sas_egp_input_link_audit` seguindo o padrão real do app (uma tabela por fonte, `/api/audit` faz UNION com label `fonte`). Novo `fonte='Vínculos'`. |
| Publish/refresh | Novas tabelas são `CREATE IF NOT EXISTS` e **não são tocadas** pelo publish. Órfãos (link_broken apontando para (projeto, chave) que não existe mais em `sas_egp_inputs`) são inofensivos. |
| `sync_dev.py` | Atualizado para copiar as duas tabelas novas. |
| EGPs com todos os inputs linkados-quebrados | Continuam aparecendo na aba EGPs com `n_inputs=0`, `pct=100`. Mesmo tratamento de EGPs com todos os inputs Sanitizados (documentado em `main.py:2128-2131`). |
| Prioridade caches | Todo write bumpa `_lineage_gen` (padrão já usado por `patch_input` em `main.py:1083`). Invalida `_cache_lineage` e `_cache_scope_dataset`. |

## 3. Modelo de dados

Duas tabelas novas em `bv_dev_db.monitoramento_sas` (e `..._dev` em dev):

### 3.1 `sas_egp_input_link` — estado

```sql
CREATE TABLE IF NOT EXISTS sas_egp_input_link (
    projeto         STRING NOT NULL,
    chave_canonica  STRING NOT NULL,
    link_broken     BOOLEAN NOT NULL,
    updated_by      STRING,
    updated_at      TIMESTAMP
) USING DELTA;
```

- **Grain**: `(projeto, chave_canonica)`.
- **Semântica**: linha ausente ≡ `link_broken=false` (linkado). Só existem linhas para
  vínculos quebrados. Tabela minúscula (esperado <100 linhas).
- **Escrita**: UPSERT (`MERGE` ou `DELETE`+`INSERT`) via OBO — `current_user()` captura
  o ator humano (não SP).
- **Nunca é tocada pelo publish** (padrão de `sas_output_producer_choice`,
  `sas_escopo`, `sas_egp_pipeline`).

### 3.2 `sas_egp_input_link_audit` — histórico

```sql
CREATE TABLE IF NOT EXISTS sas_egp_input_link_audit (
    id              STRING,       -- uuid
    projeto         STRING,
    chave_canonica  STRING,
    campo           STRING,       -- sempre 'link_broken' hoje (extensível)
    valor_antigo    STRING,       -- 'true' | 'false' | NULL
    valor_novo      STRING,
    ator            STRING,       -- current_user()
    ts              TIMESTAMP
) USING DELTA;
```

- Espelha a forma de `sas_pipeline_audit` (que tem `projeto` como entidade) —
  o modelo mais próximo dentro do app.
- Cada escrita em `sas_egp_input_link` insere uma linha aqui (via OBO,
  `current_user()`).

### 3.3 DDL bootstrap

Novo helper em `main.py`:

```python
@functools.lru_cache(maxsize=1)
def _ensure_link_tables() -> None:
    run_sql(f"CREATE TABLE IF NOT EXISTS {T_LINK} (…) USING DELTA")
    run_sql(f"CREATE TABLE IF NOT EXISTS {T_LINK_AUD} (…) USING DELTA")
```

Chamado no startup do backend e antes de qualquer read/write das duas tabelas
(mesmo padrão de `_ensure_pipe_table`, `_ensure_gestao_tables`).

### 3.4 Constantes de tabela

Adicionar em `main.py:54-77` **e** em `pipeline/publish_to_databricks.py:795-807`
(dois pontos, seguindo a nota do onboarding sobre duplicação):

```python
T_LINK     = f"{CAT_SCHEMA}.sas_egp_input_link"
T_LINK_AUD = f"{CAT_SCHEMA}.sas_egp_input_link_audit"
```

`publish_to_databricks.py` só declara os nomes — **não** cria as tabelas nem
mexe nelas. O bootstrap é no backend.

## 4. Backend

### 4.1 Predicados — overlay de vínculo

Estender os helpers em `main.py:84-114`:

```python
def _sanitizado(sh, auto, lnk="false"):
    return f"({_eff_status(sh, auto)} = 'Sanitizado' OR {lnk})"

def _modern(sh, auto, lnk="false"):
    return f"({_eff_status(sh, auto)} IN ('Modernizado','Sanitizado') OR {lnk})"

def _aingerir(sh, auto, lnk="false"):
    return f"NOT {_modern(sh, auto, lnk)}"
```

- `lnk` é uma expressão SQL avaliada a `BOOLEAN`. Default `"false"` = comportamento antigo.
- Callers que fazem `T_EGP e LEFT JOIN T_IN i` passam a fazer também
  `LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica`
  e passam `lnk="coalesce(l.link_broken, false)"` ao predicado.

### 4.2 Endpoints afetados (adicionar o JOIN + `lnk`)

| Local | Papel |
|---|---|
| `main.py:1948-1953` `/api/egp` | Lista de inputs do EGP detail. Adiciona `l.link_broken` no SELECT (front usa). |
| `main.py:2132-2140` `_egp_readiness_rows` | `n_inputs`, `n_disp`, `pct` da aba EGPs. |
| `main.py:2214-2217` `_sem_fonte_by_proj` | Contagem "Sem fonte" por EGP. |
| `main.py:2234-2241` `_readiness_inputs_header` | Card "Inputs distintos". |
| `main.py:2331-2342` `/api/waves` | Contagens de ondas. |
| `main.py:2443-2445` `_compute_priorizacao` | `n_inputs_novos` marginal por EGP. |
| `main.py:1863-1870` `_blocking` | Leaf-blockers per EGP (afeta 🔒). |
| `main.py:1101-1126` landing "+deps" | Universo de chaves da frontier. |
| `main.py:2866-2972` `/api/resumo` "+deps" | Idem. |

Deixado propositalmente **fora** (globais / não fazem `T_EGP × T_IN`):

- `main.py:633-665` `/api/metrics` (métrica global de inputs).
- `main.py:1137-1240` funil de Ingestão (agrega `T_IN` globalmente).
- `main.py:1614-1623` `_vias_resolvidas` (lineage global — quebrar vínculo em
  um EGP não deve "resolver" o upstream compartilhado).

### 4.3 Novo contador `n_links_broken` no readiness

`_egp_readiness_rows` (`main.py:2121-2200`) recebe, além do `n_inputs`/`n_disp`
recomputados via predicado, uma nova métrica:

```sql
count(CASE WHEN coalesce(l.link_broken, false) THEN 1 END) AS n_links_broken
```

Retornado em `ReadinessRow` para pintar o badge/contagem na aba EGPs.

### 4.4 Endpoint PATCH

```
PATCH /api/egp-input-link
Body: {projeto: str, chave_canonica: str, link_broken: bool}
Auth: _require_bv_users (403 se não for gestão)
```

Fluxo:

1. `_ensure_link_tables()`.
2. `run_sql` (OBO) — `MERGE` para UPSERT em `T_LINK`. Se `link_broken=false`,
   preferir `DELETE` (mantém a tabela enxuta e o "estado ausente ≡ linkado").
3. `run_sql` INSERT em `T_LINK_AUD` com `ator=current_user()`,
   `ts=current_timestamp()`, `valor_antigo` obtido do SELECT prévio.
4. `_lineage_gen += 1` (invalida `_cache_lineage` e `_cache_scope_dataset`).
5. Retorna `{ok: True, projeto, chave_canonica, link_broken}`.

### 4.5 Filtro server-side no CSV de Inputs

`/api/inputs-egps` (`main.py:909-922`) já retorna o cross-product `[(chave, projeto)]`.
Ganha:

```sql
LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica
WHERE NOT coalesce(l.link_broken, false)
```

Com isso o CSV do MonitorView (`MonitorView.tsx:285-319`) já sai limpo — não
precisa lógica extra no front.

### 4.6 União de auditoria

`/api/audit` (`main.py:2787-2863`) ganha um 4º bloco `_safe(...)`. O shape
existente das linhas de auditoria (herdado de `sas_pipeline_audit`) é:
`{id, projeto/artefato, campo, valor_antigo, valor_novo, updated_by, updated_at, fonte}`.
Sem coluna livre para `chave_canonica` — codificar dentro de `campo` como
`link_broken@<chave_canonica>` (mesma técnica que o `funil` de `sas_pipeline_audit`
distingue `migracao` vs. outros):

```python
_safe(f"""
  SELECT id,
         projeto AS artefato,
         concat('link_broken@', chave_canonica) AS campo,
         valor_antigo, valor_novo,
         ator AS updated_by, ts AS updated_at,
         'Vínculos' AS fonte
  FROM {T_LINK_AUD}
""")
```

Frontend `HistoryView.tsx` estende `CAMPO_LABEL` para reconhecer o prefixo
`link_broken@` e renderizar `"Vínculo (EGP↔Input): <chave>"`.

## 5. Frontend

### 5.1 Glyph de vínculo

Emoji direto no JSX:

- Linkado → `🔗`
- Quebrado → `⛓️‍💥`

Consistente com o padrão da app (`🔒 ⚠ ⏸ ⚡ ⟳` — todos emoji inline).
Wrap num `<span title="…">` para tooltip; sem componente novo.

**Validação obrigatória antes do merge**: abrir no browser (Chrome + Firefox
no Databricks App, tema claro e escuro) e checar se `⛓️‍💥` renderiza como
um glyph único e legível. Se render for pobre (dois emojis separados, ou
tamanho incoerente com o resto da UI), cair para o fallback SVG abaixo.

**Fallback (só se a validação falhar)**: novo
`frontend/src/components/LinkIcon.tsx`:

```tsx
type Props = { broken?: boolean; size?: number; title?: string };
export function LinkIcon({ broken, size = 16, title }: Props) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24"
         fill="none" stroke="currentColor" strokeWidth={1.8}
         strokeLinecap="round" strokeLinejoin="round" aria-label={title}>
      {broken ? (
        // path do elo quebrado + 5 sparks (image #1)
      ) : (
        // path do elo intacto (image #2)
      )}
    </svg>
  );
}
```

### 5.2 `EgpDetailPanel.tsx` — tabela de inputs

- **Nova coluna** ao final: `Vínculo`. Header (linha 267) recebe `<th>Vínculo</th>`.
- **Célula** (dentro do map em 269-317):
  ```tsx
  <td className="rd-vinc">
    {isBv ? (
      <button className="rd-vinc-btn" onClick={() => toggleLink(i)}
              title={i.link_broken
                ? "Vínculo quebrado — não conta para modernização deste EGP (clique para restaurar)"
                : "Vínculo ativo — clique para quebrar"}>
        {i.link_broken ? "⛓️‍💥" : "🔗"}
      </button>
    ) : (
      <span title={i.link_broken ? "Vínculo quebrado" : "Vínculo ativo"}>
        {i.link_broken ? "⛓️‍💥" : "🔗"}
      </span>
    )}
  </td>
  ```
- **Ordenação**: sort key primário: `i.link_broken` (broken depois de linked).
  Sort secundário mantém a ordem atual (por status/artefato).
- **Renderização esmaecida** para broken: reusar CSS de linha sanitizada (classe
  `rd-row-sanit` ou equivalente já existente).
- **Header counter** (linhas 162-173): `Inputs / necessidades: <b>{n_linkados}</b>`
  onde `n_linkados = n_inputs - n_links_broken`. Sem tooltip complicado — a
  informação "X quebrados" aparece no badge da aba EGPs.
- **Cache invalidation** do `patchMut` de link (linhas 106-125) inclui:
  `["egp","egp-readiness","funis","priorizacao","metrics","resumo","landing","waves"]`.

### 5.3 `ReadinessView.tsx` — aba EGPs

- **Backend supply**: `ReadinessRow` (types.ts:264-289) ganha
  `n_links_broken?: number`.
- **Badge** ao lado do nome do EGP (linhas 352-354, ordem: `🔒 ⚠ ⏸ ⛓️‍💥N`):
  ```tsx
  {r.n_links_broken > 0 && (
    <span className="rd-badge rd-vinc" title="Vínculos quebrados com inputs">
      ⛓️‍💥 {r.n_links_broken}
    </span>
  )}
  ```
- **Filter chip** na barra de filtros (linhas 301-318): novo toggle
  `Vínculos quebrados`, com contador `brokenCount = rows.filter(r => (r.n_links_broken ?? 0) > 0).length`.
  Estado boolean `brokenOnly`, mesmo padrão de `blockedOnly`/`despOnly`/`convOnly`.
- **CSV export** (linhas 225-249): nova coluna `"Vínculos quebrados"` com
  `r.n_links_broken ?? 0`.

### 5.4 Drawers

- **`InputDrawer.tsx:61-72`** ("Usado por N EGPs"):
  - Backend `/api/input-detail` (`main.py:882-906`) LEFT JOIN em `T_LINK`; cada
    item da lista `egps` retorna `link_broken?: boolean`.
  - Título do bloco vira `Usado por {N - broken} EGPs (+ {broken} com vínculo quebrado)`
    se `broken > 0`; senão só `Usado por {N} EGPs`.
  - EGPs com `link_broken=true` continuam listados, renderizados esmaecidos,
    com `⛓️‍💥` ao lado do nome.
- **`OutputsDrawer.tsx:116-129`** — mesmo tratamento no lado dos consumidores.

### 5.5 Aba Histórico

- **`HistoryView.tsx`**:
  - Novo case no lookup de `campo`: prefixo `link_broken@` → label
    `"Vínculo (EGP↔Input): <chave>"` (parsa a chave do sufixo).
  - `fonteCls['Vínculos'] = 'fonte-vinc'` (nova classe CSS).
  - `valor_antigo` / `valor_novo` renderizam como "Linkado" / "Quebrado".

### 5.6 `api.ts` / `types.ts`

- **`types.ts`**:
  - `EgpInput` (162-175): adicionar `link_broken?: boolean`.
  - `ReadinessRow` (264-289): adicionar `n_links_broken?: number`.
  - `InputUsageEgp` (77-83): adicionar `link_broken?: boolean`.
- **`api.ts`**: nova função `setEgpInputLink(projeto, chave_canonica, link_broken)`
  seguindo o padrão de `setOutputProducer` (linhas 166-173):
  ```ts
  setEgpInputLink: (projeto: string, chave: string, broken: boolean) =>
    patch<{ ok: true }>('/api/egp-input-link',
      { projeto, chave_canonica: chave, link_broken: broken }),
  ```

### 5.7 Prefetch

`prefetch.ts` — nenhuma mudança necessária. Os queries afetados já são
prefetched via `["egp-readiness", scope]` e `["egp", projeto]`.

## 6. Segurança / permissão

- `PATCH /api/egp-input-link` gated por `_require_bv_users` (padrão de rotas de
  gestão como Priorização pin).
- Front esconde interatividade para não-gestão (`isBv` já existe em
  `EgpDetailPanel.tsx`). Ícone segue visível.
- Auditoria captura `current_user()` via OBO — não é bypassável via SP.

## 7. Rollout

### 7.1 Sequência

1. **PR 1 — Backend puro**: constantes, `_ensure_link_tables`, predicados
   estendidos, endpoint `PATCH`, JOIN em todas as queries listadas em §4.2,
   união em `/api/audit`. `n_links_broken` em `_egp_readiness_rows`. Testes.
2. **PR 2 — Frontend**: emoji `🔗`/`⛓️‍💥` inline nos JSX; alterações em
   `EgpDetailPanel`, `ReadinessView`, drawers, `HistoryView`, `api.ts`, `types.ts`.
   Validação visual antes do merge; fallback `LinkIcon.tsx` inline SVG apenas
   se necessário.
3. **PR 3 — sync_dev**: entrada para as duas tabelas novas em `sync_dev.py`
   (só copia; DDL é do backend). Pode ir junto com o PR 1 se preferir.

Deploy prod = merge para `main` (Bitbucket Pipelines). Antes do primeiro deploy
prod, rodar `_ensure_link_tables()` manualmente (ou aceitar que rode no
primeiro startup via `lru_cache`).

### 7.2 `sync_dev.py`

Acrescentar `sas_egp_input_link` e `sas_egp_input_link_audit` na lista de
tabelas copiadas. Como as tabelas em prod começam vazias, a primeira sincronização
apenas cria as tabelas em dev.

### 7.3 Rollback

- Remover o endpoint e reverter o JOIN faz o app voltar ao comportamento antigo.
- As duas tabelas ficam ociosas — nunca dropar (histórico preservado).

## 8. Testes

### 8.1 Backend (`backend/test_*.py`)

- **`test_link_predicates.py`** (novo):
  - Predicado com `lnk="false"` = comportamento antigo.
  - Predicado com `lnk="true"` força sanitizado.
  - `_egp_readiness_rows` com 1 input broken: `n_inputs` cai 1, `n_disp` intocado,
    `pct` sobe.
- **`test_egp_input_link_endpoint.py`** (novo):
  - PATCH sem `X-Forwarded-Access-Token` → 401.
  - PATCH com usuário fora de `bv_users` → 403.
  - PATCH `link_broken=true` cria linha + audit; `false` remove linha + audit.
  - `_lineage_gen` incrementa após cada write.

### 8.2 Cenários manuais (documentados no PR)

- Quebrar vínculo em `EGP_A / Input_1` compartilhado com `EGP_B`:
  - EGPs tab: `EGP_A` mostra badge `⛓️‍💥 1`, `pct` recalcula, `n_faltam` cai.
  - EGPs tab: `EGP_B` não muda.
  - Aba Inputs: `Input_1` continua listado, status global inalterado.
  - InputDrawer de `Input_1`: `EGP_A` aparece com badge, count discounta.
  - Prioridade: `EGP_A.n_inputs_novos` cai.
  - Blocking: se `Input_1` era SAS/local sem produtor e era o único blocker
    de `EGP_A`, `EGP_A` sai de 🔒.
  - Histórico: linha nova com fonte `Vínculos`, campo `Vínculo (EGP↔Input)`,
    valores `false → true`.
- Restaurar vínculo → reverso completo.

## 9. YAGNI — deliberadamente fora do escopo

- **Bulk "quebrar todos os vínculos deste EGP"** — reversal é 1 clique, não vale
  UI extra.
- **Campo de motivo** — user disse não.
- **Job de limpeza de órfãos** — inofensivos; se o input voltar, o estado
  volta (comportamento desejável).
- **Ingestão funnel + inputs por origem** — globais, sem conceito per-EGP.
- **`_vias_resolvidas`** — lineage global, não altera.
- **Novo status enum** — `Sanitizado` continua sendo estado global; vínculo
  quebrado é um overlay, não um status.
- **Filtro de "quebrado" no drawer de outputs** — informacional apenas.

## 10. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Predicado ganha argumento novo em todos os callers. Um caller que esqueça de passar `lnk` vira bug silencioso (nada acontece; broken link não aplica). | Default `"false"` é seguro (mesmo comportamento antigo). PR checklist inclui grep por `_modern(`/`_sanitizado(`/`_aingerir(` conferindo que todos os que fazem `LEFT JOIN T_LINK` estão passando `lnk`. Teste unitário cobre o predicado. |
| `_lineage_gen` esquecido no PATCH → caches de 5 min desatualizados. | Teste que verifica `_lineage_gen += 1` na resposta do PATCH. |
| MERGE / DELETE de `sas_egp_input_link` fora de sequência com o audit → auditoria desalinhada. | Ambos executam em `run_sql` OBO na mesma request; falha do audit não desfaz o state mas o cache do estado é bumpado só se o state gravou. Documentar. |
| Duplicação de constantes (main.py + publish_to_databricks.py). | O onboarding já cita o padrão — apenas nome, sem DDL na pipeline. Grep no PR. |
| Emoji `⛓️‍💥` renderiza como dois glyphs separados na fonte do browser do Databricks App. | Checar visualmente em Chrome + Firefox (light + dark) via `./local_app.sh` antes de merge; se render for pobre, cair para o SVG inline documentado em §5.1. |

## 11. Referências

- Onboarding do app: `egps_analysis/app/frontend/ONBOARDING.md`.
- Guia de uso: `egps_analysis/app/GUIA_DO_APP.md`.
- Classificação de inputs: `egps_analysis/docs/CLASSIFICACAO_INPUTS_SAS.md`.
- Padrão de tabelas persistentes: `sas_output_producer_choice` (`main.py:1011`),
  `sas_escopo`, `sas_egp_pipeline`.
- Padrão de union de auditoria: `main.py:2787-2863`.
