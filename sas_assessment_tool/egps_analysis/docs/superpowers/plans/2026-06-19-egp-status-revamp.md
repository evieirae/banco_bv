# Revamp do status de EGP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Novo vocabulário de status de EGP (7, manual, +Despriorizado e Contabilizado/+Migrado), Removido/Despriorizado como banda no funil, remover o funil "Progresso Projetos", e status editável inline na lista de EGPs.

**Architecture:** Mudança no app (backend FastAPI `main.py` + frontend React/TS) + 1 UPDATE de recapitalização em `sas_egp_pipeline`. O funil de Migração mantém as 9 etapas e a lógica de empilhamento; muda só o vocabulário e a regra de banda. Sem `publish_to_databricks.py`, sem republish.

**Tech Stack:** Python/FastAPI; React 18 + TS + Vite (tsc strict); Databricks SQL (perfil `bv`, catálogo `bv_dev_db`); testes Python como script (`python <file>.py`).

**Spec:** `egps_analysis/docs/superpowers/specs/2026-06-19-egp-status-revamp-design.md`

**Convenções:** commits **sem** `Co-Authored-By`; branch `import/project-sas`; migração de dados e deploy = **gate humano** (não executar sem OK).

---

## File Structure

| Arquivo | Mudança |
|---|---|
| `egps_analysis/app/backend/main.py` | `STATUS_PROJETO` (7), `_funnel_bars` (BANDS+recase), `proj_funnel`/`funis` (remove progresso, `migr` exclui BANDS), `PIPELINE_PROJETO` (sem progresso), `EgpPipe`/`egp_pipeline` (migração só), `egp` detalhe (sem progresso), `egp_readiness` (+status) |
| `egps_analysis/app/test_funnel_bars.py` | **criar** — unit do `_funnel_bars` (banda + taper) |
| `egps_analysis/app/frontend/src/pipeline.ts` | `STATUS_PROJETO` 7, `SEG`/`SEG_ORDER` 7, `PIPELINE_PROJETO` sem progresso |
| `egps_analysis/app/frontend/src/types.ts` | `FunisPayload` sem `progresso`; `ReadinessRow.status`; `EgpDetail.pipeline` sem progresso |
| `egps_analysis/app/frontend/src/api.ts` | `egpPipeline({projeto, etapa?, status?})` |
| `egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx` | remove bloco Progresso; status com os 7 + tooltip |
| `egps_analysis/app/frontend/src/components/ReadinessView.tsx` | coluna Status editável inline |
| `egps_analysis/app/frontend/src/components/ResumoView.tsx` | remove card do funil Progresso |
| `egps_analysis/app/frontend/src/components/WavesView.tsx` | ajusta consumo de status (sem progresso) |
| `egps_analysis/app/frontend/src/styles.css` | token `--seg-migr*`; coluna status na readiness |
| `egps_analysis/_egp_status_migrate.py` | **criar** — UPDATE de recapitalização (gate humano) |

---

## Task 1: Backend — vocabulário, `_funnel_bars` (banda) e funis

**Files:** Modify `egps_analysis/app/backend/main.py`; Create `egps_analysis/app/test_funnel_bars.py`

- [ ] **Step 1: Teste do `_funnel_bars` (falha)**

Create `egps_analysis/app/test_funnel_bars.py`:

```python
"""Unit do _funnel_bars (banda p/ Removido/Despriorizado e Contabilizado; taper p/ os demais).
Roda como script: python egps_analysis/app/test_funnel_bars.py
Importa só a função pura (sem FastAPI/Databricks) via import do módulo backend.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
import importlib.util
spec = importlib.util.spec_from_file_location("_m", os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "main.py"))


def _load_funnel_bars():
    # carrega só o símbolo _funnel_bars do main.py sem executar o app inteiro seria complexo;
    # em vez disso, reimplementamos a expectativa e comparamos com o módulo se importável.
    import main  # noqa
    return main._funnel_bars


STAGES = ["E0", "E1", "E2", "E3"]


def test_taper_em_andamento():
    fb = _load_funnel_bars()
    bars = fb(STAGES, [(2, "Em Andamento", 1)])  # EGP na etapa rank 2
    seg = {b["etapa"]: b["seg"] for b in bars}
    assert seg["E0"] == {"Concluído": 1}
    assert seg["E1"] == {"Concluído": 1}
    assert seg["E2"] == {"Em Andamento": 1}
    assert seg["E3"] == {"A Iniciar": 1}


def test_banda_removido_em_todas_colunas():
    fb = _load_funnel_bars()
    bars = fb(STAGES, [(2, "Removido", 1)])
    for b in bars:
        assert b["seg"] == {"Removido": 1}, b


def test_banda_despriorizado_em_todas_colunas():
    fb = _load_funnel_bars()
    bars = fb(STAGES, [(1, "Despriorizado e Contabilizado", 1)])
    for b in bars:
        assert b["seg"] == {"Despriorizado e Contabilizado": 1}, b


def test_migrado_so_na_etapa():
    fb = _load_funnel_bars()
    bars = fb(STAGES, [(3, "Migrado", 1)])
    seg = {b["etapa"]: b["seg"] for b in bars}
    assert seg["E0"] == {"Concluído": 1}
    assert seg["E3"] == {"Migrado": 1}


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t(); print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1; print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passaram")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app && python3 test_funnel_bars.py`
Expected: falha (importar `main` pode exigir deps; se `import main` falhar por FastAPI ausente, instale no venv `egps_analysis/app/venv` ou rode com ele: `venv/bin/python test_funnel_bars.py`). Com o `_funnel_bars` atual, `test_banda_*` falham (hoje deriva "Removido e Contabilizado", não banda).

