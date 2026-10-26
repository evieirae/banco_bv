# Design — Aba EGPs como master-detail (lista + detalhe)

**Data:** 2026-06-15
**Componente:** `egps_analysis/app` (frontend React/TS + FastAPI)
**Status:** aprovado para implementação

## 1. Problema

A aba **EGPs** hoje é só um **detalhe de um EGP por vez**: o usuário escolhe um item num
dropdown de 229 EGPs e vê `Depende de` / `Alimenta` + a tabela de inputs editável. Não há
visão geral — não dá pra escanear, filtrar ou ordenar os EGPs pelas suas dependências. A
maior parte da tela fica no estado vazio "Selecione um EGP…".

O objetivo é transformar a aba numa **lista filtrável/ordenável de todos os EGPs (master)**,
no estilo da aba Monitoramento, com o **detalhe ao lado** ao clicar numa linha.

## 2. Decisões (resolvidas no brainstorming)

| Tema | Decisão | Motivo |
|---|---|---|
| Layout | **Split lado a lado**: master ~360px (esquerda) + detalhe `flex:1` (direita) | Mantém a lista sempre visível pra pular entre EGPs |
| Dados da lista | Reusar **`/api/egp-readiness`** (sem backend novo) | No escopo Indicium é idêntico ao dropdown (229 = 229); só "todos" perde 21 EGPs sem inputs |
| Dependência na lista | Só **"depende de" (upstream)** + breakdown `i`/`e` + flag de ciclo | Upstream é o que importa pra ordem de migração; "alimenta" já aparece no detalhe |
| `% modernizado` | **Incluir** mini-barra na lista | Vem de graça do `egp-readiness`; contexto útil |
| Ordenação | Default **`Depende de` desc**, com **headers clicáveis** (troca coluna + asc/desc) | Acha os EGPs mais "presos"; usuário pode reordenar |
| Detalhe | Reusar **`/api/egp`** (depende de · alimenta · inputs editáveis) | Já existe e funciona |
| Seleção | Deep-link via query param **`/egps?egp=<projeto>`** | Compartilhável; query não quebra os assets relativos (`base: "./"`), ao contrário de um segmento de path |

### Verificação de dados (warehouse `client_journey.monitoramento_sas`)

| Fonte | Indicium | Todos |
|---|---|---|
| `sas_lineage_nodes` (dropdown atual) | 229 | 1205 |
| `sas_egp_inputs` (base do `egp-readiness`) | 229 | 1184 |

No escopo Indicium (default) batem exatamente. Em "todos", 21 EGPs sem inputs catalogados
não aparecem — aceitável para uma lista focada em inputs/dependência.

## 3. Arquitetura de componentes

Refatorar `EgpView.tsx` em duas unidades com responsabilidades isoladas:

### `EgpView.tsx` (container + master)
- **Estado:** `scopeIndi`, `area`, `q` (busca), `sort` (chave) + `asc` (direção), chips ativos,
  `selected` (projeto | null).
- **Dados:** `api.egpReadiness(scope)` → `ReadinessRow[]`.
- **Derivações (client-side, memo):** lista de áreas, contagens dos chips, `view` (filtrada + ordenada).
- **Render:** barra de filtros + chips + tabela master (esquerda) + `<EgpDetailPanel projeto={selected} cfg={cfg} />` (direita).
- **Seleção/URL:** clique numa linha → `setSelected(projeto)` + atualiza `?egp=`; lê `?egp=` no mount;
  ouve `popstate`.

### `EgpDetailPanel.tsx` (novo — painel direito)
- **Props:** `projeto: string | null`, `cfg: AppConfig | null`.
- **Estado:** `det` (`EgpDetail`), `busy`, `err`.
- **Dados:** `api.egp(projeto)` quando `projeto` muda.
- **Render:** bloco de detalhe atual (header + aviso de ciclo + `Depende de`/`Alimenta` +
  tabela de inputs com edição inline via `api.patch`). Estado vazio quando `projeto == null`.
