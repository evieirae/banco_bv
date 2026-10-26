# Sub-área BV — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ver e filtrar os EGPs pela área interna do BV a que o responsável do cliente pertence (Digital, Operações, MIS, Estratégia - cartões/rodas, Riscos), em toda superfície que já mostra "Responsável BV", mais uma tabela agregada no fim do Resumo.

**Architecture:** A sub-área é atributo da PESSOA, guardado num cadastro novo (`sas_responsaveis_bv`, editável na Gestão); o EGP a herda do seu `responsavel_bv` (texto livre) via uma chave de nome normalizada. Toda a resolução acontece no cliente, em helpers puros (`src/subareas.ts`), sobre dados que o app já busca — nenhuma query nova no warehouse além do cadastro (tabela de ~11 linhas).

**Tech Stack:** FastAPI + Databricks SQL (OBO) no backend; React 18 + TypeScript + Vite + React Query no frontend; testes backend com pytest (sem warehouse) e frontend com `.test.mts` standalone rodados por `node` (Node 24 faz type-stripping nativo).

**Spec:** [`../specs/2026-09-15-subarea-bv-design.md`](../specs/2026-09-15-subarea-bv-design.md)

---

## Convenções deste repositório (leia antes de começar)

- **Nunca commitar/pushar sem pedido explícito do usuário.** Os passos "Commit" abaixo só rodam se o usuário autorizar; na dúvida, pare e pergunte.
- **Nunca rodar deploy** (`deploy_dev.sh`/`deploy_prod.sh`) sem consentimento explícito.
- Acentuação importa: strings de status/etapa são comparadas com as do backend e dos dados (`"Concluído"`, `"Em ingestão"`). Não normalize acentos em constantes de funil.
- Comentários do código são em **português**, explicando o *porquê* (padrão do repo).
- Rodar o app local: skill `running-app-locally`. Frontend em `egps_analysis/app/frontend`, backend em `egps_analysis/app/backend`.
- SQL em prod: use `egps_analysis/venv/bin/python` (tem `databricks-sdk`), profile `bv`, warehouse `5922c26f81f1bbdd`, catálogo `bv_dev_db`, schema `monitoramento_sas`.

## File Structure

**Backend**
- Modify `egps_analysis/app/backend/main.py` — `import unicodedata`, `T_RESPBV`, `_norm_nome_bv()`, `_ensure_responsaveis_bv_table()`, 2 endpoints `/api/responsaveis-bv` (GET + upsert; não há DELETE — desativar é `ativo=false` pelo próprio upsert). Responsabilidade: persistir e servir o cadastro. Fica junto do CRUD de analistas (mesma seção "Gestão"), que é o padrão que ele espelha.
- Create `egps_analysis/app/backend/test_subarea_bv.py` — testes da normalização de nome (puros, sem warehouse).

**Frontend — núcleo novo (arquivos pequenos e focados)**
- Create `egps_analysis/app/frontend/src/subareas.ts` — helpers **puros** de resolução nome→sub-área. Sem React, sem rede: é o que o teste sob `node` importa.
- Create `egps_analysis/app/frontend/src/useSubareas.ts` — hook fino (React Query) que busca o cadastro e devolve o mapa pronto. Separado de `subareas.ts` de propósito: o teste não pode importar React.
- Create `egps_analysis/app/frontend/subareas.test.mts` — testes dos helpers puros.

**Frontend — pontos de integração**
- Modify `src/types.ts` — `ResponsavelBv`, `ResponsaveisBvPayload`.
- Modify `src/api.ts` — 3 chamadas do cadastro.
- Modify `src/prefetch.ts` — aquecer `["responsaveis-bv"]`.
- Modify `src/tabState.ts` — `setTabState()` (escrever no store de fora de um componente, p/ o cross-nav do Resumo).
- Modify `src/components/RespBvInput.tsx` — datalist com os nomes cadastrados.
- Modify `src/components/ReadinessView.tsx` — chips + MultiSelect + coluna + CSV.
- Modify `src/components/AcompanhamentoView.tsx` — chips + MultiSelect.
- Modify `src/components/GestaoMigracao.tsx` — MultiSelect.
- Modify `src/components/GestaoStatusPanel.tsx` — linha "Sub-área BV" (2 lugares: EGP e input).
- Modify `src/components/EgpDetailPanel.tsx` — sub-área ao lado do Responsável BV.
- Modify `src/components/GestaoView.tsx` — CRUD "Responsáveis BV".
- Modify `src/components/ResumoView.tsx` — tabela agregada no fim + cross-nav.
- Modify `src/App.tsx` — passar `onNav` ao ResumoView.
- Modify `src/styles.css` — largura da grid da tabela de EGPs (coluna nova) + estilos do CRUD.

**Docs**
- Modify `egps_analysis/app/README.md` — seção "Decisões de design".
- Modify `CONTEXT.md` — termo "Sub-área BV" no glossário.

---

## Task 1: Normalizar as grafias de `responsavel_bv` em prod

Duas pessoas estão gravadas com duas grafias diferentes, o que as separaria em buckets distintos. O usuário autorizou explicitamente a correção em 2026-09-15. É uma escrita em **produção**, então mede-se antes e depois.

**Files:**
- Create: `egps_analysis/scripts/normaliza_responsavel_bv.py`

- [ ] **Step 1: Escrever o script (idempotente, com antes/depois)**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normaliza grafias divergentes de sas_egp_pipeline.responsavel_bv (2026-09-15).

Duas pessoas estavam gravadas com duas grafias, o que as separaria em duas
"sub-áreas" distintas no app: "Leticia" (2 EGPs) é a mesma pessoa que
"Leticia Domingos Duarte" (61), e "Igor Brito_Riscos" (7) carregava a área
no próprio nome. Idempotente: rodar de novo não muda nada.

    python egps_analysis/scripts/normaliza_responsavel_bv.py            # só mostra
    python egps_analysis/scripts/normaliza_responsavel_bv.py --apply    # grava