- [ ] **Step 3: Atualizar `STATUS_PROJETO`, `PIPELINE_PROJETO` e `_funnel_bars`**

Em `main.py`, trocar `STATUS_PROJETO = ["A iniciar", "Em andamento", "Concluído", "Block", "Removido"]` por:

```python
STATUS_PROJETO = ["A Iniciar", "Em Andamento", "Concluído", "Block", "Removido",
                  "Despriorizado e Contabilizado", "Migrado"]
BANDS = {"Removido", "Despriorizado e Contabilizado"}  # refletem em todas as colunas do funil
```

Remover a chave `"progresso"` de `PIPELINE_PROJETO` (manter só `"migracao"`).

Trocar o corpo de `_funnel_bars` (a parte do loop) por:

```python
def _funnel_bars(stages, items):
    """Barras empilhadas. Removido/Despriorizado e Contabilizado = banda (todas as colunas);
    demais: j<i=Concluído, j==i=status, j>i=A Iniciar."""
    bars = []
    for j in range(len(stages)):
        seg = {}
        for i, st, w in items:
            if st in BANDS:
                k = st
            elif j < i:
                k = "Concluído"
            elif j == i:
                k = st
            else:
                k = "A Iniciar"
            seg[k] = seg.get(k, 0) + w
        bars.append({"etapa": stages[j], "seg": seg})
    return bars
```

- [ ] **Step 4: Ajustar `proj_funnel` / `funis` / ingestão**

No `funis()`: em `proj_funnel`, trocar `stt = r.get(st_col) or "A iniciar"` por `"A Iniciar"`, e a contagem `if et == stages[-1] and stt != "Removido":` por `if et == stages[-1] and stt not in BANDS:`. Na seção de ingestão, trocar `"Em andamento"` por `"Em Andamento"` no `items.append((rk - 1, "Concluído" if rk >= 3 else "Em Andamento", n))`. No `return`, **remover** a entrada `"progresso": proj_funnel(PIPELINE_PROJETO["progresso"], ...)` → retornar só `{"migracao": ..., "ingestao": ...}`.

- [ ] **Step 5: Rodar o teste e ver passar**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app && venv/bin/python test_funnel_bars.py` (ou `python3` se as deps existirem)
Expected: `4/4 passaram`, exit 0.

- [ ] **Step 6: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/backend/main.py egps_analysis/app/test_funnel_bars.py
git commit -m "feat(egp-status): vocabulário 7 + banda no funil + remove funil progresso"
```

---

## Task 2: Backend — PATCH, detalhe e readiness

**Files:** Modify `egps_analysis/app/backend/main.py`

- [ ] **Step 1: `EgpPipe` + `egp_pipeline` só migração**

Em `EgpPipe`, dar default ao funil: `funil: str = "migracao"`. Em `egp_pipeline`, trocar `if p.funil not in ("migracao", "progresso"):` por `if p.funil != "migracao":` (mensagem: "só funil migracao"). O resto do upsert/auditoria permanece.

- [ ] **Step 2: `egp` detalhe sem progresso**

No endpoint de detalhe `/api/egp`, onde monta `pipeline` (`"migracao": {...}, "progresso": {...}`), remover a chave `"progresso"` (manter só `migracao: {etapa, status}`).

- [ ] **Step 3: `egp_readiness` devolve status + etapa**

