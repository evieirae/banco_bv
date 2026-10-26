# Sub-área BV — visualizar EGPs pela área interna do responsável do cliente

Data: 2026-09-15. Status: design aprovado, pendente plano de implementação.

## Problema

O app já sabe **quem** do BV responde por cada EGP (`sas_egp_pipeline.responsavel_bv`,
texto livre, editável na aba EGPs e no drawer) e já filtra por essa pessoa em EGPs,
Acompanhamento e Gestão. O que não existe é o nível **acima** da pessoa: a área interna
do BV a que ela pertence (Digital, Operações, MIS, Estratégia - cartões, Estratégia -
rodas, Riscos). Sem isso não dá para responder "como está a migração da Estratégia -
rodas?" nem cobrar a liderança certa.

O nome "área" já está tomado no app inteiro pela **área de negócio** do EGP (Cobrança,
Riscos, Jurídico…). O conceito novo chama-se **Sub-área BV**.

## Conceito

**Sub-área BV é atributo da PESSOA, não do EGP.**

- EGP herda a sub-área do seu `responsavel_bv`.
- Input (nos kanbans de Acompanhamento/Gestão) herda as sub-áreas dos EGPs que o
  consomem, via `respBvOf()` (`GestaoKanban.tsx`) — logo é **multi-valorado**: um input
  lido por EGPs de duas sub-áreas aparece nas duas.
- EGP sem responsável, ou com responsável fora do cadastro, cai no bucket visível
  **"Sem sub-área"**. Ele nunca é escondido: esse bucket é o sinal de "falta cadastrar".

Consequência desejada: cadastrar uma pessoa uma vez reclassifica todos os EGPs dela.
Não existe edição de sub-área por EGP (seria trabalho manual em ~200 linhas e divergiria
do responsável).

## Estado medido em prod (`bv_dev_db.monitoramento_sas.sas_egp_pipeline`, 2026-09-15)

194 EGPs com `responsavel_bv` preenchido, 12 grafias distintas:

| responsavel_bv | EGPs | sub-área |
|---|---:|---|
| Leticia Domingos Duarte | 61 | Estratégia - rodas |
| Joao Carneiro | 34 | Estratégia - cartões |
| Cleber William De Jesus Saure | 33 | MIS |
| Rafael Vasconcelos Ribeiro | 26 | Digital |
| Cristiano | 11 | MIS |
| Igor Brito_Riscos | 7 | Riscos |
| Adamor Luz | 6 | Digital |
| Carolina Matos | 5 | Operações |
| Daniel Vitor | 4 | Operações |
| Não localizado | 4 | — |
| Leticia | 2 | Estratégia - rodas |
| cynthia | 1 | Operações |

Duas sujeiras de grafia que o cadastro sozinho não resolve (chaves distintas para a mesma
pessoa) e que o usuário autorizou corrigir em prod:

1. `Leticia` (2 EGPs) → `Leticia Domingos Duarte`.
2. `Igor Brito_Riscos` (7 EGPs) → `Igor Brito`, sub-área `Riscos`.

## Componentes

### 1. Cadastro `sas_responsaveis_bv` (backend)

Tabela Delta nova, **fora do publish** — como `sas_analistas`/`sas_gestao_status`, nunca
dropada no republish (`publish_to_databricks.py` não a conhece).

| coluna | papel |
|---|---|
| `nome_key` | chave: nome normalizado (trim + lower + sem acento + espaços colapsados) |
| `nome` | grafia de exibição |
| `subarea` | texto livre (datalist das já cadastradas → sub-área nova sem deploy) |
| `ativo` | desativa a pessoa (saiu do BV): os EGPs dela passam a exibir "Sem sub-área", e o nome some dos dropdowns. Não preserva a classificação — para isso, apague só a sub-área |
| `created_by/at`, `updated_by/at` | auditoria, igual `sas_analistas` |

Endpoints espelhando os de analistas (`main.py`):

- `GET /api/responsaveis-bv?incluir_inativos=` — leitura **aberta** (o filtro precisa
  funcionar para qualquer usuário, não só bv_users).
- `POST /api/responsaveis-bv` — upsert parcial por `nome_key` (campo ausente não
  sobrescreve, mesmo padrão do `analistas_upsert`), `_require_gestao()`. Desativar alguém é
  este mesmo upsert com `ativo=false`, então não há endpoint DELETE.

Criação idempotente via `_ensure_*_table()`, como as demais.

### 2. Resolução `src/subareas.ts` (frontend)

Só helpers **puros** (sem Vite/rede), testáveis sob node como `organograma.ts`:

- `normNome(s)` — mesma normalização do backend. Contrato **frágil e verificado**: `\s` e
  `trim()`/`strip()` divergem entre JS e Python em BOM (U+FEFF), NEL (U+0085) e separadores
  de registro (U+001C-1F), e `\p{M}` ≠ `combining() != 0`. As três cópias (backend, frontend,
  seed) listam a classe de invisíveis à mão e filtram marca por categoria; há teste dos dois
  lados e fuzz diferencial de 4k casos
