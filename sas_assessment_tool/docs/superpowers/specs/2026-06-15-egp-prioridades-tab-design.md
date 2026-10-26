# Design — Aba "Prioridades" (EGPs priorizados pela Indicium)

**Data:** 2026-06-15
**Componente:** `egps_analysis/app` (frontend React/TS + backend FastAPI + Delta table nova)
**Status:** aprovado para implementação

## 1. Objetivo

Adicionar uma aba **"Prioridades"** ao app "Painel de Modernização SAS" para a Indicium
**adicionar, editar, reordenar e excluir** uma lista curada de EGPs priorizados. Os dados são
**mantidos por humano** e ficam numa **tabela Delta nova**, separada das tabelas geradas pelo
pipeline — portanto **nunca sobrescritos** pelo `publish_to_databricks.py`.

## 2. Decisões (do brainstorming)

| Tema | Decisão |
|---|---|
| Identidade da entrada | **Híbrido**: escolher um EGP do universo conhecido (picker via `/api/lineage/search`) **ou** digitar texto livre (EGP ainda não nos dados). |
| Campos | `ordem` (prioridade), `projeto`, `vinculado` (bool), `status`, `responsavel`, `justificativa` + carimbos. **Sem** observação/data-alvo. |
| Reordenar | Setas **↑/↓** por linha (trocam `ordem` com o vizinho). Sem biblioteca de drag-and-drop. |
| Remover | **Hard delete** (com confirmação no front) para enganos; o status **`Descartado`** cobre "decidimos não priorizar mas manter o registro". |
| UI | **Tabela inline-editável**, no padrão das abas Monitoramento/EGPs (não formulário separado). Linha de "adicionar" no topo. |
| Auditoria | **Sem** log de auditoria dedicado (YAGNI). Carimbos `created_by/at` + `updated_by/at` na própria linha indicam autoria. |
| Permissão | Qualquer usuário com acesso ao app edita (igual ao monitor; não há gating de papéis). `updated_by` registra autoria. |
| Aba | Label **"Prioridades"**, slug `prioridades`, posicionada **depois de "EGPs"**. |
| Criação da tabela | **Lazy no backend** (`CREATE TABLE IF NOT EXISTS`); o publish não a referencia nem cria. |

## 3. Arquitetura

Feature autocontida, sem tocar no pipeline de dados:

```
React PrioridadesView ──HTTP──> FastAPI /api/prioridades* ──run_sql──> Delta sas_egp_prioridades
        │                                                                 (LEFT JOIN sas_lineage_nodes
        └── picker reusa /api/lineage/search                                p/ área/onda dos vinculados)
```

*Alternativas descartadas:* pendurar colunas no `sas_lineage_nodes`/monitor (o publish reconstrói
essas tabelas e clobraria os dados; não comporta texto livre; mistura lista curada com universo
automático) e usar uma flag tipo `escopo_indi` (não guarda ordem/status/justificativa nem itens
fora do universo). Por isso, **tabela dedicada**.

## 4. Modelo de dados — `<catalog>.<schema>.sas_egp_prioridades`

Mesmo schema das demais tabelas do app (prod: `client_journey.monitoramento_sas`; dev default:
`bv_dev_db.dev_lucas_muller`), resolvido por `PUBLISH_CATALOG`/`PUBLISH_SCHEMA`.

| coluna | tipo | papel |
|---|---|---|
| `id` | STRING | UUID (gerado no backend) — chave estável p/ editar/excluir/mover |
| `ordem` | INT | posição; define o sort ascendente; setas ↑/↓ trocam com o vizinho |
| `projeto` | STRING | nome do EGP (do picker ou texto livre) |
| `vinculado` | BOOLEAN | `true` = casa com `sas_lineage_nodes.projeto` (puxa área/onda); `false` = texto livre |
| `status` | STRING | um de `A fazer` / `Em andamento` / `Concluído` / `Descartado` |
| `responsavel` | STRING | texto livre, nullable |
| `justificativa` | STRING | por que foi priorizado, nullable |
| `created_by` | STRING | `current_user()` na criação |
| `created_at` | TIMESTAMP | `current_timestamp()` na criação |
| `updated_by` | STRING | `current_user()` na última edição |
| `updated_at` | TIMESTAMP | `current_timestamp()` na última edição |

DDL (executado lazy):
```sql
CREATE TABLE IF NOT EXISTS <FQ>.sas_egp_prioridades (
  id STRING, ordem INT, projeto STRING, vinculado BOOLEAN,
  status STRING, responsavel STRING, justificativa STRING,
  created_by STRING, created_at TIMESTAMP, updated_by STRING, updated_at TIMESTAMP
) USING DELTA;
```

Derivados (área/onda) **não** são armazenados; vêm de `LEFT JOIN sas_lineage_nodes nd ON nd.projeto = p.projeto`
na leitura, somente p/ linhas `vinculado=true`. Se um EGP vinculado sumiu da linhagem, área/onda vêm `NULL`
(o front mostra "—").

## 5. Backend — endpoints (em `backend/main.py`, declarados antes do mount estático)

Constantes: `T_PRIO = f"{FQ}.sas_egp_prioridades"`, `STATUS_PRIO = ["A fazer", "Em andamento", "Concluído", "Descartado"]`.

Helper `_ensure_prio_table()` roda o `CREATE TABLE IF NOT EXISTS` (idempotente) e é chamado no início
de cada endpoint de prioridades.