No `egp_readiness`, após o SELECT principal (que agrupa por projeto), juntar o status do pipeline. Acrescentar ao SELECT um `LEFT JOIN {T_PIPE} p ON e.projeto = p.projeto` **não** é trivial com o GROUP BY atual; em vez disso, buscar o pipeline à parte e mesclar em Python:

```python
    pipe = run_sql(f"SELECT projeto, status_migracao, etapa_migracao FROM {T_PIPE}")
    pmap = {r["projeto"]: r for r in pipe}
    for r in rows:
        pr = pmap.get(r["projeto"])
        r["status"] = (pr or {}).get("status_migracao") or "A Iniciar"
        r["etapa"] = (pr or {}).get("etapa_migracao") or ""
```

(inserir antes do `return`; `rows` é a lista que já é devolvida). Se `T_PIPE` não existir ainda, `run_sql` levanta `HTTPException` — embrulhar em try/except como já é feito em `funis()`:

```python
    try:
        pipe = run_sql(f"SELECT projeto, status_migracao, etapa_migracao FROM {T_PIPE}")
    except HTTPException:
        pipe = []
```

- [ ] **Step 4: Sintaxe ok**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/backend && python3 -c "import ast; ast.parse(open('main.py').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/backend/main.py
git commit -m "feat(egp-status): PATCH/detalhe só migração + status na readiness"
```

---

## Task 3: Frontend — pipeline.ts, tipos e api

**Files:** Modify `pipeline.ts`, `types.ts`, `api.ts` (em `egps_analysis/app/frontend/src/`)

- [ ] **Step 1: `pipeline.ts`**

Trocar `STATUS_PROJETO` por:

```typescript
export const STATUS_PROJETO = ["A Iniciar", "Em Andamento", "Concluído", "Block", "Removido",
  "Despriorizado e Contabilizado", "Migrado"];
```

Remover a chave `progresso` de `PIPELINE_PROJETO` (manter só `migracao`, com as 9 etapas atuais). Trocar `SEG` e `SEG_ORDER` por (mantendo a estrutura `{bg,fg}` apontando para tokens):

```typescript
export const SEG: Record<string, { bg: string; fg: string }> = {
  "A Iniciar":                    { bg: "var(--seg-todo)",  fg: "var(--seg-todo-on)" },
  "Em Andamento":                 { bg: "var(--seg-wip)",   fg: "var(--seg-wip-on)" },
  "Concluído":                    { bg: "var(--seg-done)",  fg: "var(--seg-done-on)" },
  "Block":                        { bg: "var(--seg-block)", fg: "var(--seg-block-on)" },
  "Removido":                     { bg: "var(--seg-rem)",   fg: "var(--seg-rem-on)" },
  "Despriorizado e Contabilizado":{ bg: "var(--seg-remc)",  fg: "var(--seg-remc-on)" },
  "Migrado":                      { bg: "var(--seg-migr)",  fg: "var(--seg-migr-on)" },
};
export const SEG_ORDER = ["A Iniciar", "Em Andamento", "Concluído", "Block", "Migrado",
  "Removido", "Despriorizado e Contabilizado"];
```

- [ ] **Step 2: `types.ts`**

Em `FunisPayload`, remover `progresso: FunnelData;` (manter `migracao` e `ingestao`). Em `ReadinessRow`, acrescentar `status: string;` e `etapa: string;`. Em `EgpDetail`, mudar `pipeline?` para `{ migracao: { etapa: string | null; status: string | null } }` (remover `progresso`). (Conferir e ajustar `EgpPipelineState` se referenciar progresso.)

- [ ] **Step 3: `api.ts`**

Trocar a assinatura de `egpPipeline` para não exigir `funil`:

```typescript
  egpPipeline: (body: { projeto: string; etapa?: string | null; status?: string | null }) =>
    fetch("api/egp-pipeline", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ funil: "migracao", ...body }),
    }).then(json<{ ok: boolean; etapa: string | null; status: string | null }>),
```

- [ ] **Step 4: Commit** (build completo vem na Task 6)

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/frontend/src/pipeline.ts egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/api.ts
git commit -m "feat(app): status 7 + SEG + tipos/api (egp-status revamp)"
```

---

## Task 4: Frontend — EgpDetailPanel (só migração) + ResumoView (sem progresso) + WavesView

**Files:** Modify `EgpDetailPanel.tsx`, `ResumoView.tsx`, `WavesView.tsx`

- [ ] **Step 1: `EgpDetailPanel.tsx`** — trocar o bloco que itera `[["migracao","Funil de Migração SAS"],["progresso","Progresso Projetos"]]` por **só** migração:

```tsx
        {(() => {
          const funil = "migracao" as const;
          const cur = (det.pipeline ?? EMPTY_PIPE)[funil];
          return (
            <div className="pipe-ed" key={funil}>
              <span className="pipe-tit">Funil de Migração SAS</span>
              <select value={cur.etapa ?? ""} onChange={(e) => pipeMut.mutate({ etapa: e.target.value })}>
                <option value="">— etapa —</option>
                {PIPELINE_PROJETO[funil].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select value={cur.status ?? ""} disabled={!cur.etapa} title={STATUS_HELP}
                onChange={(e) => pipeMut.mutate({ status: e.target.value })}>
                <option value="">— status —</option>
                {STATUS_PROJETO.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          );
        })()}
```

Ajustar `EMPTY_PIPE` para `{ migracao: { etapa: null, status: null } }`. Ajustar `pipeMut` para `mutationFn: (v: { etapa?: string; status?: string }) => api.egpPipeline({ projeto, ...v })` e o `onMutate` otimista para só `migracao`. Definir no topo do arquivo a constante:

```tsx
const STATUS_HELP = "A Iniciar: habilitado, não começou · Em Andamento: trabalhando · Concluído: concluiu a etapa · Block: bloqueado, segue no backlog · Removido: tirado do backlog sem ingestão · Despriorizado e Contabilizado: já houve ingestão/validação DES e foi despriorizado · Migrado";
```

- [ ] **Step 2: `ResumoView.tsx`** — remover a linha `<FunnelChart title="Progresso Projetos" data={F.progresso} unidade="EGPs" />` (manter Migração + Ingestão).

- [ ] **Step 3: `WavesView.tsx`** — abrir o arquivo; onde consumir `progresso`/`PIPELINE_PROJETO.progresso`/status de projeto que dependa do funil progresso, ajustar para usar só `migracao`/`status`. Se não houver uso de progresso, nenhuma mudança (apenas confirmar que compila com os tipos novos).

- [ ] **Step 4: Commit** (build na Task 6)

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx egps_analysis/app/frontend/src/components/ResumoView.tsx egps_analysis/app/frontend/src/components/WavesView.tsx
git commit -m "feat(app): detalhe só funil Migração + remove card Progresso"
```

---

## Task 5: Frontend — coluna Status editável inline na lista de EGPs + CSS

**Files:** Modify `ReadinessView.tsx`, `styles.css`

- [ ] **Step 1: `ReadinessView.tsx`** — importar `useMutation, useQueryClient` e `STATUS_PROJETO`, `SEG`; criar uma mutation que grava o status sem expandir:

```tsx
  const qc = useQueryClient();
  const pipeMut = useMutation({
    mutationFn: (v: { projeto: string; status: string }) => api.egpPipeline(v),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["egp-readiness"] }); qc.invalidateQueries({ queryKey: ["funis"] }); },
  });