- `mapaSubarea(rows)` → `Map<nome normalizado, sub-área>` (só o que a resolução precisa)
- `subareaDe(responsavel_bv, mapa)` → `string | null`
- `SEM_SUBAREA = "Sem sub-área"`
- `subareasDe(responsaveis[], mapa)` → `string[]` (caso multi-valorado dos inputs)

Mais `useSubareas()` (hook fino: `useQuery(["responsaveis-bv"])`), cache compartilhado
entre abas e incluído em `prefetchAllTabs`.

Testes em `frontend/subareas.test.mts` (node runner, padrão de `organograma.test.mts`):
normalização com acento/caixa/espaço duplo, nome fora do cadastro → `null`, responsável
vazio → `null`, multi-valorado deduplicado.

### 3. Superfícies

| Onde | O quê |
|---|---|
| **EGPs** (`ReadinessView`) | chips clicáveis no topo (contagem por sub-área, clique liga/desliga o filtro) + `MultiSelect` "Sub-área BV" ao lado de "Responsável BV" + coluna nova na tabela + coluna no export CSV |
| **Acompanhamento** (`AcompanhamentoView`) | chips + `MultiSelect`; vale para kanban de EGP **e** de input (via `respBvOf`) |
| **Gestão** (`GestaoMigracao`, `GestaoStatusPanel`) | mesmo `MultiSelect` + coluna no painel de status |
| **Drawer do EGP** (`EgpDetailPanel`) | sub-área exibida ao lado do Responsável BV — derivada, read-only |
| **Gestão** (`GestaoView`) | CRUD "Responsáveis BV" (nome + sub-área + ativo), no mesmo formato do "Gestão de analistas" |
| **Resumo** (fim da aba) | tabela `Sub-área BV · EGPs · Migrados · Bloqueados · Inputs faltando · % pronto` + linha Total; clique na linha cross-navega para EGPs já filtrado |

O filtro é multi-select e **soma** com os filtros existentes (área, responsável, mês,
etapa, status), como qualquer outro filtro das abas.

### 4. Entrada de dados

`RespBvInput` passa de `<input>` livre para `<input list="…">` com datalist do cadastro:
guia para a grafia cadastrada sem quebrar o texto livre já gravado nem exigir cadastro
prévio para atribuir alguém novo.

Seed do cadastro (11 pessoas): as 9 da planilha do usuário, `Igor Brito` (Riscos) e
`Não localizado` (sub-área vazia — aparece como "Sem sub-área").

## Fonte dos números do Resumo

A tabela agregada é calculada **no cliente** a partir de `/api/readiness`, que já é
prefetchado e traz tudo que ela precisa (`etapa`, `status`, `bloqueado_dep`, `n_faltam`,
`pct`, `responsavel_bv`). Zero endpoint novo e zero query extra no warehouse.

Definição de cada coluna:

- **EGPs**: linhas do recorte corrente do readiness (`indi_deps`).
- **Migrados**: `status === "Migrado"`. **Migrado é status, não etapa** — mesma leitura da
  aba Priorização (`WavesView`). O funil no topo desta mesma página usa um terceiro corte
  (status terminal, somando os despriorizados, "por pedido" em `main.py`), então esta coluna
  bate com a Priorização, não com o headline do funil acima dela. Ler a etapa aqui, como o
  desenho original propunha, daria um **terceiro** número de "migrados" na mesma tela.
- **Bloqueados**: `bloqueado_dep === true`.
- **Inputs faltando**: soma de `n_faltam`.
- **% pronto**: média de `pct` ponderada por `n_inputs`, com **peso mínimo 1** — EGP sem
  input nenhum tem `pct = 100` no backend (não há o que ingerir); com peso 0 ele sumiria da
  média e uma sub-área composta só desses mostraria 0% com todos prontos.

## Escrita em prod autorizada

Patch pontual em `sas_egp_pipeline` (9 linhas, autorizado explicitamente pelo usuário em
2026-09-15), rodado antes do seed do cadastro:

```sql
UPDATE … SET responsavel_bv = 'Leticia Domingos Duarte' WHERE trim(responsavel_bv) = 'Leticia';
UPDATE … SET responsavel_bv = 'Igor Brito'              WHERE trim(responsavel_bv) = 'Igor Brito_Riscos';
```

Não é destrutivo (só normaliza grafia) e é idempotente. Validar com o `GROUP BY` antes e
depois. O republish **não** reverte: `sas_egp_pipeline` é `CREATE IF NOT EXISTS` e o MERGE
preserva colunas humanas.

## Fora de escopo (YAGNI)

- Sub-área editável por EGP (divergiria do responsável).
- Hierarquia de sub-áreas / organograma do BV com fotos.
- Sub-área em Inputs como campo próprio — lá ela é sempre derivada dos EGPs consumidores.
- Histórico/auditoria de mudança de sub-área de uma pessoa.
