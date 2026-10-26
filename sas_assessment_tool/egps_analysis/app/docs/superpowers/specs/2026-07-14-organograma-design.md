# Organograma do time (aba "Home") — quem faz o quê

**Data:** 2026-07-14
**Escopo:** frontend + pequena extensão de backend (2 colunas em `sas_analistas`).

> Histórico: a 1ª versão era um dado **estático** no frontend. Pivotou para **data-driven** via
> `sas_analistas` (decisão do usuário) — muda o time pela aba Gestão, sem redeploy. Este doc
> descreve o desenho final (implementado).

## Problema

O BV não tinha, no painel, uma visão de **quem é o time da Indicium** e o **papel** de cada
pessoa. Existia só um PNG solto (três colunas: Gestão / Lideranças Técnicas / Desenvolvimento,
com foto + nome + cargo). O PNG não é theme-aware, nem responsivo, o texto não é selecionável e
qualquer ajuste exige reexportar a imagem.

## Objetivo

1. Renderizar o organograma **nativo** (HTML/CSS, theme-aware) na aba **Home** (ex-"Guia").
2. **Data-driven**: os membros saem de `sas_analistas` (a mesma tabela dos dropdowns de
   "Responsável", editável na aba **Gestão → Gestão de analistas**). Marcar/ajustar alguém
   reflete na hora, sem redeploy.
3. Fotos por **email** (arquivo em `assets/organograma/`), com **fallback p/ avatar de iniciais**
   quando não há arquivo. Adicionar foto = soltar o arquivo (zero código).

## Fonte de dados — `sas_analistas`

Duas colunas novas (add-once idempotente, padrão `ALTER TABLE ADD COLUMNS` já usado no projeto):

- `organograma BOOLEAN` — se a pessoa aparece na aba Home.
- `papel STRING` — cargo; **o grupo (coluna) é DERIVADO do papel** (não há campo de grupo).

Backfill único fez `organograma=true` + `papel` p/ os 13 que já estavam na tabela (por email).

### Papéis e mapeamento papel→grupo (frontend, `organograma.ts`)

Um único dropdown de **Papel** na Gestão; o grupo sai de `PAPEL_GRUPO`:

| Grupo (coluna) | Papéis |
|---|---|
| Time de Gestão | Delivery Manager, Consulting Director, Account Manager, Project Analyst |
| Lideranças Técnicas | Tech Lead, Team Lead |
| Time de Desenvolvimento | DE, AE |

Papel fora do mapa, ou `organograma=false`, ou sem papel → **fora** do organograma.
Ordem dentro do grupo: alfabética por nome (backend `ORDER BY nome`). Ordem curada não é objetivo
(adicionar coluna `ordem` só se pedirem).

## Design

### 1. Backend (`backend/main.py`)

- `_migrate_analistas_cols()` (lru_cache): adiciona `organograma`/`papel` uma vez por processo.
- `GET /api/analistas`: devolve `organograma` (coagido p/ bool) e `papel`.
- `POST /api/analistas` (upsert, `_require_gestao`): aceita `organograma`/`papel`.
  **Upsert agora é PARCIAL** (`coalesce`): campo ausente no request não é sobrescrito. Corrige
  bug latente — antes um toggle (que não manda `nome`) zerava o nome p/ o local-part do email e
  forçava `ativo=true`.

### 2. `organograma.ts` (helpers PUROS, testáveis sob node)

- `PAPEL_GRUPO`, `ORG_GRUPOS` (ordem canônica), `PAPEIS` (opções do dropdown).
- `montarOrganograma(analistas)` → `OrgGrupo[]`: filtra `organograma && papel mapeado`, agrupa,
  devolve na ordem canônica (grupos vazios saem).
- `iniciais(nome)` → 2 letras (1ª da 1ª e da última palavra; 1 palavra → 2 primeiras).
- `fotoKey(email)` → nome do arquivo: lower-case, `@`→`_at_`, `.`→`_`, sufixo `.png`
  (`guilherme.zanotelli@indicium.tech` → `guilherme_zanotelli_at_indicium_tech.png`); "" / sem @ → null.
- **Sem `import.meta.glob` aqui** (Vite-only fica no componente) p/ manter testável.

### 3. `OrganogramaSection.tsx`

- `useQuery(["analistas"])` (mesma key dos dropdowns → cache compartilhado; edição na Gestão
  invalida `["analistas"]` que casa por prefixo e atualiza os dois).
- `montarOrganograma(rows)`; se vazio, não renderiza nada.
- Card: círculo (foto via `import.meta.glob` por `fotoKey(email)`, senão iniciais) + nome + papel,
  **centralizado, avatar em cima**. Legenda `DE = Data Engineer · AE = Analytics Engineer` no
  rodapé **do grupo Desenvolvimento** (só quando há DE/AE).

### 4. Gestão de analistas (`GestaoView.tsx`)

- Form de adicionar: + dropdown **Papel** + checkbox **Organograma**.
- Tabela: colunas **Papel** (dropdown por linha) e **Organograma** (checkbox por linha),
  editáveis inline (upsert parcial preserva os demais campos).

### 5. Layout da aba Home (`GuiaView.tsx` + `styles.css`)

- Rótulo da aba `guia`: **"Guia" → "Home"** (id/path `/guia` e landing default inalterados).
- Página em **2 colunas** (`.home-grid`, ~60/40): **guia empilhado à esquerda**
  (`.home-main`: Como funciona → Conceitos → As abas → Fluxos → FAQ), **organograma à direita**.
- Organograma: 3 grupos **lado a lado** (`.org-groups`, grid de 3), divisória tracejada entre
  colunas, cards centralizados.
- `.guia` alargada de 1080 → **1400px, centrada** (`margin: 0 auto`) — some o vão horizontal.
- Colapsa p/ 1 coluna em `max-width: 900px`. Tudo em tokens de tema.

## Fora de escopo

- **Arquivos** de foto (o ramo de render existe; só os arquivos entram depois, por email).
- Campo de grupo separado (grupo é derivado do papel).
- Ordenação curada dentro do grupo (é alfabética; `ordem` só se pedirem).
- Editar o path `/guia` ou tornar "Home" a aba default.

## Curadoria de dados (não é código)

- Os nomes vêm do registro de analistas — podem diferir do PNG (ex.: "David William" vs "David
  Couto", "Joao Cunha", acentos faltando). Corrige-se inline na Gestão (campo Nome) → reflete na Home.
- Quem não está em `sas_analistas` não aparece (ex.: Alexandre Rici, João Emanuel Targino) — some
  como analista (email + nome + papel + ✓organograma). Isso também os lista nos dropdowns de
  Responsável (como Silas/Ricardo já estão).

## Verificação

- Aba **"Home"**: 2 colunas; guia à esquerda; organograma à direita com 3 grupos lado a lado,
  cards centralizados (avatar em cima), legenda DE/AE no rodapé do grupo Desenvolvimento.
- Marcar/desmarcar Organograma ou trocar Papel na Gestão reflete na Home (cache invalida).
- Toggle parcial na Gestão **não** apaga nome nem muda ativo (upsert coalesce).
- Sem arquivo de foto → iniciais; soltar `<email>.png` em `assets/organograma/` → foto (sem código).
- Tema claro/escuro OK; largura estreita → 1 coluna, sem scroll horizontal.
- `npx tsc --noEmit` limpo; `node organograma.test.mts` passa (iniciais, fotoKey, PAPEIS,
  montarOrganograma).