- Extraído do bloco `det && (...)` do `EgpView` atual.

> Nenhuma mudança no backend nem em `api.ts` (todos os endpoints já existem:
> `egpReadiness`, `egp`, `patch`).

## 4. Master — lista de EGPs

**Colunas** (cada linha = um `ReadinessRow`):

| Coluna | Origem | Render |
|---|---|---|
| EGP | `projeto` | `shortName(projeto)` + `◆` se Indicium; linha selecionada destacada |
| Área | `area` | texto |
| Onda | `onda` | `waveTag()` (ex. `O3`, `⟳`) |
| Inputs | `n_inputs` | número |
| % modernizado | `pct` | mini-barra (`rd-bar`/`rd-fill`) + `pct%` |
| Faltam | `n_faltam` | número (vazio se 0) |
| Depende de | `n_deps`, `n_deps_indi`, `n_deps_ext`, `ciclo_id` | total + badges `Ni`/`Me` + `⟳` se em ciclo (não-expansível; o clique abre o detalhe) |

**Filtros:** select de escopo (`indi`/`todos`), select de área, busca por nome. Contador
"N de M EGPs".

**Chips de dependência** (toggle, client-side):
- `⟳ em ciclo` → `ciclo_id > 0`
- `depende de externo` → `n_deps_ext > 0`
- `folhas` → `n_deps == 0`

**Ordenação:** headers clicáveis (`projeto`, `area`, `n_inputs`, `pct`, `n_faltam`, `n_deps`).
Default `n_deps` desc. Clicar no header ativo inverte a direção; em outro header, ordena
desc nele. (Mesmo padrão do `ReadinessView`.)

## 5. Detalhe — painel direito

- Reusa o detalhe atual: cabeçalho (área/onda/ciclo/Indicium, n_inputs/n_outputs), aviso de
  dependência cíclica, painéis **Depende de** e **Alimenta**, e tabela de **inputs** com edição
  inline de `status_humano` / `responsavel` / `observacao` (otimista + `PATCH`, com rollback no erro).
- **Aperto da tabela:** `.egp-detail` rola em x/y; a tabela de inputs recebe `min-width` para
  não esmagar colunas no painel de ~62%.
- `projeto == null` → "Selecione um EGP para ver seus inputs e dependências."

## 6. URL / estado

- A rota da aba continua `/egps` (resolvida pelo `slugFromPath`, que ignora a query string).
- EGP selecionado vira `?egp=<projeto>`:
  - clique: `const url = new URL(location.href); url.searchParams.set("egp", projeto); history.pushState(null, "", url)`.
  - mount: `new URLSearchParams(location.search).get("egp")` inicializa `selected`.
  - `popstate`: re-lê o param.
- Deep-link com escopo diferente: o detalhe carrega o `projeto` da URL mesmo que ele não esteja
  na lista filtrada atual (o destaque na lista só aparece se presente).

## 7. CSS / layout

- `.egpview` → coluna flex; abaixo dos filtros, `.egp-split { display:flex; gap:16px; flex:1; min-height:0 }`.
- `.egp-master { flex:0 0 360px; overflow:auto }`; `.egp-detail { flex:1; min-width:0; overflow:auto }`.
- Tabela master: classes próprias (`.em-*`) espelhando o visual do `.rd-table` para consistência,
  sem acoplar a `ReadinessView`.

## 8. Fora de escopo (YAGNI)

- Grafo de dependências (já existe na aba Linhagem).
- Coluna "alimenta" na lista (exigiria agregação downstream no backend).
- Layout responsivo/mobile.
- Qualquer mudança no backend ou em `egp-readiness`/`egp`.

## 9. Verificação

- **Funções puras** (filtro/ordenação/bucket de chips) testáveis em Node, como no roteamento.
- **Build:** `npm run build` verde (tsc estrito).
- **Manual:** deep-link `?egp=`; troca de ordenação (coluna + direção); chips; destaque da seleção;
  edição de input persiste e reflete no detalhe.
- **Revisão adversarial** do diff antes de concluir.
