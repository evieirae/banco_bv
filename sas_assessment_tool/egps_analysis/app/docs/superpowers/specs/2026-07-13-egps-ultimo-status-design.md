# Aba EGPs: coluna "Último status" (substitui "Prontidão") + painel de status

**Data:** 2026-07-13
**Escopo:** frontend apenas (sem mudança de backend).

## Problema

Na aba **EGPs** (`ReadinessView`) a última coluna é **"Prontidão"** — um selo
(`Habilitado p/ migrar` / `Quase pronto` / `Parcial` / `Bloqueado` / `Em ciclo`) derivado de
`% modernizado` + ciclo. Essa informação é **redundante**: a barra de `% modernizado`, os chips de
bucket e os ícones 🔒/⚠/⏸ da linha já comunicam prontidão.

O que falta na aba EGPs é o **"último status"** — o texto livre que os analistas registram
(`sas_gestao_status`), hoje visível só na aba **Gestão**.

## Objetivo

1. Trocar a coluna **"Prontidão"** por **"Último status"** na aba EGPs.
2. Clicar na célula abre o **mesmo painel lateral da aba Gestão** (`GestaoStatusPanel`): último
   status em destaque + histórico completo + seção "Validação BV".
3. O botão **"+ Adicionar Comentário"** passa a ser visível **só para usuários `is_gestao()`**
   (grupo `bv_users`). Os demais têm o painel em **modo leitura**.

## Por que não mexe no backend

Todos os dados já vêm de endpoints **não-gated** (qualquer usuário logado lê):

- `GET /api/gestao/rows?entity=egp` → `GestaoRow[]` com `resumoStatus` (texto do último status),
  `bvEventos`, `nome`, `area`, `etapa`. **Só EGPs `escopo_indi = true`** (Indicium).
- `GET /api/gestao/status?entity=egp&id=<projeto>` → histórico (usado pelo próprio painel).

As **escritas** continuam gated no backend: `POST /api/gestao/status` exige `_require_gestao()`.
Ou seja, "leitura para todos, escrita só gestão" já é garantido pelo servidor — o frontend só
**esconde o botão** para não oferecer uma ação que o backend recusaria.

## Design

### 1. `ReadinessView` — coluna e abertura do painel

- Buscar, além do readiness, os dados da Gestão (reusando as mesmas query keys da aba Gestão,
  então o cache é compartilhado):
  - `gestaoApi.listRows("egp")` → `["gestao", "egp"]`
  - `gestaoApi.getUsers()` → `["gestao-users"]`
- Montar `Map<projeto, GestaoRow>`.
- Cabeçalho: `Prontidão` → `Último status`.
- Célula (por linha, `gr = map.get(r.projeto)`):
  | Caso | Render | Clicável |
  |---|---|---|
  | Sem `GestaoRow` (EGP fora do escopo Indicium) | `fora de escopo` (muted) | não |
  | Tem `GestaoRow`, `resumoStatus` preenchido | texto truncado em 1 linha, `title` = texto completo | sim |
  | Tem `GestaoRow`, `resumoStatus` vazio | `sem status` (muted) | sim |
- O clique usa `stopPropagation` para **não** disparar o expand da linha (detalhe do EGP). Seta
  `panelId = r.projeto`.
- Renderiza `<GestaoStatusPanel entity="egp" row={panelRow} allRows={gestaoRows} users={users}
  onClose={...} />` quando `panelId` resolve para uma `GestaoRow` — espelhando o wiring de
  `GestaoMigracao.tsx:189` / `:360`.

**Por que a linha ainda expande no resto:** o clique na linha continua abrindo o `EgpDetailPanel`
(dependências/inputs). Só a **célula de último status** tem comportamento próprio (abre o drawer).

### 2. `GestaoStatusPanel` — gate do botão de adicionar

- Já busca `["config"]` para `is_admin`. Adicionar `isGestao = !!cfgQ.data?.is_gestao`.
- Envolver o botão `+ Adicionar Comentário` (e, por consequência, o `AddCommentModal`) em
  `{isGestao && …}`.
- **Sem regressão na aba Gestão:** lá todos os usuários são `bv_users` (`is_gestao = true`), então
  o botão continua aparecendo.
- A seção "Validação BV" (correção via `is_admin`) já é gated — inalterada.

### 3. CSS

- Truncar o texto na largura **atual** da última coluna, em 1 linha (`white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis`). **Sem alargar a coluna.**
- O CSV **não muda** (sem coluna de último status).

## Fora de escopo

- Adicionar/editar status pela aba EGPs (continua só na Gestão, via o mesmo painel).
- Resolver nome do autor fora do que o painel já faz (usa `users` que já buscamos).
- Tornar EGPs fora do escopo Indicium clicáveis (renderizam `fora de escopo`).

## Verificação

- Aba EGPs, escopo "só Indicium": coluna mostra último status; clique abre o painel; texto longo
  trunca em 1 linha com tooltip.
- Escopo "todos"/"+dependências": EGPs não-Indicium mostram `fora de escopo` e não abrem painel.
- Usuário **não**-`bv_users`: painel abre, sem o botão "+ Adicionar Comentário".
- Usuário `bv_users`: botão presente; adicionar comentário atualiza último status (invalida
  `["gestao","egp"]` e `["gestao-status","egp"]`).
- Clique na célula de status **não** expande o detalhe do EGP; clique no resto da linha expande.
- `npx tsc --noEmit` limpo.