```

No cabeçalho da tabela (`rd-thead`), acrescentar uma coluna `<div>Status</div>` (após "Área" ou antes de "Prontidão" — escolher posição estável). Na linha (`rd-trow`), acrescentar uma célula com o dropdown, parando a propagação do clique (pra não expandir):

```tsx
                  <div className="rd-status" onClick={(e) => e.stopPropagation()}>
                    <select value={r.status} title={STATUS_HELP}
                      style={{ background: SEG[r.status]?.bg, color: SEG[r.status]?.fg }}
                      onChange={(e) => pipeMut.mutate({ projeto: r.projeto, status: e.target.value })}>
                      {STATUS_PROJETO.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </div>
```

Definir `STATUS_HELP` (mesmo texto da Task 4) no topo. Atualizar o `grid-template-columns` de `.rd-thead, .rd-trow` em `styles.css` para incluir a coluna nova (uma faixa ~150px).

- [ ] **Step 2: `styles.css`** — (a) adicionar os tokens de cor do "Migrado" no `:root` e no tema claro, seguindo o padrão dos demais `--seg-*` (verde-escuro distinto do `--seg-done`):

```css
  --seg-migr: #0b6b3a; --seg-migr-on: #ffffff;
```

(adicionar análogo no bloco `[data-theme="light"]` se os outros `--seg-*` forem redefinidos lá). (b) ajustar o `grid-template-columns` da readiness (regra `.rd-thead, .rd-trow`) inserindo a faixa da coluna Status; (c) regra `.rd-status select { ... }` mínima (largura 100%, borda sutil). Conferir os tokens `--seg-*` existentes antes de duplicar.

- [ ] **Step 3: Build completo (tsc strict + vite)**

Run: `cd /home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/app/frontend && npm run build 2>&1 | tail -15`
Expected: `tsc -b && vite build` sem erro.

- [ ] **Step 4: Commit**

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git add egps_analysis/app/frontend/src/components/ReadinessView.tsx egps_analysis/app/frontend/src/styles.css
git commit -m "feat(app): coluna Status editável inline na lista de EGPs"
```

---

## Task 6: Migração de dados (GATE HUMANO — não executar sem OK)

**Files:** Create `egps_analysis/_egp_status_migrate.py`

- [ ] **Step 1: Script de migração (recapitalização)** — read-only seguro: só recapitaliza, idempotente.

```python
#!/usr/bin/env python3
"""TEMP: recapitaliza status_migracao em sas_egp_pipeline (Em andamento->Em Andamento,
A iniciar->A Iniciar). NÃO toca Concluído/Block/Removido/NULL. Idempotente.
Uso: egps_analysis/venv/bin/python egps_analysis/_egp_status_migrate.py [--apply]
"""
import sys, time
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState, Disposition, Format
W = WorkspaceClient(profile="bv"); WID = "5922c26f81f1bbdd"; FQ = "bv_dev_db.monitoramento_sas"
def q(sql):
    r = W.statement_execution.execute_statement(statement=sql, warehouse_id=WID, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2); r = W.statement_execution.get_statement(statement_id=r.statement_id)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(r.status.error if r.status else "?")
    return r.result.data_array or []
RENAMES = [("Em andamento", "Em Andamento"), ("A iniciar", "A Iniciar")]
apply = "--apply" in sys.argv
for old, new in RENAMES:
    n = q(f"SELECT count(*) FROM {FQ}.sas_egp_pipeline WHERE status_migracao = '{old}'")[0][0]
    print(f"{old!r} -> {new!r}: {n} linha(s)")
    if apply and int(n) > 0:
        q(f"UPDATE {FQ}.sas_egp_pipeline SET status_migracao = '{new}' WHERE status_migracao = '{old}'")
        print(f"  aplicado.")
print("dry-run (use --apply para gravar)" if not apply else "ok")
```

- [ ] **Step 2: Snapshot pré + dry-run** (sem OK do usuário, só leitura/dry):

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
egps_analysis/venv/bin/python egps_analysis/_status_prod_snapshot.py pre2
egps_analysis/venv/bin/python egps_analysis/_egp_status_migrate.py
```

- [ ] **Step 3: Aplicar (SÓ com OK humano):** `egps_analysis/venv/bin/python egps_analysis/_egp_status_migrate.py --apply`, depois re-snapshot `... _status_prod_snapshot.py post2` e conferir que só `Em andamento`→`Em Andamento` mudou.

---

## Task 7: Deploy (GATE HUMANO — não executar sem OK)

Sem republish. Após Tasks 1–6:

```bash
cd egps_analysis/app/frontend && npm run build && cd ..
databricks sync . /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas \
  --exclude 'frontend/node_modules/**' --exclude '.databricks/**' --profile bv
databricks apps deploy monitoramento-sas \
  --source-code-path /Workspace/Users/lucas.muller@indicium.tech/monitoramento-sas --profile bv
```

Verificação: aba EGPs com coluna Status editável; detalhe sem "Progresso Projetos"; landing sem o funil Progresso; funil de Migração mostra os 7 status (Removido/Despriorizado como banda quando houver).

---

## Self-Review

- **Cobertura do spec:** §2 vocabulário→T1/T3; §3 banda/`_funnel_bars`→T1 (+teste); §4 dados→T6; §5 backend (PATCH/detalhe/readiness/funis)→T1/T2; §6 frontend→T3/T4/T5; §7 deploy→T6/T7; §8 aceite→T5(build)+T6(snapshot)+T7(smoke). Sem lacunas.
- **Placeholders:** nenhum — código concreto nos passos novos; edições mecânicas com instrução exata + arquivo já lido.
- **Consistência de tipos:** `STATUS_PROJETO` (7) idêntico em `pipeline.ts` e `main.py`; `SEG` keys == `STATUS_PROJETO` + nada derivado extra (Concluído é status); `BANDS` igual nos dois lados conceitualmente; `egpPipeline({projeto,etapa?,status?})` usado em EgpDetailPanel e ReadinessView; `ReadinessRow.status` consumido na coluna nova; `FunisPayload` sem `progresso` consumido em ResumoView.
