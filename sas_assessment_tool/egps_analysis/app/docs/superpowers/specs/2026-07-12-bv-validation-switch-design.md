# Switch "Com BV" + coluna "Dias em validação (BV)" — design

**Data:** 2026-07-12 · **Aba:** Gestão (variantes EGP e Input)

## Problema

Quando entregamos um projeto ao BV para validação, o BV tem um prazo de **8 dias
úteis** para dar feedback. Esse prazo é **fixo e cumulativo entre entregas**: se
entregamos e o BV leva 6 dias úteis, sobram 2 dias úteis; numa reentrega, o BV tem
só esses 2 dias restantes antes de podermos considerar o projeto migrado.

Hoje não há como rastrear de quem é a vez ("bola") nem quantos dias úteis o projeto
já passou com o BV. Precisamos de:

1. um **switch "Com BV"** por projeto (ON = bola com o BV; OFF = bola conosco);
2. uma **coluna "Dias em validação (BV)"** = total de dias úteis que o switch ficou ON.

## Convenção de contagem

- Unidade: **dias úteis** (seg–sex menos feriados BR), reusando `diasUteis` +
  `FERIADOS_BR` de `diasUteis.ts` — mesma fonte de verdade da coluna "Dias Úteis"
  existente.
- Cada intervalo ON conta como **`[entrega, retorno)`** — meia-aberta: o dia da
  entrega conta; o dia em que a bola volta pra nós **não** conta. Consequência:
  **entrega e retorno no mesmo dia = 0 dias**. Intervalos nunca contam o dia de
  fronteira duas vezes.
- Intervalo ainda aberto (atualmente ON): conta **`[entrega, hoje]`** — hoje conta,
  pois a bola ainda está com o BV.
- Sem indicação visual de "prazo esgotado" — decisão do usuário (evitar poluir a UI).
  O número na coluna é suficiente; a ação de "martelar como migrado" segue manual.

## Modelo de dados

Tabela Delta nova, **append-only** (mesmo espírito de `sas_gestao_status`):

```
sas_gestao_bv (
  id STRING,            -- uuid do evento (p/ DELETE pontual)
  entity STRING,        -- 'egp' | 'input'
  entity_id STRING,     -- projeto | chave_canonica
  com_bv BOOLEAN,       -- estado APÓS este toggle (true = com BV)
  data STRING,          -- 'YYYY-MM-DD' efetiva do toggle (default hojeSP)
  autor STRING,         -- email OBO de quem registrou
  ts STRING             -- timestamp ISO completo (auditoria / ordenação)
) USING DELTA
```

- **Estado atual** de um projeto = `com_bv` do evento mais recente (por `ts`).
- **Dias em validação** = derivado da lista de eventos (ver frontend). Não é
  materializado — é função pura do log.
- Constante `T_GBV = f"{FQ}.sas_gestao_bv"`. Criada em `_ensure_gestao_tables()`.

## Backend (`main.py`)

Autorização em dois níveis (reusa o padrão OBO/SQL sem SCIM):

- `_is_gestao()` (existe) → grupo `bv_users`. Já usado nas escritas da Gestão.
- `_is_admin()` (**novo**, espelho de `_is_gestao`) → grupo `bv_admins`, via
  `is_account_group_member('bv_admins')`. `_require_admin()` levanta 403.

Endpoints:

1. **`GET /api/gestao/rows`** — hidratar cada linha com `bvEventos: [{comBv, data}]`
   (ascendente por `ts`). Um único `SELECT ... FROM T_GBV WHERE entity = ?` agrupado
   por `entity_id` em memória, no mesmo estilo de `_gestao_extras`. Payload por
   projeto é pequeno (poucos handovers na prática).

2. **`POST /api/gestao/bv {entity, id, comBv, data?}`** — append de 1 evento.
   - `data` ausente ⇒ `hojeSP()`, permitido a **bv_users** (toggle do dia a dia).
   - `data` presente (data retroativa/explícita) ⇒ restrito a **bv_admins**
     (`_require_admin()`). É correção.
   - Auth mínima geral: `_require_gestao()`.

3. **`DELETE /api/gestao/bv {id}`** — remove 1 evento pelo `id`. Restrito a
   **bv_admins** (`_require_admin()`). Hard-delete (log operacional pequeno; a
   raridade + o gate de admin mantêm o dano ao trilho de auditoria mínimo).

O gate de admin nas correções (DELETE + POST com data) é o que limita a exposição:
o toggle comum não altera o passado; só admin reescreve histórico.

## Frontend

**`diasUteis.ts`** — novo helper puro:

```
diasEmValidacaoBV(eventos: {comBv: boolean; data: string}[], hoje: string): number
```

Percorre eventos (asc), reduz em intervalos ON, soma dias úteis meia-abertos
`[entrega, retorno)` (retorno = `data` do próximo evento OFF); intervalo aberto soma
`[entrega, hoje]` inclusivo. Precisa de um `ehDiaUtil(data)` interno (dow + feriado)
para o ajuste meia-aberto (`diasUteis` é inclusivo nas duas pontas).

**`gestaoApi.ts`** — `GestaoRow` ganha `bvEventos: {comBv: boolean; data: string}[]`.
Novos métodos no `GestaoDataSource`: `setBV(entity, id, comBv, data?)` e
`deleteBV(id)` (delta + mock). Um flag **novo e distinto** `is_admin` (NÃO o
`is_gestao`) é exposto ao front em **`/api/config`** (`AppConfig`, onde `is_gestao` já
mora) — mesmo transporte, valor próprio de `_is_admin()` (`bv_admins`) — para
condicionar a UI de correção. `is_gestao` (bv_users) segue governando o toggle comum.

**`GestaoMigracao.tsx`** (tabela, ambas variantes):
- Coluna **"Com BV"**: toggle (switch) refletindo `comBv` do último evento; clique
  faz `setBV(flip)` + invalida `["gestao", entity]`. Estilo do switch reusa/segue o
  padrão de botões do app.
- Coluna **"Dias em validação (BV)"**: `diasEmValidacaoBV(r.bvEventos, hoje)`.
  Ordenável (nova sort key `diasBV`; `comBv` também ordenável).

**`GestaoStatusPanel.tsx`** (side panel — correção, só admin):
- Seção **"Validação BV"** listando os eventos (`data · autor · Com BV/Conosco`).
- Se `is_admin`: botão de deletar por evento + controle "adicionar evento em
  [data]" (POST com `data`). Não-admin vê a lista read-only (ou nada).

## Fora de escopo (YAGNI)

- Indicação visual de prazo esgotado.
- Coluna "Responsável Validação BV" (já anotada como futura no código).
- Soft-delete/tombstone dos eventos.
- Notificações/alertas de prazo.

## Testes

- `diasEmValidacaoBV`: teste puro cobrindo — entrega+retorno mesmo dia = 0; intervalo
  com fim de semana no meio; múltiplos intervalos sem dupla contagem na fronteira;
  intervalo aberto até hoje; feriado dentro do intervalo. (frontend não tem runner
  hoje; se não houver, um bloco `demo()`/assert simples reaproveitável, sem framework.)
- Backend: o gate `_require_admin` nas correções (POST com data / DELETE) e o append
  simples do toggle. Reusar `test_priorizacao_logic.py`-style se aplicável.