| Método/rota | Comportamento |
|---|---|
| `GET /api/prioridades` | Garante a tabela; retorna linhas `ORDER BY ordem ASC, created_at ASC`, com `area`/`onda` via LEFT JOIN p/ vinculados. `{ "rows": [...] }`. |
| `POST /api/prioridades` | Body: `projeto` (obrigatório, não-vazio), `vinculado` (bool), `status` (default `A fazer`), `responsavel?`, `justificativa?`. Valida `status ∈ STATUS_PRIO`. `ordem = COALESCE(MAX(ordem),0)+1`. Gera `id` (uuid4). Carimba created/updated. Retorna a linha criada. |
| `PATCH /api/prioridades/{id}` | Atualiza só os campos enviados (`projeto`/`vinculado`/`status`/`responsavel`/`justificativa`). Valida `status` se enviado. Carimba `updated_by/at`. 404 se `id` inexistente. Retorna a linha. |
| `POST /api/prioridades/{id}/move` | Body `{ "dir": "up"|"down" }`. Acha o vizinho imediato (menor `ordem` > atual p/ baixo; maior `ordem` < atual p/ cima) e **troca os valores de `ordem`** entre as duas linhas (2 UPDATEs). No-op se já é a ponta. Retorna `{ "ok": true }`. |
| `DELETE /api/prioridades/{id}` | Apaga a linha (`DELETE FROM ... WHERE id = ...`). 404 se inexistente. Retorna `{ "ok": true }`. Buracos em `ordem` são tolerados (sort por `ordem` continua válido). |

Erros via `HTTPException` (400 validação, 404 não-encontrado, 502 falha SQL), como nos endpoints atuais.
Concorrência: last-write-wins, igual ao `PATCH /api/inputs` atual; a janela de corrida no `move` (2 UPDATEs)
é aceitável p/ uma lista curta e de baixo tráfego.

**Funções puras isoláveis** (testáveis sem Databricks, devem ser extraídas):
- `valid_status(s) -> bool` (pertence a `STATUS_PRIO`).
- `next_ordem(max_ordem: int | None) -> int` (→ `(max_ordem or 0) + 1`).
- `neighbor_swap(rows, id, dir) -> (id_a, ordem_a, id_b, ordem_b) | None` — dada a lista ordenada de
  `{id, ordem}`, devolve o par a trocar (ou `None` se for a ponta). Mantém o SQL fino e a lógica testável.

## 6. Frontend

- **`src/components/PrioridadesView.tsx`** (novo): tabela inline-editável reusando os tokens/classes
  de tema já existentes.
  - Cabeçalho/linhas: `#` (nº + setas ↑/↓) · **EGP** (nome; se vinculado, mostra `área · onda`, senão tag "livre")
    · **Status** (`<select>`) · **Responsável** (`<input>`) · **Justificativa** (`<input>`) · **ações** (🗑).
  - Edição inline com salvamento on-blur/on-change → `PATCH`; refetch da lista após cada mutação.
  - **Linha de adicionar** no topo: campo de busca de EGP (debounced, chama `/api/lineage/search`) com
    dropdown de resultados; opção "usar '<texto>' como EGP livre" quando não há match; selects/inputs de
    status/resp/justificativa; botão **Adicionar** (`POST`). `vinculado` = `true` se escolhido do dropdown.
  - Excluir pede `confirm()` antes do `DELETE`.
  - Estado vazio: mensagem `.empty` ("Nenhum EGP priorizado ainda").
- **`src/api.ts`**: objeto `prioridades` com `list()`, `create(body)`, `update(id, patch)`,
  `move(id, dir)`, `remove(id)`.
- **`src/types.ts`**: tipo `Prioridade` (campos da tabela + `area?`/`onda?` derivados) e `StatusPrio`.
- **`src/App.tsx`**: incluir `"prioridades"` em `View`, item em `TABS` (`{ id:"prioridades",
  label:"Prioridades", slug:"prioridades" }`) **após "EGPs"**, e `{view === "prioridades" && <PrioridadesView />}`.
- **`src/styles.css`**: classes p/ a linha de adicionar e os botões de seta, reusando os tokens
  (`var(--accent)`, `var(--line)`, etc.). Sem novas cores hardcoded.

## 7. Erros & estados

- Falha de rede/SQL → banner `.error` no topo da view (padrão já usado nas outras abas).
- Validação de status no backend (400) e no front (select restrito a `STATUS_PRIO`).
- `projeto` vazio → bloqueado no front (botão Adicionar desabilitado) e no backend (400).
- Picker sem resultados → permite texto livre (`vinculado=false`).

## 8. Testes

- **pytest** (backend, sem Databricks) p/ as funções puras: `valid_status`, `next_ordem`, `neighbor_swap`
  (incluindo casos de ponta: subir o 1º / descer o último → no-op).
- **Frontend**: se houver lógica pura no picker (ex. filtro/destaque de match), testar em Node como
  os testes existentes (`theme.test.mts`); caso contrário, sem teste de UI.
- **Manual** no app publicado: adicionar (vinculado e livre), editar cada campo, reordenar ↑/↓ nas
  pontas e no meio, excluir com confirmação, recarregar e conferir persistência; conferir no tema claro.

## 9. Segurança do publish

`publish_to_databricks.py` **não** referencia `sas_egp_prioridades` e **não** deve passar a referenciar.
A criação é lazy no backend; nenhum passo de publish cria/recria/MERGE nessa tabela. Verificar (grep) que
o nome não aparece no script antes de finalizar.

## 10. Fora de escopo (YAGNI)

Log de auditoria dedicado; gating por papel/usuário; data-alvo/prazo; observação livre separada da
justificativa; renumerar `ordem` p/ fechar buracos; drag-and-drop; deep-link por item.

## 11. Custo

Frontend (1 componente + fios em api/types/App + CSS) + backend (5 endpoints + helpers + DDL lazy).
Sem mudança no pipeline de dados. Rebuild + redeploy do Databricks App ao final (gate humano).