"""
import argparse

from databricks.sdk import WorkspaceClient

TABELA = "bv_dev_db.monitoramento_sas.sas_egp_pipeline"
WAREHOUSE = "5922c26f81f1bbdd"

# (grafia errada, grafia canônica)
RENOMES = [
    ("Leticia", "Leticia Domingos Duarte"),
    ("Igor Brito_Riscos", "Igor Brito"),
]


def consulta(w, sql):
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=WAREHOUSE, wait_timeout="50s")
    return r.result.data_array or []


def distribuicao(w):
    return consulta(w, f"""SELECT responsavel_bv, count(*) AS n FROM {TABELA}
        WHERE responsavel_bv IS NOT NULL AND trim(responsavel_bv) <> ''
        GROUP BY 1 ORDER BY 2 DESC""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="grava (sem isso, só mostra)")
    ap.add_argument("--profile", default="bv")
    args = ap.parse_args()

    w = WorkspaceClient(profile=args.profile)

    print("ANTES:")
    for nome, n in distribuicao(w):
        print(f"  {n:>4}  {nome}")

    for errado, certo in RENOMES:
        sql = (f"UPDATE {TABELA} SET responsavel_bv = '{certo}' "
               f"WHERE trim(responsavel_bv) = '{errado}'")
        if args.apply:
            consulta(w, sql)
            print(f"aplicado: {errado!r} -> {certo!r}")
        else:
            print(f"[dry-run] {sql}")

    if args.apply:
        print("DEPOIS:")
        for nome, n in distribuicao(w):
            print(f"  {n:>4}  {nome}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Rodar em dry-run e conferir a distribuição**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool && egps_analysis/venv/bin/python egps_analysis/scripts/normaliza_responsavel_bv.py`

Expected: bloco "ANTES" com 12 grafias, entre elas `Leticia` (2) e `Igor Brito_Riscos` (7); dois `[dry-run] UPDATE …`; nada gravado.

- [ ] **Step 3: Aplicar**

Run: `egps_analysis/venv/bin/python egps_analysis/scripts/normaliza_responsavel_bv.py --apply`

Expected: bloco "DEPOIS" com **11** grafias (a de Leticia funde numa existente, a de Igor vira um nome novo); `Leticia` e `Igor Brito_Riscos` sumiram; `Leticia Domingos Duarte` passou de 61 para **63**; `Igor Brito` aparece com **7**. A soma total (194) não muda.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/scripts/normaliza_responsavel_bv.py
git commit -m "chore(app): normaliza grafias divergentes de responsavel_bv"
```

---

## Task 2: Backend — cadastro `sas_responsaveis_bv`

A chave do cadastro é o nome normalizado, porque `responsavel_bv` é texto livre digitado à mão: "joao carneiro" e "Joao  Carneiro" têm que casar com a mesma pessoa.

**Files:**
- Modify: `egps_analysis/app/backend/main.py`
- Test: `egps_analysis/app/backend/test_subarea_bv.py`

- [ ] **Step 1: Escrever o teste que falha**

Create `egps_analysis/app/backend/test_subarea_bv.py`:

```python
# -*- coding: utf-8 -*-
"""Testes da chave canônica do Responsável BV. Não bate no warehouse."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.main import _norm_nome_bv  # noqa: E402


def test_caixa_e_espacos_nao_separam_a_pessoa():
    assert _norm_nome_bv("  Joao  Carneiro ") == _norm_nome_bv("joao carneiro")


def test_acento_nao_separa_a_pessoa():
    # o BV digita ora com ora sem acento; é a mesma pessoa
    assert _norm_nome_bv("Letícia Domingos Duarte") == _norm_nome_bv("Leticia Domingos Duarte")


def test_nomes_diferentes_nao_colidem():
    assert _norm_nome_bv("Cristiano") != _norm_nome_bv("Cristiane")


def test_vazio_e_none_viram_string_vazia():
    assert _norm_nome_bv(None) == ""
    assert _norm_nome_bv("   ") == ""
```

- [ ] **Step 2: Rodar o teste e verificar que falha**

Run: `cd egps_analysis/app && venv/bin/python -m pytest backend/test_subarea_bv.py -v`
Expected: FAIL — `ImportError: cannot import name '_norm_nome_bv'`

- [ ] **Step 3: Implementar a normalização**

Em `egps_analysis/app/backend/main.py`, adicionar `import unicodedata` ao bloco de imports da stdlib (após `import uuid`, linha ~26):

```python
import unicodedata
```

Adicionar a constante junto das outras `T_*` (após `T_ANALISTAS`, linha ~69):

```python
T_RESPBV = f"{FQ}.sas_responsaveis_bv"   # Responsável BV -> sub-área (nunca dropada pelo publish)
```

Adicionar a função logo antes de `_ensure_analistas_table` (linha ~574):

```python
def _norm_nome_bv(nome):
    """Chave canônica do Responsável BV. `sas_egp_pipeline.responsavel_bv` é texto livre
    digitado à mão, então caixa/acento/espaço duplo NÃO podem separar a mesma pessoa em
    duas sub-áreas. Regra replicada em frontend/src/subareas.ts (normNome) — mudou aqui,
    muda lá."""
    s = unicodedata.normalize("NFKD", (nome or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)
```

- [ ] **Step 4: Rodar o teste e verificar que passa**

Run: `cd egps_analysis/app && venv/bin/python -m pytest backend/test_subarea_bv.py -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Implementar a tabela e os endpoints**

Em `main.py`, logo após `_ensure_analistas_table()` (linha ~579), adicionar:

```python
def _ensure_responsaveis_bv_table():
    """Cadastro Responsável BV -> sub-área interna do cliente (Digital, MIS, Operações,
    Estratégia - cartões/rodas, Riscos). Fora do publish, como sas_analistas: o republish
    nunca a droparia, mas deixamos explícito porque ela guarda dado 100% humano."""
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_RESPBV} (nome_key STRING, nome STRING,
  subarea STRING, ativo BOOLEAN, created_by STRING, created_at STRING,
  updated_by STRING, updated_at STRING) USING DELTA""", want_rows=False)
    return True


@app.get("/api/responsaveis-bv")
def responsaveis_bv_list(incluir_inativos: bool = False):
    """Cadastro de Responsáveis BV (fonte da sub-área em TODAS as abas e do datalist do
    campo Responsável BV). Leitura ABERTA de propósito: o filtro por sub-área precisa
    funcionar para qualquer usuário, não só para o grupo de gestão."""
    _ensure_responsaveis_bv_table()
    where = "" if incluir_inativos else "WHERE ativo IS NOT false"
    rows = run_sql(f"SELECT nome_key, nome, subarea, ativo FROM {T_RESPBV} {where} "
                   f"ORDER BY subarea, nome")
    return {"rows": rows, "is_gestao": _is_gestao()}


class ResponsavelBv(BaseModel):
    nome: str
    subarea: str | None = None
    ativo: bool | None = None


@app.post("/api/responsaveis-bv")
def responsaveis_bv_upsert(r: ResponsavelBv):
    """Cria/edita por nome_key. Upsert PARCIAL (coalesce): um toggle de ativo não apaga a
    sub-área. Restrito a bv_users."""
    _require_gestao()
    _ensure_responsaveis_bv_table()
    nome = (r.nome or "").strip()
    key = _norm_nome_bv(nome)
    if not key:
        raise HTTPException(400, "nome obrigatório")
    sub_upd = "NULL" if r.subarea is None else sql_lit(r.subarea.strip())
    sub_ins = "NULL" if r.subarea is None else sql_lit(r.subarea.strip())
    ativo_upd = "NULL" if r.ativo is None else str(bool(r.ativo)).lower()
    ativo_ins = "true" if r.ativo is None else str(bool(r.ativo)).lower()
    run_sql(
        f"MERGE INTO {T_RESPBV} t USING (SELECT {sql_lit(key)} AS nome_key) s "
        f"ON t.nome_key = s.nome_key "
        f"WHEN MATCHED THEN UPDATE SET t.nome = {sql_lit(nome)}, "
        f"t.subarea = coalesce({sub_upd}, t.subarea), "
        f"t.ativo = coalesce({ativo_upd}, t.ativo), "
        f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (nome_key, nome, subarea, ativo, created_by, created_at, "
        f"updated_by, updated_at) VALUES ({sql_lit(key)}, {sql_lit(nome)}, {sub_ins}, {ativo_ins}, "
        f"current_user(), cast(current_timestamp() AS STRING), current_user(), "
        f"cast(current_timestamp() AS STRING))",
        want_rows=False)
    return {"ok": True, "nome_key": key, "nome": nome}
```

- [ ] **Step 6: Verificar que o módulo importa e a suíte segue verde**

Run: `cd egps_analysis/app && venv/bin/python -m pytest backend/ -q`
Expected: todos passam (inclusive os 4 novos); nenhum erro de import/sintaxe.

- [ ] **Step 7: Commit**

```bash
git add egps_analysis/app/backend/main.py egps_analysis/app/backend/test_subarea_bv.py
git commit -m "feat(app): cadastro Responsavel BV -> sub-area (tabela + endpoints)"
```

---

## Task 3: Frontend — helpers puros `subareas.ts`

Todo o resto do plano depende destes helpers. Eles não conhecem React nem rede: é por isso que dá para testá-los com `node` direto, sem bundler (mesmo padrão de `src/organograma.ts` + `organograma.test.mts`).

**Files:**
- Create: `egps_analysis/app/frontend/src/subareas.ts`
- Test: `egps_analysis/app/frontend/subareas.test.mts`

- [ ] **Step 1: Escrever o teste que falha**

Create `egps_analysis/app/frontend/subareas.test.mts`:

```ts
import assert from "node:assert/strict";
import { normNome, mapaSubarea, subareaDe, subareasDe, ordenarSubareas, SEM_SUBAREA } from "./src/subareas.ts";

let pass = 0;
function check(name: string, fn: () => void) { fn(); pass++; console.log("ok -", name); }

const CADASTRO = [
  { nome: "Joao Carneiro", subarea: "Estratégia - cartões" },
  { nome: "Letícia Domingos Duarte", subarea: "Estratégia - rodas" },
  { nome: "Cristiano", subarea: "MIS" },
  { nome: "Não localizado", subarea: "" },   // cadastrado SEM sub-área
];

check("normNome: caixa, espaço duplo e acento não separam a pessoa", () => {
  assert.equal(normNome("  Joao  Carneiro "), normNome("joao carneiro"));
  assert.equal(normNome("Letícia Domingos Duarte"), normNome("Leticia Domingos Duarte"));
});
check("normNome: vazio/null → string vazia", () => {
  assert.equal(normNome(null), "");
  assert.equal(normNome("   "), "");
});
check("subareaDe: resolve pelo nome normalizado", () => {
  const m = mapaSubarea(CADASTRO);
  assert.equal(subareaDe("joao  CARNEIRO", m), "Estratégia - cartões");
  assert.equal(subareaDe("Leticia Domingos Duarte", m), "Estratégia - rodas");
});
check("subareaDe: fora do cadastro, vazio ou sem sub-área → null", () => {
  const m = mapaSubarea(CADASTRO);
  assert.equal(subareaDe("Fulano Novo", m), null);
  assert.equal(subareaDe("", m), null);
  assert.equal(subareaDe(null, m), null);
  assert.equal(subareaDe("Não localizado", m), null);  // cadastrado, mas sem sub-área
});
check("subareasDe: multi-valorado, deduplicado, sem sub-área vira bucket", () => {
  const m = mapaSubarea(CADASTRO);
  assert.deepEqual(subareasDe(["Cristiano", "Cristiano"], m), ["MIS"]);
  assert.deepEqual(subareasDe([], m), [SEM_SUBAREA]);
  assert.deepEqual(subareasDe(["Fulano Novo"], m), [SEM_SUBAREA]);
  assert.deepEqual(new Set(subareasDe(["Cristiano", "Fulano"], m)), new Set(["MIS", SEM_SUBAREA]));
});
check("ordenarSubareas: alfabética pt-BR com 'Sem sub-área' por último", () => {
  assert.deepEqual(
    ordenarSubareas([SEM_SUBAREA, "MIS", "Operações", "Digital", "MIS"]),
    ["Digital", "MIS", "Operações", SEM_SUBAREA]);
});
console.log(`\n${pass} testes OK`);
```

- [ ] **Step 2: Rodar o teste e verificar que falha**

Run: `cd egps_analysis/app/frontend && node subareas.test.mts`
Expected: FAIL — `Cannot find module './src/subareas.ts'`

- [ ] **Step 3: Implementar os helpers**

Create `egps_analysis/app/frontend/src/subareas.ts`:

```ts
// Sub-área BV: a área INTERNA do cliente (Digital, MIS, Operações, Estratégia - cartões,
// Estratégia - rodas, Riscos) a que pertence o Responsável BV de um EGP. Não confundir com
// "Área" (Cobrança/Riscos/Jurídico), que é a área de NEGÓCIO do EGP e já existe no app.
//
// A sub-área é atributo da PESSOA (cadastro sas_responsaveis_bv, editado na Gestão); o EGP
// a herda do seu responsavel_bv. Aqui ficam só helpers PUROS (sem React/rede) p/ serem
// testáveis sob node; o fetch do cadastro vive em useSubareas.ts.

export interface ResponsavelBvLike { nome: string; subarea?: string | null }

export type MapaSubarea = Map<string, string>;   // nome normalizado -> sub-área

// Bucket de quem não tem sub-área resolvida (sem responsável, responsável fora do cadastro
// ou cadastrado sem sub-área). NUNCA some das listas: é justamente o sinal de "falta
// cadastrar alguém" — esconder viraria EGP invisível.
export const SEM_SUBAREA = "Sem sub-área";

// Chave canônica do nome. `sas_egp_pipeline.responsavel_bv` é texto livre digitado à mão,
// então caixa/acento/espaço duplo não podem separar a mesma pessoa. Espelha _norm_nome_bv
// em backend/main.py — mudou lá, muda aqui.
export function normNome(nome: string | null | undefined): string {
  return (nome ?? "")
    .trim()
    .toLowerCase()
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .replace(/\s+/g, " ");
}

export function mapaSubarea(rows: ResponsavelBvLike[]): MapaSubarea {
  const m: MapaSubarea = new Map();
  for (const r of rows) {
    const sub = (r.subarea ?? "").trim();
    if (!sub) continue;              // cadastrado sem sub-área -> cai em SEM_SUBAREA
    m.set(normNome(r.nome), sub);
  }
  return m;
}

export function subareaDe(resp: string | null | undefined, mapa: MapaSubarea): string | null {
  const k = normNome(resp);
  return k ? mapa.get(k) ?? null : null;
}

// Versão multi-valorada: um input herda a sub-área dos EGPs que o consomem, que podem ser
// de sub-áreas diferentes (ver respBvOf em GestaoKanban.tsx). Lista vazia ou nomes sem
// sub-área devolvem [SEM_SUBAREA], nunca [] — senão a linha sumiria de toda contagem.
export function subareasDe(resps: (string | null | undefined)[], mapa: MapaSubarea): string[] {
  const out = new Set<string>();
  for (const r of resps) out.add(subareaDe(r, mapa) ?? SEM_SUBAREA);
  if (out.size === 0) out.add(SEM_SUBAREA);
  return [...out];
}

// Ordem canônica de opções e chips: alfabética pt-BR com SEM_SUBAREA sempre por último.
// Ordem ESTÁVEL de propósito (não por contagem): chip que pula de lugar quando o filtro
// muda é impossível de clicar duas vezes seguidas.
export function ordenarSubareas(subs: Iterable<string>): string[] {
  return [...new Set(subs)].sort((a, b) => {
    if (a === SEM_SUBAREA) return 1;
    if (b === SEM_SUBAREA) return -1;
    return a.localeCompare(b, "pt-BR");
  });
}
```

- [ ] **Step 4: Rodar o teste e verificar que passa**

Run: `cd egps_analysis/app/frontend && node subareas.test.mts`
Expected: PASS — `6 testes OK`

- [ ] **Step 5: Commit**

```bash
git add egps_analysis/app/frontend/src/subareas.ts egps_analysis/app/frontend/subareas.test.mts
git commit -m "feat(app): helpers puros de resolucao nome -> sub-area BV"
```

---

## Task 4: Frontend — tipos, API, hook e prefetch

**Files:**
- Modify: `egps_analysis/app/frontend/src/types.ts`
- Modify: `egps_analysis/app/frontend/src/api.ts`
- Create: `egps_analysis/app/frontend/src/useSubareas.ts`
- Modify: `egps_analysis/app/frontend/src/prefetch.ts`

- [ ] **Step 1: Adicionar os tipos**

Em `src/types.ts`, logo após `AnalistasPayload` (linha ~117):

```ts
// Cadastro Responsável BV -> sub-área interna do cliente (tabela sas_responsaveis_bv,
// editada na aba Gestão). `ativo` vem como string em algumas respostas do SQL, igual Analista.
export interface ResponsavelBv {
  nome_key: string;
  nome: string;
  subarea?: string | null;
  ativo: boolean | string;
}

export interface ResponsaveisBvPayload {
  rows: ResponsavelBv[];
  is_gestao: boolean;
}
```

- [ ] **Step 2: Adicionar as chamadas de API**

Em `src/api.ts`, logo após `analistasSyncGrupo` (linha ~103), e acrescentando `ResponsaveisBvPayload` ao import de tipos do arquivo:

```ts
  responsaveisBv: (incluirInativos = false) =>
    fetch(`api/responsaveis-bv${incluirInativos ? "?incluir_inativos=true" : ""}`).then(json<ResponsaveisBvPayload>),
  responsavelBvUpsert: (body: { nome: string; subarea?: string; ativo?: boolean }) =>
    fetch("api/responsaveis-bv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean; nome_key: string; nome: string }>),
```

- [ ] **Step 3: Criar o hook**

Create `egps_analysis/app/frontend/src/useSubareas.ts`:

```ts
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { mapaSubarea, ordenarSubareas, type MapaSubarea } from "./subareas";

// Acesso ao cadastro Responsável BV -> sub-área. Uma queryKey só (["responsaveis-bv"])
// compartilhada por TODAS as abas: o cadastro tem ~11 linhas e muda raramente, então a
// primeira aba que abrir paga a busca e as outras leem do cache do React Query.
// Separado de subareas.ts de propósito: lá ficam helpers puros, testáveis sob node.
export function useSubareas(): {
  mapa: MapaSubarea;
  nomes: string[];          // grafias cadastradas (datalist do campo Responsável BV)
  subareas: string[];       // sub-áreas distintas cadastradas (datalist da Gestão)
} {
  const q = useQuery({ queryKey: ["responsaveis-bv"], queryFn: () => api.responsaveisBv() });
  const rows = useMemo(() => q.data?.rows ?? [], [q.data]);
  return useMemo(() => ({
    mapa: mapaSubarea(rows),
    nomes: rows.map((r) => r.nome).sort((a, b) => a.localeCompare(b, "pt-BR")),
    subareas: ordenarSubareas(rows.map((r) => (r.subarea ?? "").trim()).filter(Boolean)),
  }), [rows]);
}
```

- [ ] **Step 4: Aquecer o cache no prefetch**

Em `src/prefetch.ts`, no bloco "e as leves", logo após a linha do `["analistas"]`:

```ts
  P(["responsaveis-bv"], () => api.responsaveisBv());            // sub-área BV (todas as abas)
```

E no bloco `if (cfg.is_gestao)`, após `P(["analistas", "all"], …)`:

```ts
    P(["responsaveis-bv", "all"], () => api.responsaveisBv(true)); // Gestão (cadastro)
```

- [ ] **Step 5: Verificar que compila**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/api.ts egps_analysis/app/frontend/src/useSubareas.ts egps_analysis/app/frontend/src/prefetch.ts
git commit -m "feat(app): API, tipos e hook do cadastro de sub-area BV"
```

---

## Task 5: Gestão — CRUD "Responsáveis BV"

Sem esta tela o cadastro só existiria via SQL. Ela vem antes das superfícies de leitura para que dê para popular e conferir os dados de verdade nas tasks seguintes.

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/GestaoView.tsx`

- [ ] **Step 1: Adicionar imports e o bloco de estado**

Em `GestaoView.tsx`, ampliar os imports existentes:

```ts
import type { Analista, ResponsavelBv } from "../types";
import { useSubareas } from "../useSubareas";
```

Dentro de `GestaoView()`, após o `const [msg, setMsg] = useState<string | null>(null);`:

```ts
  // Cadastro Responsável BV -> sub-área (mesma estrutura do cadastro de analistas acima).
  // Inclui inativos: gestores precisam ver/reativar quem foi desativado.
  const qBv = useQuery({ queryKey: ["responsaveis-bv", "all"], queryFn: () => api.responsaveisBv(true) });
  const { subareas: subareasCadastradas } = useSubareas();
  const [bvNome, setBvNome] = useState("");
  const [bvSub, setBvSub] = useState("");

  const upsertBv = useMutation({
    mutationFn: (b: { nome: string; subarea?: string; ativo?: boolean }) => api.responsavelBvUpsert(b),
    // invalida as DUAS chaves: a lista desta tela ("all") e a que alimenta o filtro de
    // sub-área nas outras abas (["responsaveis-bv"]).
    onSuccess: () => qc.invalidateQueries({ queryKey: ["responsaveis-bv"] }),
    onError: (e) => setMsg(`Falha: ${e}`),
  });

  const bvRows: ResponsavelBv[] = qBv.data?.rows ?? [];

  function addBv() {
    const n = bvNome.trim();
    if (!n) { setMsg("Informe o nome do responsável BV."); return; }
    upsertBv.mutate({ nome: n, subarea: bvSub.trim(), ativo: true });
    setBvNome(""); setBvSub(""); setMsg(null);
  }
```

- [ ] **Step 2: Adicionar a seção na UI**

No JSX de `GestaoView`, logo antes de `<h3>Gestão de analistas</h3>`:

```tsx
      <h3>Responsáveis BV</h3>
      <p className="muted">
        A <b>sub-área BV</b> é a área interna do cliente (Digital, MIS, Operações,
        Estratégia - cartões/rodas, Riscos) e vale por <b>pessoa</b>: cadastrar alguém aqui
        reclassifica todos os EGPs em que ela é Responsável BV. Quem não estiver nesta lista
        aparece como <b>Sem sub-área</b> nas demais abas.
      </p>

      <div className="rsm-card">
        <div className="gestao-add">
          <input type="text" placeholder="nome (como está no EGP)" value={bvNome}
            onChange={(e) => setBvNome(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") addBv(); }} />
          <input type="text" list="subareas-bv" placeholder="sub-área" value={bvSub}
            onChange={(e) => setBvSub(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") addBv(); }} />
          <datalist id="subareas-bv">
            {subareasCadastradas.map((s) => <option key={s} value={s} />)}
          </datalist>
          <button className="theme-btn" onClick={addBv} disabled={upsertBv.isPending}>+ Adicionar</button>
        </div>
      </div>

      {qBv.error && <div className="error">{String(qBv.error)}</div>}
      <div className="rsm-card">
        <table className="rsm-tbl">
          <thead>
            <tr><th>Nome</th><th>Sub-área</th><th style={{ width: 70 }}>Ativo</th></tr>
          </thead>
          <tbody>
            {bvRows.map((b) => (
              <tr key={b.nome_key} className={isAtivo(b.ativo) ? undefined : "zero"}>
                <td>{b.nome}</td>
                <td>
                  <input defaultValue={b.subarea ?? ""} list="subareas-bv" placeholder="—"
                    title="Área interna do BV desta pessoa"
                    onBlur={(e) => { const v = e.target.value.trim();
                      if (v !== (b.subarea ?? "")) upsertBv.mutate({ nome: b.nome, subarea: v }); }} />
                </td>
                <td>
                  <input type="checkbox" checked={isAtivo(b.ativo)}
                    title={isAtivo(b.ativo) ? "Ativo — desmarque para desativar" : "Inativo — marque para reativar"}
                    onChange={(e) => upsertBv.mutate({ nome: b.nome, ativo: e.target.checked })} />
                </td>
              </tr>
            ))}
            {!qBv.isFetching && bvRows.length === 0 && (
              <tr><td colSpan={3} className="muted">Nenhum responsável BV cadastrado.</td></tr>
            )}
          </tbody>
        </table>
      </div>
```

> O nome é **read-only** na tabela (só editável ao criar): ele é a chave que casa com o texto livre gravado nos EGPs. Renomear aqui criaria uma linha nova e deixaria os EGPs órfãos — quem errou o nome desativa a linha e cria outra.

- [ ] **Step 3: Verificar que compila**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 4: Popular o cadastro pela tela**

Subir o app local (skill `running-app-locally`), abrir a aba **Gestão** e cadastrar as 11 pessoas:

| Nome | Sub-área |
|---|---|
| Adamor Luz | Digital |
| Rafael Vasconcelos Ribeiro | Digital |
| Carolina Matos | Operações |
| Daniel Vitor | Operações |
| cynthia | Operações |
| Cleber William De Jesus Saure | MIS |
| Cristiano | MIS |
| Joao Carneiro | Estratégia - cartões |
| Leticia Domingos Duarte | Estratégia - rodas |
| Igor Brito | Riscos |
| Não localizado | *(deixar vazio)* |

Expected: as 11 linhas aparecem na tabela; recarregar a página mantém tudo (veio do warehouse).

- [ ] **Step 5: Commit**

```bash
git add egps_analysis/app/frontend/src/components/GestaoView.tsx
git commit -m "feat(app): CRUD de Responsaveis BV na aba Gestao"
```

---

## Task 6: Campo Responsável BV com datalist

Sem isto, o próximo analista digita "Leticia" de novo e recria a divergência que a Task 1 acabou de corrigir. O campo continua aceitando texto livre (atribuir alguém novo não pode depender de cadastro prévio) — a datalist só sugere.

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/RespBvInput.tsx`

- [ ] **Step 1: Trocar o input por um com datalist**

Substituir o conteúdo de `RespBvInput.tsx` por:

```tsx
import { useEffect, useId, useState } from "react";
import { useSubareas } from "../useSubareas";

// Input de texto com commit no blur/Enter — responsável do lado BV (sas_egp_pipeline).
// Extraído de ReadinessView p/ ser compartilhado com o modal de detalhe (EgpDetailPanel).
// A datalist sugere as grafias já cadastradas (Gestão → Responsáveis BV) sem travar o campo:
// atribuir alguém novo não pode depender de cadastro prévio. Sugerir importa porque o nome
// é a chave que resolve a sub-área — "Leticia" e "Leticia Domingos Duarte" viram 2 pessoas.
export function RespBvInput({ value, onSave }: { value: string | null; onSave: (v: string | null) => void }) {
  const [draft, setDraft] = useState(value ?? "");
  const { nomes } = useSubareas();
  const listId = useId();
  useEffect(() => { setDraft(value ?? ""); }, [value]);
  const commit = (v: string) => {
    const t = v.trim();
    if (t === (value ?? "")) return;
    onSave(t === "" ? null : t);
  };
  return (
    <>
      <input type="text" placeholder="—" value={draft} list={listId}
        title="Responsável do lado BV por este EGP (sugestões vêm do cadastro da Gestão)"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
      <datalist id={listId}>
        {nomes.map((n) => <option key={n} value={n} />)}
      </datalist>
    </>
  );
}
```

- [ ] **Step 2: Verificar que compila**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 3: Conferir no app**

Na aba EGPs, clicar num campo "Responsável BV": as 11 grafias cadastradas aparecem como sugestão; digitar um nome fora da lista continua funcionando e salva normalmente.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/frontend/src/components/RespBvInput.tsx
git commit -m "feat(app): datalist de nomes cadastrados no campo Responsavel BV"
```

---

## Task 7: Aba EGPs — chips, filtro, coluna e CSV

A aba EGPs é a superfície principal. Atenção a um detalhe que decide se os chips funcionam: **a contagem de cada chip tem que ignorar o próprio filtro de sub-área**, senão ao selecionar uma sub-área todas as outras zeram e ficam impossíveis de clicar. Por isso o recorte de dimensões é quebrado em dois memos.

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/ReadinessView.tsx`
- Modify: `egps_analysis/app/frontend/src/styles.css`

- [ ] **Step 1: Imports e estado do filtro**

Em `ReadinessView.tsx`, junto dos demais imports:

```ts
import { useSubareas } from "../useSubareas";
import { SEM_SUBAREA, subareaDe, ordenarSubareas } from "../subareas";
```

Logo após o bloco de `respBvSel` (linha ~128):

```ts
  // Sub-área BV = área interna do cliente, derivada do Responsável BV pelo cadastro da
  // Gestão (ver src/subareas.ts). useTabState pelo mesmo motivo dos filtros vizinhos:
  // sobrevive ao cross-nav — inclusive ao vindo da tabela do Resumo, que escreve nesta
  // mesma chave antes de navegar.
  const [subareaSel, setSubareaSel] = useTabState<Set<string>>("egps.subarea", new Set());
  const toggleSubarea = (s: string) =>
    setSubareaSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
```

- [ ] **Step 2: Resolver a sub-área de cada linha**

Após `const { mesOf, meses } = useMesPlan();` (linha ~168):

```ts
  const { mapa: mapaSub } = useSubareas();
  // EGP sem responsável ou com responsável fora do cadastro cai em "Sem sub-área" — bucket
  // visível, nunca linha escondida.
  const subOf = useMemo(
    () => (r: ReadinessRow) => subareaDe(r.responsavel_bv, mapaSub) ?? SEM_SUBAREA,
    [mapaSub]);
  // Opções do filtro/chips: saem de TODAS as linhas do recorte (não do subconjunto
  // filtrado), senão a opção desaparece assim que você filtra por ela.
  const subareaList = useMemo(() => ordenarSubareas(rows.map(subOf)), [rows, subOf]);
```

- [ ] **Step 3: Quebrar `baseDims` em dois memos**

Substituir o memo `baseDims` existente (linha ~185) por:

```ts
  // Conjunto após os filtros de DIMENSÃO (área/onda/status/etapa/busca). Os chips de
  // bucket e quick win são toggles aplicados em cima (em `view`); por isso os
  // indicadores abaixo contam sobre baseDims e reagem aos filtros de dimensão.
  //
  // Dois memos: `baseSemSubarea` é tudo MENOS o filtro de sub-área, e é sobre ele que os
  // chips de sub-área contam. Se contassem sobre baseDims, selecionar uma sub-área zeraria
  // todas as outras e nenhuma daria para clicar de novo.
  const baseSemSubarea = useMemo(() => {
    let v = rows;
    if (soComResp) v = v.filter((r) => !!r.responsavel);
    if (areaSel.size) v = v.filter((r) => areaSel.has(r.area));
    if (mesSel.size) v = v.filter((r) => mesSel.has(mesTag(mesOf.get(r.projeto))));
    if (statusSel.size) v = v.filter((r) => statusSel.has(r.status));
    if (etapaSel.size) v = v.filter((r) => etapaSel.has(r.etapa));
    if (respBvSel.size) v = v.filter((r) => !!r.responsavel_bv && respBvSel.has(r.responsavel_bv));
    if (showTipo && tipoSel.size) v = v.filter((r) => tipoSel.has(TIPO_LABEL[r.tipo] ?? r.tipo));
    if (q) {
      const ql = q.toLowerCase();
      v = v.filter((r) => r.projeto.toLowerCase().includes(ql)
        || (r.jira_id?.toLowerCase().includes(ql) ?? false));
    }
    return v;
  }, [rows, soComResp, areaSel, mesSel, mesOf, statusSel, etapaSel, respBvSel, tipoSel, showTipo, q]);
  const baseDims = useMemo(
    () => (subareaSel.size ? baseSemSubarea.filter((r) => subareaSel.has(subOf(r))) : baseSemSubarea),
    [baseSemSubarea, subareaSel, subOf]);
  // Contagem por sub-área para os chips (ignora o próprio filtro de sub-área, ver acima).
  const subareaCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of baseSemSubarea) m.set(subOf(r), (m.get(subOf(r)) ?? 0) + 1);
    return m;
  }, [baseSemSubarea, subOf]);
```

- [ ] **Step 4: Adicionar o MultiSelect ao lado do de Responsável BV**

Logo após o `<MultiSelect label="Responsável BV" …>` (linha ~348):

```tsx
        <MultiSelect label="Sub-área BV" options={subareaList} sel={subareaSel}
          title="Área interna do BV do responsável (Digital, MIS, Operações, Estratégia…). Vem do cadastro em Gestão → Responsáveis BV; quem não está lá aparece como 'Sem sub-área'."
          onToggle={toggleSubarea} onClear={() => setSubareaSel(new Set())} />
```

- [ ] **Step 5: Adicionar a linha de chips**

Logo após o `</div>` que fecha a `<div className="rd-chips">` existente (linha ~430) e ANTES do `</>}` que fecha o bloco `{!hdr.collapsed && <>` — a linha nova tem que recolher junto com o resto do cabeçalho:

```tsx
      <div className="rd-chips">
        <span className="rd-chips-lbl">Sub-área BV</span>
        {subareaList.map((s) => (
          <button key={s} className={`chip ${s === SEM_SUBAREA ? "todo" : "wip"} ${subareaSel.has(s) ? "on" : ""}`}
            title={s === SEM_SUBAREA
              ? "EGPs sem Responsável BV, ou com um responsável que não está no cadastro da Gestão"
              : `EGPs cujo Responsável BV é da sub-área ${s}`}
            onClick={() => toggleSubarea(s)}>{s}: {subareaCounts.get(s) ?? 0}</button>
        ))}
        <InfoTip text="Área interna do BV a que pertence o Responsável BV do EGP. É atributo da PESSOA: cadastre em Gestão → Responsáveis BV e todos os EGPs dela mudam junto. Cada chip é o mesmo filtro do seletor 'Sub-área BV' acima; a contagem ignora o próprio filtro de sub-área (por isso selecionar uma não zera as outras)." />
      </div>
```

- [ ] **Step 6: Adicionar a coluna à tabela**

No `<div className="rd-thead…">`, trocar `<div>Responsável BV</div><div>Último status</div>` por:

```tsx
<div>Responsável BV</div><div>Sub-área BV</div><div>Último status</div>
```

Na linha, logo após o `<div className="rd-respbv" …>…</div>` (linha ~556):

```tsx
                  <div className="muted" style={{ fontSize: 11 }}
                    title="Derivada do Responsável BV (cadastro em Gestão → Responsáveis BV) — não se edita por EGP">
                    {subOf(r)}
                  </div>
```

- [ ] **Step 7: Ajustar a grid no CSS**

Em `src/styles.css` (linhas 433-436), as três larguras. A coluna nova são 130px inseridos entre "Responsável BV" (120px) e "Último status" (150px):

```css
.rd-table .rd-thead, .rd-table .rd-tbody { min-width: 1790px; }
.rd-thead, .rd-trow { display: grid; grid-template-columns: 44px minmax(200px,2.6fr) 110px 0.6fr 60px 70px 56px minmax(80px,0.8fr) 54px 70px 90px 160px 150px 160px 120px 130px 150px; align-items: center; }
/* variante da aba EGPs no recorte "Indicium + dependências": coluna Tipo (escopo/dependência) entre EGP e Área */
.rd-thead.with-tipo, .rd-trow.with-tipo { grid-template-columns: 44px minmax(200px,2.6fr) 110px 120px 0.6fr 60px 70px 56px minmax(80px,0.8fr) 54px 70px 90px 160px 150px 160px 120px 130px 150px; }
```

E adicionar, junto das regras de chips (após a linha `.chip.ok { … }`, linha ~431):

```css
.rd-chips-lbl { font-size: 11px; color: var(--mut); margin-right: 2px; }
```

- [ ] **Step 8: Adicionar a coluna ao CSV**

No `exportCsv`, logo após `{ header: "Responsável BV", … }`:

```ts
      { header: "Sub-área BV", get: (r) => subOf(r) },
```

- [ ] **Step 9: Verificar**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros.

Com o app rodando, na aba EGPs:
- A linha de chips mostra `Digital: N`, `MIS: N`, …, `Sem sub-área: N`, e a soma bate com o total de EGPs do recorte.
- Clicar num chip filtra a tabela **e** as contagens dos outros chips continuam as mesmas (não zeram).
- O seletor "Sub-área BV" e o chip refletem a mesma seleção (clicar num, o outro acompanha).
- A coluna "Sub-área BV" aparece preenchida; EGP sem responsável mostra "Sem sub-área".
- O CSV exportado tem a coluna nova.

- [ ] **Step 10: Commit**

```bash
git add egps_analysis/app/frontend/src/components/ReadinessView.tsx egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app): sub-area BV na aba EGPs (chips, filtro, coluna e CSV)"
```

---

## Task 8: Aba Acompanhamento — chips e filtro

Aqui a entidade pode ser **input**, que herda a sub-área de vários EGPs consumidores — por isso usa `subareasDe` (plural) e não `subareaDe`.

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/AcompanhamentoView.tsx`

- [ ] **Step 1: Imports, estado e resolução**

Junto dos imports:

```ts
import { useSubareas } from "../useSubareas";
import { subareasDe, ordenarSubareas, SEM_SUBAREA } from "../subareas";
```

Junto dos outros filtros do componente (logo após `respsBvSel`, linha ~79). Aqui é `useState` mesmo — todos os filtros vizinhos desta aba são `useState`; não introduza `useTabState` só neste:

```ts
  const [subareasSel, setSubareasSel] = useState<Set<string>>(new Set());
```

Após o memo `respBvOptions`:

```ts
  const { mapa: mapaSub } = useSubareas();
  // Multi-valorado: na variante "input" a linha herda o Responsável BV de TODOS os EGPs
  // consumidores, que podem ser de sub-áreas diferentes — a linha entra nas duas.
  const subareasDaLinha = useMemo(
    () => (r: GestaoRow) => subareasDe(respBvOf(r, entity, readinessMap), mapaSub),
    [mapaSub, entity, readinessMap]);
  const subareaOptions = useMemo(
    () => ordenarSubareas(rows.flatMap(subareasDaLinha)), [rows, subareasDaLinha]);
```

- [ ] **Step 2: Aplicar o filtro em dois passos**

Substituir o memo `filtered` por um par, pelo mesmo motivo da aba EGPs (chip não pode zerar os vizinhos):

```ts
  const filteredSemSubarea = useMemo(() => rows.filter((r) => {
    if (etapasSel.size && !etapasSel.has(etapaKeyOf(r))) return false;
    if (respsBvSel.size && !respBvOf(r, entity, readinessMap).some((bv) => respsBvSel.has(bv))) return false;
    // herdado dos EGPs consumidores (n:n na variante input) — passa se QUALQUER um bate
    if (mesesSel.size && !r.egps.some((e) => mesesSel.has(mesTag(mesOf.get(e))))) return false;
    if (pctRange) {
      if (entity === "egp") {
        if (!pctPassaFiltro(readinessMap.get(r.id), pctCategoriasSel, pctRange)) return false;
      } else {
        const p = preworkingPercentual(preworkingMap.get(r.id));
        if (p < pctRange[0] || p > pctRange[1]) return false;
      }
    }
    return true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [rows, etapasSel, respsBvSel, mesesSel, pctRange, pctCategoriasSel, mesOf, colunasValidas, readinessMap, preworkingMap, entity]);
  const filtered = useMemo(
    () => (subareasSel.size
      ? filteredSemSubarea.filter((r) => subareasDaLinha(r).some((s) => subareasSel.has(s)))
      : filteredSemSubarea),
    [filteredSemSubarea, subareasSel, subareasDaLinha]);
  // contagem dos chips: ignora o próprio filtro de sub-área
  const subareaCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of filteredSemSubarea) for (const s of subareasDaLinha(r)) m.set(s, (m.get(s) ?? 0) + 1);
    return m;
  }, [filteredSemSubarea, subareasDaLinha]);
```

- [ ] **Step 3: Adicionar o MultiSelect**

Logo após o `<MultiSelect label="Responsável BV" …>` do bloco `.filters`:

```tsx
        <MultiSelect label="Sub-área BV" options={subareaOptions} sel={subareasSel}
          title="Área interna do BV do responsável. Na visão de inputs, o input aparece se QUALQUER EGP consumidor for da sub-área selecionada."
          onToggle={(v) => setSubareasSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setSubareasSel(new Set())} />
```

- [ ] **Step 4: Adicionar os chips**

Imediatamente após o fechamento da `<div className="filters">`:

```tsx
      <div className="rd-chips">
        <span className="rd-chips-lbl">Sub-área BV</span>
        {subareaOptions.map((s) => (
          <button key={s} className={`chip ${s === SEM_SUBAREA ? "todo" : "wip"} ${subareasSel.has(s) ? "on" : ""}`}
            title={s === SEM_SUBAREA
              ? "Sem Responsável BV, ou responsável fora do cadastro da Gestão"
              : `Sub-área ${s}`}
            onClick={() => setSubareasSel((p) => { const n = new Set(p); n.has(s) ? n.delete(s) : n.add(s); return n; })}>
            {s}: {subareaCounts.get(s) ?? 0}
          </button>
        ))}
      </div>
```

- [ ] **Step 5: Verificar**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros.

No app, aba Acompanhamento: os chips aparecem nas duas variantes (EGP e Input); filtrar por uma sub-área reduz os quadros; na variante Input, a soma das contagens pode passar do total de linhas — isso é **esperado** (input de dois consumidores conta nas duas sub-áreas).

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/components/AcompanhamentoView.tsx
git commit -m "feat(app): filtro e chips de sub-area BV no Acompanhamento"
```

---

## Task 9: Aba Gestão — filtro no Kanban e linha no painel de status

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/GestaoMigracao.tsx`
- Modify: `egps_analysis/app/frontend/src/components/GestaoStatusPanel.tsx`

- [ ] **Step 1: `GestaoMigracao` — imports, estado e resolução**

Junto dos imports:

```ts
import { useSubareas } from "../useSubareas";
import { subareasDe, ordenarSubareas } from "../subareas";
```

Logo após `const [respsBvSel, setRespsBvSel] = useState<Set<string>>(new Set());` (linha ~82):

```ts
  const [subareasSel, setSubareasSel] = useState<Set<string>>(new Set());
```

Logo após o memo `respBvOptions` (linha ~174):

```ts
  // Sub-área BV: derivada do Responsável BV pelo cadastro (Gestão → Responsáveis BV).
  // Multi-valorada na variante "input" — herda de todos os EGPs consumidores.
  const { mapa: mapaSub } = useSubareas();
  const subareasDaLinha = useMemo(
    () => (r: GestaoRow) => subareasDe(respBvOf(r, entity, readinessMap), mapaSub),
    [mapaSub, entity, readinessMap]);
  const subareaOptions = useMemo(
    () => ordenarSubareas(rows.flatMap(subareasDaLinha)), [rows, subareasDaLinha]);
```

- [ ] **Step 2: `GestaoMigracao` — aplicar o filtro**

No memo `filtered`, logo após a linha do `respsBvSel` (linha ~198):

```ts
      if (subareasSel.size && !subareasDaLinha(r).some((s) => subareasSel.has(s))) return false;
```

E acrescentar `subareasSel, subareasDaLinha` ao array de dependências desse `useMemo`.

- [ ] **Step 3: `GestaoMigracao` — adicionar o MultiSelect**

Logo após o `<MultiSelect label="Responsável BV" …>` (linha ~393):

```tsx
        <MultiSelect label="Sub-área BV" options={subareaOptions} sel={subareasSel}
          title={entity === "egp"
            ? "Área interna do BV do responsável (cadastro em Gestão → Responsáveis BV, no topo desta aba)."
            : "Sub-área dos EGPs consumidores — o input aparece se QUALQUER consumidor for da sub-área selecionada."}
          onToggle={(v) => setSubareasSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setSubareasSel(new Set())} />
```

- [ ] **Step 4: `GestaoStatusPanel` — mostrar a sub-área**

Junto dos imports:

```ts
import { useSubareas } from "../useSubareas";
import { subareasDe } from "../subareas";
```

No corpo do componente, junto dos outros hooks:

```ts
  const { mapa: mapaSub } = useSubareas();
```

O painel tem **dois** blocos "Resp. BV" (um na variante EGP, linha ~216, outro na variante input, linha ~348). Em cada um, logo após o `</div>` que fecha o `gm-field` do "Resp. BV", adicionar:

```tsx
            <div className="gm-field">
              <span>Sub-área BV</span>
              <div className="muted" style={{ fontSize: 12 }}
                title="Área interna do BV — derivada do Responsável BV pelo cadastro em Gestão → Responsáveis BV">
                {subareasDe(respBvOf(row, entity, readinessMap), mapaSub).join(", ")}
              </div>
            </div>
```

(No segundo bloco a indentação é um nível maior — siga a do `gm-field` vizinho.)

- [ ] **Step 5: Verificar**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros.

No app (aba Gestão, restrita a bv_users): o seletor "Sub-área BV" filtra o Kanban; abrir um card mostra a linha "Sub-área BV" logo abaixo de "Resp. BV", tanto para EGP quanto para input.

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/components/GestaoMigracao.tsx egps_analysis/app/frontend/src/components/GestaoStatusPanel.tsx
git commit -m "feat(app): sub-area BV no Kanban e no painel de status da Gestao"
```

---

## Task 10: Drawer do EGP — sub-área ao lado do Responsável BV

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx`

- [ ] **Step 1: Import e resolução**

Junto dos imports:

```ts
import { useSubareas } from "../useSubareas";
import { SEM_SUBAREA, subareaDe } from "../subareas";
```

No corpo do componente, junto dos outros hooks:

```ts
  const { mapa: mapaSub } = useSubareas();
```

- [ ] **Step 2: Mostrar a sub-área embaixo do campo**

Na célula do `RespBvInput` (linha ~381), trocar

```tsx
                <div>
                  <RespBvInput value={cur.responsavel_bv ?? null}
                    onSave={(v) => pipeMut.mutate({ responsavel_bv: v ?? "" })} />
                </div>
```

por

```tsx
                <div>
                  <RespBvInput value={cur.responsavel_bv ?? null}
                    onSave={(v) => pipeMut.mutate({ responsavel_bv: v ?? "" })} />
                  {/* derivada do nome acima pelo cadastro (Gestão → Responsáveis BV); muda
                      sozinha quando o responsável muda, por isso não é editável aqui */}
                  <div className="muted" style={{ fontSize: 11, marginTop: 2 }}
                    title="Área interna do BV — vem do cadastro em Gestão → Responsáveis BV">
                    {subareaDe(cur.responsavel_bv, mapaSub) ?? SEM_SUBAREA}
                  </div>
                </div>
```

- [ ] **Step 3: Verificar**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros.

No app: abrir um EGP na aba EGPs; abaixo do campo "Responsável BV" aparece a sub-área. Trocar o responsável para outra pessoa cadastrada muda a sub-área logo após salvar.

- [ ] **Step 4: Commit**

```bash
git add egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx
git commit -m "feat(app): sub-area BV no drawer do EGP"
```

---

## Task 11: Resumo — tabela agregada no fim, com cross-nav

A tabela lê `/api/readiness` com a **mesma queryKey** da aba EGPs (`["egp-readiness", "indi_deps"]`), então não custa query nova: o React Query serve do cache. Clicar numa linha escreve o filtro no store de aba e navega — por isso `tabState` ganha um setter usável fora de componente.

**Files:**
- Modify: `egps_analysis/app/frontend/src/tabState.ts`
- Modify: `egps_analysis/app/frontend/src/App.tsx`
- Modify: `egps_analysis/app/frontend/src/components/ResumoView.tsx`

- [ ] **Step 1: Setter no `tabState`**

Em `src/tabState.ts`, no fim do arquivo:

```ts
// Escreve no store de fora de um componente. Usado pelo cross-nav do Resumo: a view de
// destino ainda não está montada (o App monta uma view por vez), então ela lê este valor
// no initializer do useState ao montar. Não notifica quem já está montado — de propósito:
// o único caso de uso é "prepare o filtro e navegue".
export function setTabState<T>(key: string, value: T): void {
  store.set(key, value);
}
```

- [ ] **Step 2: Passar `onNav` ao Resumo**

Em `src/App.tsx`, trocar

```tsx
      {view === "resumo" && <ResumoView cfg={cfg} />}
```

por

```tsx
      {view === "resumo" && <ResumoView cfg={cfg} onNav={go} />}
```

- [ ] **Step 3: Tabela no `ResumoView`**

Em `src/components/ResumoView.tsx`, nos imports:

```ts
import { useMemo } from "react";
import type { ReadinessRow } from "../types";
import type { View } from "../routes";
import { setTabState } from "../tabState";
import { useSubareas } from "../useSubareas";
import { SEM_SUBAREA, subareaDe, ordenarSubareas } from "../subareas";
```

Adicionar o componente da tabela, antes de `export function ResumoView`:

```tsx
// "EGPs por sub-área BV": recorte por ÁREA INTERNA DO CLIENTE (quem cobra o quê do lado
// do BV), não por área de negócio do EGP. Calculada no cliente sobre /api/readiness —
// mesma queryKey da aba EGPs, então sai do cache sem query nova no warehouse.
function SubareaTable({ onNav }: { onNav: (v: View) => void }) {
  const q = useQuery({ queryKey: ["egp-readiness", "indi_deps"], queryFn: () => api.egpReadiness("indi_deps") });
  const { mapa } = useSubareas();
  const rows: ReadinessRow[] = q.data?.rows ?? [];

  const linhas = useMemo(() => {
    type Acc = { sub: string; egps: number; migrados: number; bloqueados: number; faltam: number; pctNum: number; pctDen: number };
    const m = new Map<string, Acc>();
    for (const r of rows) {
      const sub = subareaDe(r.responsavel_bv, mapa) ?? SEM_SUBAREA;
      const a = m.get(sub) ?? { sub, egps: 0, migrados: 0, bloqueados: 0, faltam: 0, pctNum: 0, pctDen: 0 };
      a.egps++;
      // etapa "Migrado" sozinha mente: dezenas de EGPs chegam nela por despriorização.
      // Só conta como migrado quem está na etapa E não foi despriorizado.
      if (r.etapa === "Migrado" && r.status !== "Despriorizado e Contabilizado") a.migrados++;
      if (r.bloqueado_dep) a.bloqueados++;
      a.faltam += r.n_faltam ?? 0;
      // % pronto ponderado por nº de inputs: média simples das médias daria o mesmo peso a
      // um EGP de 1 input e a um de 80.
      a.pctNum += (r.pct ?? 0) * (r.n_inputs ?? 0);
      a.pctDen += r.n_inputs ?? 0;
      m.set(sub, a);
    }
    const ordem = ordenarSubareas([...m.keys()]);
    return ordem.map((s) => m.get(s)!);
  }, [rows, mapa]);

  const tot = useMemo(() => linhas.reduce((t, l) => ({
    egps: t.egps + l.egps, migrados: t.migrados + l.migrados, bloqueados: t.bloqueados + l.bloqueados,
    faltam: t.faltam + l.faltam, pctNum: t.pctNum + l.pctNum, pctDen: t.pctDen + l.pctDen,
  }), { egps: 0, migrados: 0, bloqueados: 0, faltam: 0, pctNum: 0, pctDen: 0 }), [linhas]);

  const pct = (num: number, den: number) => (den > 0 ? Math.round(num / den) : 0);

  // clique: prepara o filtro da aba EGPs e navega (a view lê o store ao montar)
  const abrir = (sub: string) => { setTabState("egps.subarea", new Set([sub])); onNav("readiness"); };

  if (q.isFetching && rows.length === 0) return <div className="rsm-card muted">carregando…</div>;
  if (q.error) return <div className="error">{String(q.error)}</div>;

  return (
    <div className="rsm-card">
      <table className="rsm-tbl">
        <thead>
          <tr>
            <th>Sub-área BV</th><th>EGPs</th><th>Migrados</th><th>Bloqueados</th>
            <th>Inputs faltando</th><th>% pronto</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map((l) => (
            <tr key={l.sub} style={{ cursor: "pointer" }} title="Abrir a aba EGPs filtrada por esta sub-área"
              onClick={() => abrir(l.sub)}>
              <td>{l.sub}</td>
              <td>{fmt(l.egps)}</td>
              <td>{fmt(l.migrados)}</td>
              <td className={l.bloqueados > 0 ? "neg" : "zero"}>{fmt(l.bloqueados)}</td>
              <td className={l.faltam > 0 ? "neg" : "zero"}>{fmt(l.faltam)}</td>
              <td className="rsm-pct">
                <div className="rsm-bar"><div style={{ width: `${pct(l.pctNum, l.pctDen)}%` }} /></div>
                <span>{pct(l.pctNum, l.pctDen)}%</span>
              </td>
            </tr>
          ))}
          <tr className="tot">
            <td>Total</td><td>{fmt(tot.egps)}</td><td>{fmt(tot.migrados)}</td>
            <td>{fmt(tot.bloqueados)}</td><td>{fmt(tot.faltam)}</td>
            <td>{pct(tot.pctNum, tot.pctDen)}%</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Aceitar a prop e renderizar a seção**

Trocar a assinatura do componente para incluir `onNav`:

```tsx
export function ResumoView({ cfg, onNav }: { cfg: AppConfig | null; onNav: (v: View) => void }) {
```

E, antes do `<p className="muted">Indicadores 3/4/6/7 …` que fecha a view:

```tsx
      <h3>EGPs por sub-área BV</h3>
      <details className="rsm-como"><summary>como estes números são contados</summary>
      <p className="muted">Recorte fixo: Indicium + dependências transitivas (o mesmo default da aba EGPs). A <b>sub-área BV</b> é a área interna do cliente (Digital, MIS, Operações, Estratégia…) e vem do <b>Responsável BV</b> do EGP pelo cadastro em Gestão → Responsáveis BV — quem não estiver cadastrado cai em "Sem sub-área". <b>Migrados</b> conta quem está na etapa Migrado E não foi despriorizado (a etapa sozinha mente: EGP despriorizado também chega nela). <b>% pronto</b> é a média de inputs modernizados ponderada pelo nº de inputs de cada EGP, não a média das médias. Clique numa linha para abrir a aba EGPs já filtrada.</p>
      </details>
      <SubareaTable onNav={onNav} />
```

- [ ] **Step 5: Verificar**

Run: `cd egps_analysis/app/frontend && npx tsc --noEmit`
Expected: sem erros.

No app:
- A tabela aparece no fim do Resumo e a linha **Total** bate com o total de EGPs do recorte "Indicium + dependências" da aba EGPs.
- Clicar numa linha abre a aba EGPs com o chip/seletor daquela sub-área já ligado e a tabela filtrada.
- A contagem de EGPs de cada sub-área bate com o chip correspondente na aba EGPs (com os demais filtros limpos).

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/frontend/src/tabState.ts egps_analysis/app/frontend/src/App.tsx egps_analysis/app/frontend/src/components/ResumoView.tsx
git commit -m "feat(app): tabela de EGPs por sub-area BV no Resumo, com cross-nav"
```

---

## Task 12: Documentação e verificação final

**Files:**
- Modify: `egps_analysis/app/README.md`
- Modify: `CONTEXT.md`

- [ ] **Step 1: Registrar a decisão no README do app**

Em `egps_analysis/app/README.md`, na seção "Decisões de design", acrescentar:

```markdown
### Sub-área BV é atributo da pessoa, não do EGP

A **sub-área BV** é a área interna do cliente (Digital, MIS, Operações, Estratégia -
cartões/rodas, Riscos) e fica no cadastro `sas_responsaveis_bv` (aba Gestão → Responsáveis
BV), chaveado pelo nome NORMALIZADO (trim + minúsculas + sem acento + espaços colapsados —
`_norm_nome_bv` no backend, `normNome` em `src/subareas.ts`; mudou num, muda no outro).

O EGP herda a sub-área do seu `responsavel_bv`; o input herda as dos EGPs que o consomem
(multi-valorado). **Não existe** sub-área editável por EGP: seria trabalho manual em ~200
linhas e divergiria do responsável. Quem não está no cadastro aparece como "Sem sub-área" —
bucket visível de propósito, é o sinal de que falta cadastrar alguém.

Não confundir com **Área** (Cobrança/Riscos/Jurídico), que é a área de NEGÓCIO do EGP e é
outro eixo: um EGP de Cobrança pode ter responsável da sub-área MIS.

A tabela do Resumo é calculada no cliente sobre `/api/readiness` (mesma queryKey da aba
EGPs) — nenhuma query nova no warehouse. `sas_responsaveis_bv` fica fora do publish, como
`sas_analistas`: guarda dado 100% humano e nunca é dropada no republish.
```

- [ ] **Step 2: Registrar o termo no CONTEXT.md**

Em `CONTEXT.md`, na seção `### Corpus e app atual`, no formato dos termos vizinhos (negrito + dois-pontos, descrição na linha seguinte, `_Avoid_` opcional):

```markdown
**Sub-área BV**:
A área interna do cliente (Digital, MIS, Operações, Estratégia - cartões, Estratégia - rodas, Riscos) a que pertence o Responsável BV de um EGP. É atributo da pessoa (cadastro `sas_responsaveis_bv`), herdado pelo EGP.
_Avoid_: área interna (colide com "Área", a área de negócio do EGP: Cobrança/Riscos/Jurídico)
```

- [ ] **Step 3: Suíte completa**

Run:
```bash
cd egps_analysis/app && venv/bin/python -m pytest backend/ -q
cd frontend && node subareas.test.mts && node organograma.test.mts && npx tsc --noEmit && npm run build
```
Expected: pytest verde; `6 testes OK` + os testes do organograma; `tsc` limpo; build sem erro.

- [ ] **Step 4: Varredura anti-regressão dos acentos**

Run: `cd egps_analysis/app && grep -rn "Em ingestao\|Concluido\|Migracao\|Priorizacao" frontend/src backend/main.py | grep -v "^Binary" | head`
Expected: **zero** linhas. Variantes sem acento de strings de status/etapa quebram silenciosamente a comparação com os dados gravados (ver histórico de patches ASCII no `main.py`).

- [ ] **Step 5: Conferência final de números no app rodando**

- Resumo → linha Total da tabela nova == total de EGPs do recorte "Indicium + dependências" na aba EGPs.
- Soma dos chips de sub-área na aba EGPs (sem outros filtros) == total de EGPs do recorte.
- "Sem sub-área" deve estar **baixo** (só quem não tem responsável) — se estiver alto, há grafia fora do cadastro: cadastre a pessoa em Gestão → Responsáveis BV.

- [ ] **Step 6: Commit**

```bash
git add egps_analysis/app/README.md CONTEXT.md
git commit -m "docs(app): sub-area BV nas decisoes de design e no glossario"
```

---

## Deploy (só com autorização explícita do usuário)

Não faz parte da implementação. Quando o usuário pedir: dev via `egps_analysis/app/deploy_dev.sh`, prod via Bitbucket Pipelines na `main` (ver `egps_analysis/app/docs/DEPLOY.md`). Depois de qualquer deploy, **verificar o artefato deployado** (hash do bundle + marcador no `main.py`): um deploy SUCCEEDED pode servir código velho.
