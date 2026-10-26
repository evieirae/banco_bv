# Priorização — filtros fixos, pin de mês e resumo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Travar o recorte da aba Priorização (Indicium + dependências, todas as áreas, 400 inputs/mês), permitir fixar manualmente um EGP num mês (persistido), e mostrar 3 cards de resumo (migrados neste mês / bloqueados / habilitados).

**Architecture:** A lógica de empacotamento por capacidade sai do endpoint para um módulo puro (`priorizacao_logic.py`), testável sem DB (espelha `prioridades_logic.py`). `GET /api/priorizacao` passa a ler pins da coluna nova `mes_prioridade` em `sas_egp_pipeline`, chamar a função pura e devolver `resumo`. Um novo `PATCH /api/priorizacao/mes` (gated a gestão) grava/limpa o pin. O frontend remove os controles de filtro, mostra rótulo fixo + cards, e (só gestão) um seletor de mês por EGP.

**Tech Stack:** FastAPI + Databricks SQL (backend), React + TanStack Query + Vite/TS (frontend), pytest (backend logic).

---

## ⚠️ Guardrails deste repo (LEIA antes de executar)

- **Sem `git commit`/`push` sem o usuário pedir explicitamente.** Os passos de commit abaixo só rodam **após OK do usuário** (pergunte antes de cada commit, ou agrupe no fim e peça autorização). **Sem trailer `Co-Authored-By`.**
- **Sem deploy sem consentimento.** A coluna nova `mes_prioridade` é criada em produção (`bv_dev_db.monitoramento_sas`) na primeira chamada que tocar `_ensure_pipe_table()` **rodando contra o warehouse** — não force isso sem OK. Os testes desta feature são offline (não tocam prod).
- **`backend/main.py` é grande e tem context-guard** — edite via replacement direcionado (os `old_string` exatos estão nos passos) e revise com `git diff`.
- Rodar comandos de backend a partir de `egps_analysis/app/backend/`; usar o venv `egps_analysis/app/venv`.

## File Structure

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `backend/priorizacao_logic.py` | Empacotamento puro por capacidade + contagem de resumo (sem DB) | **Criar** |
| `backend/test_priorizacao_logic.py` | Testes pytest da lógica pura | **Criar** |
| `backend/main.py` | `_ensure_pipe_table` (+coluna), `_migrados_mes` (query), `/api/priorizacao` (usa a fn pura + resumo), `PATCH /api/priorizacao/mes` | **Modificar** |
| `frontend/src/types.ts` | `PrioResumo`, `PrioEgp.mes_pin`, `PriorizacaoPayload.resumo` | **Modificar** |
| `frontend/src/api.ts` | `priorizacao()` sem args, `priorizacaoSetMes()` | **Modificar** |
| `frontend/src/components/WavesView.tsx` | Remove filtros → rótulo fixo; 3 cards; controle de mover (gestão) | **Reescrever** |
| `frontend/src/styles.css` | Estilos do rótulo/cards/controle mover | **Modificar** |

---

## Task 1: Módulo puro de empacotamento + testes (TDD)

**Files:**
- Create: `backend/priorizacao_logic.py`
- Test: `backend/test_priorizacao_logic.py`

- [ ] **Step 1: Escrever os testes que falham**

Create `backend/test_priorizacao_logic.py`:

```python
from priorizacao_logic import plan_months, resumo_counts

# Cenário base (cap=3):
#   A:{a,b}(2)  B:{b,c}(2, compartilha b)  C:{d}(1)  D:{e,f,g,h}(4, > cap)
INPUTS = {"A": {"a", "b"}, "B": {"b", "c"}, "C": {"d"}, "D": {"e", "f", "g", "h"}}
ORDER = ["A", "B", "C", "D"]


def _names(month):
    return [e["projeto"] for e in month["egps"]]


def test_sem_pins_empacota_como_o_algoritmo_atual():
    meses = plan_months(ORDER, INPUTS, {}, cap=3)
    # m1: A(+a,b)=2, B(+c)=1 -> {a,b,c}; m2: C(+d)=1; m3: D solo (excede)
    assert [_names(m) for m in meses] == [["A", "B"], ["C"], ["D"]]
    assert meses[0]["inputs"] == {"a", "b", "c"}
    assert meses[0]["egps"][0]["n_inputs_novos"] == 2   # A
    assert meses[0]["egps"][1]["n_inputs_novos"] == 1   # B (dedupe: b já contado)
    assert meses[2]["egps"][0]["excede"] is True        # D sozinho > cap
    assert meses[2]["egps"][0]["pinned"] is False


def test_pin_puxa_egp_para_mes_1():
    meses = plan_months(ORDER, INPUTS, {"C": 1}, cap=3)
    # m1: C(pin, +d), A(+a,b) -> {d,a,b}; m2: B(+c); m3: D solo
    assert [_names(m) for m in meses] == [["C", "A"], ["B"], ["D"]]
    assert meses[0]["egps"][0]["pinned"] is True        # C fixado vem primeiro
    assert meses[0]["inputs"] == {"a", "b", "d"}


def test_pin_que_estoura_o_teto_marca_excede_e_nao_enche_o_mes():
    meses = plan_months(ORDER, INPUTS, {"D": 1}, cap=3)
    # m1: D(pin, 4 > cap) sozinho; automáticos NÃO entram no m1
    assert _names(meses[0]) == ["D"]
    assert meses[0]["egps"][0]["excede"] is True
    assert len(meses[0]["inputs"]) == 4                 # acima do teto (guia)
    assert [_names(m) for m in meses[1:]] == [["A", "B"], ["C"]]


def test_pin_para_mes_novo_ao_final_com_dedupe():
    meses = plan_months(ORDER, INPUTS, {"A": 3}, cap=3)
    # m1: B(+b,c), C(+d); m2: D solo; m3: A(pin) -> só {a} (b já ingerido no m1)
    assert [_names(m) for m in meses] == [["B", "C"], ["D"], ["A"]]
    assert meses[2]["egps"][0]["pinned"] is True
    assert meses[2]["egps"][0]["n_inputs_novos"] == 1   # dedupe reduz A para {a}


def test_meses_vazios_sao_removidos():
    # pin isolado no mês 2 sem nada no mês 1 automático? Garante contiguidade.
    meses = plan_months(["A"], {"A": {"a"}}, {"A": 2}, cap=3)
    assert len(meses) == 1 and _names(meses[0]) == ["A"]


def test_resumo_counts_complemento():
    r = resumo_counts(["A", "B", "C", "D", "E"], {"B", "C"})
    assert r == {"total": 5, "bloqueados": 2, "habilitados": 3}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd egps_analysis/app/backend && ../venv/bin/pytest test_priorizacao_logic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'priorizacao_logic'`.

- [ ] **Step 3: Implementar o módulo puro**

Create `backend/priorizacao_logic.py`:

```python
"""Lógica pura (sem DB) do empacotamento por capacidade da aba Priorização.
Testável offline; consumida por main.py:/api/priorizacao. Espelha o padrão de
prioridades_logic.py (funções puras + test_*.py)."""


def plan_months(order, egp_inputs, pin, cap):
    """Empacota EGPs em meses de ≤ cap inputs DISTINTOS a ingerir, com dedupe global
    (input conta no 1º mês em que aparece) e pins absolutos (teto vira guia).

    order      : list[str]      EGPs já ordenados por prioridade (viab, -fanout, esforço, nome).
    egp_inputs : dict[str, set] inputs pendentes distintos por EGP.
    pin        : dict[str, int] mês fixado (>=1) por EGP fixado (só os fixados).
    cap        : int            capacidade-guia por mês.

    Retorna list de meses contíguos (vazios removidos), cada um:
      {"inputs": set, "egps": [{"projeto", "n_inputs_novos", "excede", "pinned"}]}.
    Dentro do mês: pins primeiro (na ordem de `order`), depois os automáticos.
    """
    cap = max(1, int(cap))
    pinned = [pj for pj in order if pin.get(pj)]
    free = [pj for pj in order if not pin.get(pj)]
    ingested = set()
    months = {}                       # m(int>=1) -> {"inputs": set, "egps": []}
    max_pin = max(pin.values()) if pin else 0

    def _add(cm, pj, marginal, excede, pinned_flag):
        cm["inputs"] |= marginal
        cm["egps"].append({"projeto": pj, "n_inputs_novos": len(marginal),
                           "excede": excede, "pinned": pinned_flag})

    m = 1
    free_i = 0
    while free_i < len(free) or m <= max_pin:
        cm = months.setdefault(m, {"inputs": set(), "egps": []})
        # (a) pins deste mês, na ordem de prioridade
        for pj in pinned:
            if pin[pj] == m:
                marginal = egp_inputs.get(pj, set()) - ingested
                _add(cm, pj, marginal, len(marginal) > cap, True)
                ingested |= marginal
        # (b) automáticos até o teto (guia)
        while free_i < len(free):
            pj = free[free_i]
            marginal = egp_inputs.get(pj, set()) - ingested
            novos = len(marginal)
            if novos > cap:                      # EGP sozinho excede -> mês próprio
                if cm["egps"]:
                    break                        # não crava num mês já ocupado -> próximo
                _add(cm, pj, marginal, True, False)
                ingested |= marginal
                free_i += 1
                break                            # fecha o mês (over-cap)
            if cm["egps"] and len(cm["inputs"]) + novos > cap:
                break                            # não cabe -> próximo mês
            _add(cm, pj, marginal, False, False)
            ingested |= marginal
            free_i += 1
        m += 1

    # remove meses vazios; ordem crescente (renumeração fica com o caller: mes = i+1)
    return [months[k] for k in sorted(months) if months[k]["egps"]]


def resumo_counts(frontier, blocked):
    """total = nº de EGPs do recorte; bloqueados = interseção; habilitados = complemento."""
    total = len(frontier)
    bloq = len(set(frontier) & set(blocked))
    return {"total": total, "bloqueados": bloq, "habilitados": total - bloq}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd egps_analysis/app/backend && ../venv/bin/pytest test_priorizacao_logic.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/backend/priorizacao_logic.py egps_analysis/app/backend/test_priorizacao_logic.py
git commit -m "feat(app): priorizacao — lógica pura de empacotamento (pin + resumo) + testes"
```

---

## Task 2: Backend — coluna `mes_prioridade` + helper `_migrados_mes`

**Files:**
- Modify: `backend/main.py` (`_ensure_pipe_table`, ~linhas 1406-1418; e adicionar `_migrados_mes` logo antes de `@app.get("/api/priorizacao")`, ~linha 1681)

- [ ] **Step 1: Adicionar o guard idempotente da coluna em `_ensure_pipe_table`**

Em `main.py`, localize o guard de `responsavel` dentro de `_ensure_pipe_table` e adicione o guard de `mes_prioridade` logo depois.

Replace:

```python
    try:
        run_sql(f"SELECT responsavel FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (responsavel STRING)", want_rows=False)
```

With:

```python
    try:
        run_sql(f"SELECT responsavel FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (responsavel STRING)", want_rows=False)
    try:
        run_sql(f"SELECT mes_prioridade FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (mes_prioridade INT)", want_rows=False)
```

- [ ] **Step 2: Adicionar `_migrados_mes` acima do endpoint `/api/priorizacao`**

Localize a linha `@app.get("/api/priorizacao")` e insira **imediatamente antes** dela:

```python
def _migrados_mes(frontier):
    """Nº de EGPs do recorte cujo status de migração virou 'Migrado' NESTE mês de
    calendário (via auditoria T_PIPE_AUD). KPI de velocidade — só 'Migrado' (não conta
    Removido/Despriorizado, que são saídas de escopo). Robusto a falha de SQL -> 0."""
    if not frontier:
        return 0
    inl = ", ".join(sql_lit(pj) for pj in frontier)
    try:
        r = run_sql(
            f"SELECT count(DISTINCT projeto) AS n FROM {T_PIPE_AUD} "
            f"WHERE funil = 'migracao' AND campo = 'status' AND valor_novo = 'Migrado' "
            f"AND substr(ts, 1, 7) = date_format(current_date(), 'yyyy-MM') "
            f"AND projeto IN ({inl})")
        return int(r[0]["n"]) if r and r[0].get("n") is not None else 0
    except HTTPException:
        return 0
```

- [ ] **Step 3: Verificar import do módulo (compila)**

Run: `cd egps_analysis/app/backend && ../venv/bin/python -c "import ast; ast.parse(open('main.py').read()); print('ok')"`
Expected: `ok` (sintaxe válida; sem tocar em DB).

- [ ] **Step 4: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): priorizacao — coluna mes_prioridade (idempotente) + _migrados_mes"
```

---

## Task 3: Backend — `/api/priorizacao` usa a função pura + devolve `resumo`/`mes_pin`

**Files:**
- Modify: `backend/main.py` (topo: import; endpoint `/api/priorizacao`, ~linhas 1733-1787)

- [ ] **Step 1: Importar a lógica pura**

Localize a linha `import ingest  # núcleo da ingestão in-app` e adicione **logo abaixo**:

```python
from priorizacao_logic import plan_months, resumo_counts
```

- [ ] **Step 2: Substituir o miolo do endpoint (resp_of/blocked/packing/return)**

No corpo de `def priorizacao(...)`, substitua o bloco que vai de `try: _ensure_pipe_table()` até o `return {...}` final.

Replace:

```python
    try:
        _ensure_pipe_table()
        resp_of = {r["projeto"]: r.get("responsavel") for r in run_sql(f"SELECT projeto, responsavel FROM {T_PIPE}")}
    except HTTPException:
        resp_of = {}
    try:
        blocked = _blocking()["blocked"]
    except HTTPException:
        blocked = set()

    def _viab(pj):
        # 0 = viável agora (não bloqueado; nada pendente OU tem pendência ingerível);
        # 1 = pendência só SAS/local (aguardando produtor); 2 = bloqueado por dependência.
        if pj in blocked:
            return 2
        if len(egp_inputs.get(pj, ())) == 0 or n_ingerivel.get(pj, 0) > 0:
            return 0
        return 1

    # ordem lexicográfica: viabilidade asc, fan-out desc, esforço asc, nome
    egps = sorted(frontier, key=lambda pj: (_viab(pj), -fanout.get(pj, 0), len(egp_inputs.get(pj, ())), pj))
    ingested = set()
    meses = []
    cur = {"inputs": set(), "egps": []}

    def _flush():
        nonlocal cur
        if cur["egps"]:
            meses.append(cur)
            cur = {"inputs": set(), "egps": []}

    def _row(pj, marginal, excede):
        return {"projeto": pj, "area": area_of.get(pj), "n_inputs_novos": len(marginal),
                "responsavel": resp_of.get(pj) or None, "excede": excede,
                "bloqueado": pj in blocked, "fan_out": fanout.get(pj, 0)}

    for pj in egps:
        marginal = egp_inputs.get(pj, set()) - ingested  # dedupe entre meses
        novos = len(marginal)
        if novos > cap:
            _flush()                 # EGP sozinho excede a capacidade -> mês próprio
            cur["inputs"] |= marginal
            cur["egps"].append(_row(pj, marginal, True))
            ingested |= marginal
            _flush()
            continue
        if cur["egps"] and len(cur["inputs"]) + novos > cap:
            _flush()                 # não cabe no mês atual -> abre o próximo
        cur["inputs"] |= marginal
        cur["egps"].append(_row(pj, marginal, False))
        ingested |= marginal
    _flush()
    out = [{"mes": i + 1, "n_inputs": len(m["inputs"]), "n_egps": len(m["egps"]), "egps": m["egps"]}
           for i, m in enumerate(meses)]
    return {"meses": out, "n_meses": len(out), "n_inputs": len(ingested), "n_egps": len(egps), "capacidade": cap}
```

With:

```python
    try:
        _ensure_pipe_table()
        pipe_rows = run_sql(f"SELECT projeto, responsavel, mes_prioridade FROM {T_PIPE}")
        resp_of = {r["projeto"]: r.get("responsavel") for r in pipe_rows}
        pin = {}
        for r in pipe_rows:
            pj, mp = r.get("projeto"), r.get("mes_prioridade")
            if pj in frontier and mp is not None and str(mp) != "":
                try:
                    mv = int(mp)
                except (TypeError, ValueError):
                    continue
                if mv >= 1:
                    pin[pj] = mv
    except HTTPException:
        resp_of, pin = {}, {}
    try:
        blocked = _blocking()["blocked"]
    except HTTPException:
        blocked = set()

    def _viab(pj):
        # 0 = viável agora (não bloqueado; nada pendente OU tem pendência ingerível);
        # 1 = pendência só SAS/local (aguardando produtor); 2 = bloqueado por dependência.
        if pj in blocked:
            return 2
        if len(egp_inputs.get(pj, ())) == 0 or n_ingerivel.get(pj, 0) > 0:
            return 0
        return 1

    # ordem lexicográfica: viabilidade asc, fan-out desc, esforço asc, nome
    order = sorted(frontier, key=lambda pj: (_viab(pj), -fanout.get(pj, 0), len(egp_inputs.get(pj, ())), pj))
    meses_raw = plan_months(order, egp_inputs, pin, cap)
    out = []
    for i, mth in enumerate(meses_raw):
        egps_out = []
        for e in mth["egps"]:
            pj = e["projeto"]
            egps_out.append({"projeto": pj, "area": area_of.get(pj),
                             "n_inputs_novos": e["n_inputs_novos"],
                             "responsavel": resp_of.get(pj) or None, "excede": e["excede"],
                             "bloqueado": pj in blocked, "fan_out": fanout.get(pj, 0),
                             "mes_pin": pin.get(pj)})
        out.append({"mes": i + 1, "n_inputs": len(mth["inputs"]),
                    "n_egps": len(egps_out), "egps": egps_out})
    resumo = resumo_counts(frontier, blocked)
    resumo["migrados_mes"] = _migrados_mes(frontier)
    total_inputs = sum(len(m["inputs"]) for m in meses_raw)
    return {"meses": out, "n_meses": len(out), "n_inputs": total_inputs,
            "n_egps": len(order), "capacidade": cap, "resumo": resumo}
```

- [ ] **Step 3: Verificar sintaxe**

Run: `cd egps_analysis/app/backend && ../venv/bin/python -c "import ast; ast.parse(open('main.py').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Rodar os testes da lógica pura de novo (regressão)**

Run: `cd egps_analysis/app/backend && ../venv/bin/pytest test_priorizacao_logic.py -v`
Expected: PASS (6 passed) — garante que o empacotamento extraído continua correto.

- [ ] **Step 5: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): priorizacao — endpoint usa fn pura + resumo (migrados/bloqueados/habilitados) + mes_pin"
```

---

## Task 4: Backend — `PATCH /api/priorizacao/mes` (fixar/limpar mês, gated)

**Files:**
- Modify: `backend/main.py` (adicionar model + endpoint logo após o `def priorizacao(...)` retornar; antes do próximo `@app.` — ~linha 1789)

- [ ] **Step 1: Adicionar model + endpoint**

Insira, após o fim da função `priorizacao` (antes do próximo decorator `@app.`):

```python
class PrioMesPin(BaseModel):
    projeto: str
    mes: int | None = None


@app.patch("/api/priorizacao/mes")
def priorizacao_set_mes(p: PrioMesPin):
    """Fixa (mes>=1) ou limpa (mes=null) o mês de prioridade de 1 EGP na aba Priorização.
    Pin absoluto (o teto de capacidade vira guia). Só gestão (bv_users). Auditado."""
    _require_gestao()
    if p.mes is not None and (not isinstance(p.mes, int) or isinstance(p.mes, bool) or p.mes < 1):
        raise HTTPException(400, "mes deve ser inteiro >= 1 ou null")
    _ensure_pipe_table()
    cur = run_sql(f"SELECT mes_prioridade AS mp FROM {T_PIPE} WHERE projeto = {sql_lit(p.projeto)}")
    old = cur[0].get("mp") if cur else None
    mes_lit = "NULL" if p.mes is None else str(int(p.mes))   # int literal seguro (sem quoting)
    run_sql(
        f"MERGE INTO {T_PIPE} t USING (SELECT {sql_lit(p.projeto)} AS projeto) s ON t.projeto = s.projeto "
        f"WHEN MATCHED THEN UPDATE SET t.mes_prioridade = {mes_lit}, "
        f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (projeto, mes_prioridade, updated_by, updated_at) VALUES "
        f"({sql_lit(p.projeto)}, {mes_lit}, current_user(), cast(current_timestamp() AS STRING))",
        want_rows=False)
    if _norm(old) != _norm(p.mes):
        run_sql(
            f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(p.projeto)}, 'migracao', 'mes_prioridade', "
            f"{sql_lit(_norm(old))}, {sql_lit(_norm(p.mes))}, current_user(), "
            f"cast(current_timestamp() AS STRING))", want_rows=False)
    return {"ok": True, "projeto": p.projeto, "mes": p.mes}
```

- [ ] **Step 2: Verificar sintaxe**

Run: `cd egps_analysis/app/backend && ../venv/bin/python -c "import ast; ast.parse(open('main.py').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Rodar toda a suíte do backend (nada quebrou)**

Run: `cd egps_analysis/app/backend && ../venv/bin/pytest -q`
Expected: PASS em todos (test_priorizacao_logic, test_ingest, test_obo_dispatch, test_prioridades_logic).

- [ ] **Step 4: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/backend/main.py
git commit -m "feat(app): priorizacao — PATCH /api/priorizacao/mes (fixar/limpar mês, gated gestão)"
```

---

## Task 5: Frontend — tipos (`types.ts`)

**Files:**
- Modify: `frontend/src/types.ts` (interfaces `PrioEgp`/`PrioMes`/`PriorizacaoPayload`, ~linhas 194-217)

- [ ] **Step 1: Adicionar `PrioResumo`, `mes_pin` e `resumo`**

Replace:

```ts
export interface PrioEgp {
  projeto: string;
  area: string | null;
  n_inputs_novos: number;
  responsavel: string | null;
  excede: boolean;
  bloqueado: boolean;
  fan_out: number;   // nº de EGPs do recorte que consomem o output deste (alavancagem)
}
```

With:

```ts
export interface PrioEgp {
  projeto: string;
  area: string | null;
  n_inputs_novos: number;
  responsavel: string | null;
  excede: boolean;
  bloqueado: boolean;
  fan_out: number;   // nº de EGPs do recorte que consomem o output deste (alavancagem)
  mes_pin: number | null;   // mês fixado manualmente (null = automático)
}

export interface PrioResumo {
  migrados_mes: number;   // EGPs migrados NESTE mês de calendário (velocidade)
  bloqueados: number;
  habilitados: number;    // = total - bloqueados
  total: number;
}
```

Replace:

```ts
export interface PriorizacaoPayload {
  meses: PrioMes[];
  n_meses: number;
  n_inputs: number;
  n_egps: number;
  capacidade: number;
}
```

With:

```ts
export interface PriorizacaoPayload {
  meses: PrioMes[];
  n_meses: number;
  n_inputs: number;
  n_egps: number;
  capacidade: number;
  resumo: PrioResumo;
}
```

- [ ] **Step 2: Commit (só com OK do usuário)** — junto com Task 6 (typecheck só compila com api.ts pronto). Pule o commit isolado aqui.

---

## Task 6: Frontend — API (`api.ts`)

**Files:**
- Modify: `frontend/src/api.ts` (`priorizacao`, ~linhas 125-132)

- [ ] **Step 1: `priorizacao()` sem args (recorte fixo) + `priorizacaoSetMes()`**

Replace:

```ts
  priorizacao: (p: { scope: string; area?: string; deps: string; capacidade: number }) => {
    const q = new URLSearchParams();
    q.set("scope", p.scope);
    if (p.area) q.set("area", p.area);
    q.set("deps", p.deps);
    q.set("capacidade", String(p.capacidade));
    return fetch(`api/priorizacao?${q}`).then(json<PriorizacaoPayload>);
  },
```

With:

```ts
  // Recorte FIXO da aba Priorização: Indicium + dependências, todas as áreas, 400 inputs/mês.
  priorizacao: () =>
    fetch("api/priorizacao?scope=indi&deps=transitive&capacidade=400").then(json<PriorizacaoPayload>),
  priorizacaoSetMes: (body: { projeto: string; mes: number | null }) =>
    fetch("api/priorizacao/mes", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean; projeto: string; mes: number | null }>),
```

- [ ] **Step 2: Commit (só com OK do usuário)** — junto com Task 7 (typecheck depende do WavesView atualizado).

---

## Task 7: Frontend — `WavesView.tsx` (rótulo fixo + cards + mover)

**Files:**
- Rewrite: `frontend/src/components/WavesView.tsx`

- [ ] **Step 1: Reescrever o componente**

Substitua **todo** o conteúdo de `frontend/src/components/WavesView.tsx` por:

```tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { api } from "../api";
import type { AppConfig, PrioMes, PrioEgp } from "../types";

// Aba "Priorização": plano de ingestão por CAPACIDADE, recorte FIXO (Indicium + dependências,
// todas as áreas, 400 inputs/mês). Slug /ondas p/ deep-links. Cards de resumo no topo
// (migrados no mês / bloqueados / habilitados). Gestão (bv_users) pode fixar um EGP num mês (📌).
// Backend: GET /api/priorizacao (recorte embutido) + PATCH /api/priorizacao/mes.
const CAP = 400;
const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);

interface Props {
  cfg: AppConfig | null;
  onOpenEgp: (projeto: string) => void;
}

export function WavesView({ cfg, onOpenEgp }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<Set<number>>(new Set([1]));
  const isGestao = !!cfg?.is_gestao;

  const q = useQuery({
    queryKey: ["priorizacao"],
    queryFn: () => api.priorizacao(),
    placeholderData: keepPreviousData,
  });
  const data = q.data;
  const meses: PrioMes[] = data?.meses ?? [];
  const resumo = data?.resumo;
  const nMeses = data?.n_meses ?? 0;

  const setMes = useMutation({
    mutationFn: (v: { projeto: string; mes: number | null }) => api.priorizacaoSetMes(v),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["priorizacao"] }),
  });

  const toggle = (m: number) =>
    setOpen((s) => { const n = new Set(s); n.has(m) ? n.delete(m) : n.add(m); return n; });

  return (
    <div className="waves">
      <div className="filters">
        <span className="prio-fixed">
          Recorte fixo: <b>Indicium + dependências</b> · todas as áreas · <b>{CAP}</b> inputs/mês
        </span>
        <span className="count">
          {q.isFetching ? "calculando…" : data
            ? `${data.n_meses} meses · ${data.n_inputs.toLocaleString("pt-BR")} inputs distintos · ${data.n_egps} EGPs`
            : ""}
        </span>
      </div>

      {resumo && (
        <div className="metrics prio-metrics">
          <div className="card">
            <div className="card-value">{resumo.migrados_mes.toLocaleString("pt-BR")}</div>
            <div className="card-label">Migrados neste mês</div>
          </div>
          <div className="card danger">
            <div className="card-value">{resumo.bloqueados.toLocaleString("pt-BR")}</div>
            <div className="card-label">Bloqueados</div>
          </div>
          <div className="card ok">
            <div className="card-value">{resumo.habilitados.toLocaleString("pt-BR")}</div>
            <div className="card-label">Habilitados</div>
          </div>
        </div>
      )}

      <div className="lin-hint">
        Plano por <b>capacidade</b>: meses de até <b>{CAP}</b> inputs distintos a ingerir. Prioridade:{" "}
        <b>1) viabilidade</b> → <b>2) alavancagem</b> → <b>3) quick win</b>. Input compartilhado conta{" "}
        <b>1×</b> (no 1º mês).{isGestao ? " Gestão pode fixar um EGP num mês (📌)." : ""} Clique num EGP p/ abrir na aba EGPs.
      </div>
      {q.error && <div className="error">{String(q.error)}</div>}
      <div className="wave-list">
        {meses.map((m) => {
          const isOpen = open.has(m.mes);
          const pct = Math.min(100, Math.round((100 * m.n_inputs) / CAP));
          const over = m.n_inputs > CAP;
          return (
            <div key={m.mes} className="wave-card">
              <div className="wave-top clickable" onClick={() => toggle(m.mes)}>
                <span className="wave-name">{isOpen ? "▾" : "▸"} Mês {m.mes}</span>
                <span className={`pill ${over ? "todo" : "ok"}`}>{m.n_inputs.toLocaleString("pt-BR")}/{CAP}</span>
              </div>
              <div className="wave-bar"><div className={`wave-fill ${over ? "todo" : "ok"}`} style={{ width: `${pct}%` }} /></div>
              <div className="wave-meta">
                <span><b>{m.n_inputs.toLocaleString("pt-BR")}</b> inputs novos</span>
                <span>{m.n_egps} EGPs</span>
              </div>
              {isOpen && (
                <div className="prio-egps">
                  {m.egps.map((e) => (
                    <div key={e.projeto} className="prio-egp-row">
                      <button className="prio-egp" title={e.projeto} onClick={() => onOpenEgp(e.projeto)}>
                        <span className="pe-name">
                          {e.mes_pin != null && <span title={`fixado no mês ${e.mes_pin}`}>📌 </span>}
                          {shortName(e.projeto)}
                          {e.bloqueado && <span title="bloqueado por dependência"> 🔒</span>}
                          {e.excede && <span className="pill todo"> excede</span>}
                        </span>
                        <span className="pe-meta">
                          {e.area ?? "?"} · +{e.n_inputs_novos} inputs
                          {e.fan_out > 0 ? ` · alimenta ${e.fan_out}` : ""}
                          {e.responsavel ? ` · ${e.responsavel.split("@")[0]}` : ""}
                        </span>
                      </button>
                      {isGestao && (
                        <MoveControl egp={e} nMeses={nMeses} busy={setMes.isPending}
                          onMove={(mes) => setMes.mutate({ projeto: e.projeto, mes })} />
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {!q.isFetching && meses.length === 0 && <div className="empty">Nenhum EGP no recorte atual.</div>}
      </div>
    </div>
  );
}

// Seletor de mês por EGP (só gestão). "auto" = limpa o pin; "+ novo mês" = fixa em nMeses+1.
function MoveControl({ egp, nMeses, busy, onMove }: {
  egp: PrioEgp; nMeses: number; busy: boolean; onMove: (mes: number | null) => void;
}) {
  const cur = egp.mes_pin;
  const months: number[] = [];
  for (let i = 1; i <= nMeses; i++) months.push(i);
  const newMonth = nMeses + 1;
  return (
    <div className="prio-move" onClick={(ev) => ev.stopPropagation()}>
      <select value={cur ?? ""} disabled={busy} title="Fixar este EGP num mês (📌)"
        onChange={(ev) => { const v = ev.target.value; onMove(v === "" ? null : Number(v)); }}>
        <option value="">auto</option>
        {months.map((i) => <option key={i} value={i}>Mês {i}</option>)}
        <option value={newMonth}>+ novo mês ({newMonth})</option>
      </select>
      {cur != null && (
        <button className="prio-clear" disabled={busy} title="Voltar ao automático"
          onClick={() => onMove(null)}>✕</button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck + build (frontend)**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK, sem erros de TS (`priorizacao()` sem args, `resumo`/`mes_pin` tipados, `useMutation`/`useQueryClient` importados).

- [ ] **Step 3: Commit (só com OK do usuário)** — inclui Tasks 5, 6 e 7 juntas (o typecheck só fecha com as três).

```bash
git add egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/api.ts egps_analysis/app/frontend/src/components/WavesView.tsx
git commit -m "feat(app): priorizacao (frontend) — recorte fixo + cards resumo + mover EGP de mês"
```

---

## Task 8: Frontend — estilos (`styles.css`)

**Files:**
- Modify: `frontend/src/styles.css` (adicionar no fim do arquivo)

- [ ] **Step 1: Adicionar estilos**

Adicione ao final de `frontend/src/styles.css`:

```css
/* aba Priorização: rótulo fixo, cards de resumo e controle de mover EGP */
.prio-fixed { font-size: 12px; color: var(--ink); }
.prio-metrics { margin: 8px 0; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
.prio-egp-row { display: flex; gap: 6px; align-items: center; }
.prio-egp-row .prio-egp { flex: 1; min-width: 0; }
.prio-move { display: flex; gap: 4px; align-items: center; }
.prio-move select { background: var(--panel2); color: var(--ink); border: 1px solid var(--line);
  border-radius: 6px; padding: 3px 6px; font-size: 11px; }
.prio-clear { background: var(--panel2); color: var(--mut); border: 1px solid var(--line);
  border-radius: 6px; padding: 3px 7px; font-size: 11px; cursor: pointer; }
.prio-clear:hover:not(:disabled) { color: var(--danger); border-color: var(--danger); }
.prio-clear:disabled, .prio-move select:disabled { opacity: .5; cursor: default; }
```

- [ ] **Step 2: Build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK.

- [ ] **Step 3: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/frontend/src/styles.css
git commit -m "style(app): priorizacao — rótulo fixo, cards e controle de mover"
```

---

## Task 9: Verificação end-to-end

- [ ] **Step 1: Suíte backend verde**

Run: `cd egps_analysis/app/backend && ../venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 2: Build frontend verde**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK.

- [ ] **Step 3: Verificação visual (skill `verify`)** — rodar o app local e conferir:
  - Aba **Priorização** sem controles editáveis; rótulo "Recorte fixo: Indicium + dependências · todas as áreas · 400 inputs/mês".
  - 3 cards no topo: Migrados neste mês / Bloqueados (vermelho) / Habilitados (verde); Bloqueados + Habilitados = total.
  - Meses de até 400; mês que estoura (por pin) aparece com barra/pill em destaque + "excede".
  - Como usuário de gestão: o seletor de mês aparece por EGP; mover um EGP para o Mês 1 (ou "novo mês") persiste (refetch mostra 📌 e o EGP no mês escolhido); "✕"/"auto" volta ao automático.
  - Como usuário não-gestão (se possível testar): o seletor não aparece; abrir EGP ainda funciona.

- [ ] **Step 4: Revisão de código (skill requesting-code-review)** antes de qualquer commit/deploy.

---

# FASE 2 — Onda → Mês de priorização em todas as abas

> Depende da Fase 1 (o payload `/api/priorizacao` com `meses[].egps[].projeto → mes` já existe). **Sem mudança de backend.** Padrão idêntico por aba: remover o `waveTag` local, importar `mesTag`/`useMesPlan`, e trocar `waveTag(r.onda)` por `mesTag(mesOf.get(r.projeto))`; o ⟳ passa a vir de `ciclo_id`. EGP fora do recorte fixo → `mesOf` não tem a chave → `mesTag(undefined)` = `"—"`.
>
> **Regra dos hooks:** chame `useMesPlan()` junto dos outros hooks no topo do componente (antes de qualquer `return` condicional).

## File Structure (Fase 2)

| Arquivo | Ação |
|---|---|
| `frontend/src/mesPlan.ts` | **Criar** — `mesTag` + hook `useMesPlan` (mapa `projeto→mês`, cache compartilhado `["priorizacao"]`). |
| `frontend/src/components/ReadinessView.tsx` | Filtro Onda→Mês + coluna/CSV/célula. |
| `frontend/src/components/IndiciumView.tsx` | Coluna/CSV/célula. |
| `frontend/src/components/MigrationScopeView.tsx` | Coluna/CSV/célula. |
| `frontend/src/components/InputDrawer.tsx` | 2 células. |
| `frontend/src/components/EgpDetailPanel.tsx` | Pill do nó + 2 listas de deps. |
| `frontend/src/components/LineageView.tsx` | Rótulo do nó + tooltip (cytoscape) + patch ao vivo. |

---

## Task 10: Módulo compartilhado `mesPlan.ts`

**Files:**
- Create: `frontend/src/mesPlan.ts`

- [ ] **Step 1: Criar o módulo**

Create `frontend/src/mesPlan.ts`:

```ts
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

// Tag textual do mês do plano de priorização. null/undefined (fora do recorte fixo) => "—".
export const mesTag = (mes: number | null | undefined) => (mes == null ? "—" : `M${mes}`);

// Hook compartilhado: mapa projeto -> mês do plano dinâmico. Usa a MESMA queryKey do WavesView
// (["priorizacao"]) => cache único; quando um pin é gravado (PATCH invalida ["priorizacao"]),
// todas as abas que usam este hook re-renderizam com o mês atualizado.
export function useMesPlan() {
  const q = useQuery({ queryKey: ["priorizacao"], queryFn: () => api.priorizacao(), staleTime: 60_000 });
  const mesOf = useMemo(() => {
    const m = new Map<string, number>();
    (q.data?.meses ?? []).forEach((mm) => mm.egps.forEach((e) => m.set(e.projeto, mm.mes)));
    return m;
  }, [q.data]);
  const meses = useMemo(() => (q.data?.meses ?? []).map((mm) => mm.mes), [q.data]);
  return { mesOf, meses, isFetching: q.isFetching };
}
```

- [ ] **Step 2: Typecheck**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK (Task 6 já deixou `api.priorizacao()` sem args; `PrioMes`/`PrioEgp` já tipados na Task 5).

- [ ] **Step 3: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/frontend/src/mesPlan.ts
git commit -m "feat(app): mesPlan — mesTag + hook useMesPlan (mapa projeto→mês, cache compartilhado)"
```

---

## Task 11: ReadinessView — filtro Onda→Mês + coluna + célula + CSV

**Files:**
- Modify: `frontend/src/components/ReadinessView.tsx`

- [ ] **Step 1: Remover `waveTag` local (linhas 11-15)**

Delete:

```tsx
const waveTag = (onda: string) => {
  if (!onda) return "—";
  if (/cicl/i.test(onda)) return "⟳";
  const m = onda.match(/\d+/);
  return m ? `O${m[0]}` : onda;
};
```

- [ ] **Step 2: Importar `mesTag`/`useMesPlan`**

Após o último `import ... from "..."` do topo do arquivo, adicione:

```tsx
import { mesTag, useMesPlan } from "../mesPlan";
```

- [ ] **Step 3: Trocar o estado do filtro Onda por Mês**

Replace:

```tsx
  const [ondaSel, setOndaSel] = useState<Set<string>>(new Set());
  const toggleOnda = (s: string) =>
    setOndaSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
```

With:

```tsx
  const [mesSel, setMesSel] = useState<Set<string>>(new Set());
  const toggleMes = (s: string) =>
    setMesSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
```

- [ ] **Step 4: Chamar o hook e derivar a lista de meses**

Logo após `const rows = useMemo(() => rq.data?.rows ?? [], [rq.data]);` adicione:

```tsx
  const { mesOf, meses } = useMesPlan();
```

Replace:

```tsx
  const ondasList = useMemo(() => {
    const wn = (o: string) => { const m = o.match(/\d+/); return m ? Number(m[0]) : 999; };
    return [...new Set(rows.map((r) => r.onda).filter(Boolean))].sort((a, b) => wn(a) - wn(b) || a.localeCompare(b));
  }, [rows]);
```

With:

```tsx
  const mesesList = useMemo(() => meses.map((n) => `M${n}`), [meses]);
```

- [ ] **Step 5: Trocar o filtro em `baseDims`**

Replace:

```tsx
    if (ondaSel.size) v = v.filter((r) => ondaSel.has(r.onda));
```

With:

```tsx
    if (mesSel.size) v = v.filter((r) => mesSel.has(mesTag(mesOf.get(r.projeto))));
```

Replace (deps do `useMemo` de `baseDims`):

```tsx
  }, [rows, areaSel, ondaSel, statusSel, etapaSel, q]);
```

With:

```tsx
  }, [rows, areaSel, mesSel, mesOf, statusSel, etapaSel, q]);
```

- [ ] **Step 6: Reset dos filtros**

Replace:

```tsx
    setAreaSel(new Set()); setOndaSel(new Set()); setBucket(""); setQ(""); setQuickWin(false); setBlockedOnly(false); setStatusSel(new Set()); setEtapaSel(new Set());
```

With:

```tsx
    setAreaSel(new Set()); setMesSel(new Set()); setBucket(""); setQ(""); setQuickWin(false); setBlockedOnly(false); setStatusSel(new Set()); setEtapaSel(new Set());
```

- [ ] **Step 7: Coluna CSV Onda→Mês**

Replace:

```tsx
      { header: "Onda", get: (r) => r.onda },
```

With:

```tsx
      { header: "Mês", get: (r) => mesTag(mesOf.get(r.projeto)) },
```

- [ ] **Step 8: MultiSelect Onda→Mês**

Replace:

```tsx
        <MultiSelect label="Onda" options={ondasList} sel={ondaSel}
          onToggle={toggleOnda} onClear={() => setOndaSel(new Set())} />
```

With:

```tsx
        <MultiSelect label="Mês" options={mesesList} sel={mesSel}
          onToggle={toggleMes} onClear={() => setMesSel(new Set())} />
```

- [ ] **Step 9: Cabeçalho e célula da tabela**

Replace:

```tsx
          <div>Onda</div>{th("n_inputs", "Inputs")}{th("pct", "% modernizado")}
```

With:

```tsx
          <div>Mês</div>{th("n_inputs", "Inputs")}{th("pct", "% modernizado")}
```

Replace:

```tsx
                  <div className={r.ciclo_id > 0 ? "cyc-txt" : ""}>{waveTag(r.onda)}</div>
```

With:

```tsx
                  <div className={r.ciclo_id > 0 ? "cyc-txt" : ""}>{mesTag(mesOf.get(r.projeto))}{r.ciclo_id > 0 ? " ⟳" : ""}</div>
```

- [ ] **Step 10: Build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK.

- [ ] **Step 11: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/frontend/src/components/ReadinessView.tsx
git commit -m "feat(app): Prontidão — Onda→Mês (coluna, filtro, célula, CSV) via useMesPlan"
```

---

## Task 12: IndiciumView — coluna + célula + CSV

**Files:**
- Modify: `frontend/src/components/IndiciumView.tsx`

- [ ] **Step 1: Remover `waveTag` local (linhas 16-21)**

Delete:

```tsx
const waveTag = (onda: string | null) => {
  if (!onda) return "—";
  if (/cicl/i.test(onda)) return "⟳";
  const m = onda.match(/\d+/);
  return m ? `O${m[0]}` : onda;
};
```

- [ ] **Step 2: Importar + chamar o hook**

Após o último `import` do topo, adicione:

```tsx
import { mesTag, useMesPlan } from "../mesPlan";
```

Logo após `const qc = useQueryClient();` (dentro do componente), adicione:

```tsx
  const { mesOf } = useMesPlan();
```

- [ ] **Step 3: CSV Onda→Mês**

Replace:

```tsx
      { header: "Onda", get: (r) => r.onda ?? "" },
```

With:

```tsx
      { header: "Mês", get: (r) => mesTag(mesOf.get(r.projeto)) },
```

- [ ] **Step 4: Cabeçalho e célula**

Replace:

```tsx
          <div>Onda</div>
```

With:

```tsx
          <div>Mês</div>
```

Replace:

```tsx
                <div className={Number(r.ciclo_id) > 0 ? "cyc-txt" : ""}>{rec ? waveTag(r.onda) : "—"}</div>
```

With:

```tsx
                <div className={Number(r.ciclo_id) > 0 ? "cyc-txt" : ""}>{rec ? mesTag(mesOf.get(r.projeto)) + (Number(r.ciclo_id) > 0 ? " ⟳" : "") : "—"}</div>
```

- [ ] **Step 5: Build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK.

- [ ] **Step 6: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/frontend/src/components/IndiciumView.tsx
git commit -m "feat(app): Indicium — Onda→Mês (coluna, célula, CSV) via useMesPlan"
```

---

## Task 13: MigrationScopeView — coluna + célula + CSV

**Files:**
- Modify: `frontend/src/components/MigrationScopeView.tsx`

- [ ] **Step 1: Remover `waveTag` local (linhas 10-14)**

Delete:

```tsx
const waveTag = (onda: string | null) => {
  if (!onda) return "—";
  if (/cicl/i.test(onda)) return "⟳";
  const m = onda.match(/\d+/);
  return m ? `O${m[0]}` : onda;
};
```

- [ ] **Step 2: Importar + chamar o hook**

Após o último `import` do topo, adicione:

```tsx
import { mesTag, useMesPlan } from "../mesPlan";
```

Logo após `const rows = useMemo(() => sq.data?.rows ?? [], [sq.data]);` adicione:

```tsx
  const { mesOf } = useMesPlan();
```

- [ ] **Step 3: CSV Onda→Mês**

Replace:

```tsx
      { header: "Onda", get: (r) => r.onda ?? "" },
```

With:

```tsx
      { header: "Mês", get: (r) => mesTag(mesOf.get(r.projeto)) },
```

- [ ] **Step 4: Cabeçalho e célula**

Replace:

```tsx
          <div>Onda</div>{th("n_inputs", "Inputs")}{th("pct", "% modernizado")}
```

With:

```tsx
          <div>Mês</div>{th("n_inputs", "Inputs")}{th("pct", "% modernizado")}
```

Replace:

```tsx
                  <div className={r.ciclo_id && r.ciclo_id > 0 ? "cyc-txt" : ""}>{waveTag(r.onda)}</div>
```

With:

```tsx
                  <div className={r.ciclo_id && r.ciclo_id > 0 ? "cyc-txt" : ""}>{mesTag(mesOf.get(r.projeto))}{r.ciclo_id && r.ciclo_id > 0 ? " ⟳" : ""}</div>
```

- [ ] **Step 5: Build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK.

- [ ] **Step 6: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/frontend/src/components/MigrationScopeView.tsx
git commit -m "feat(app): Escopo Migração — Onda→Mês (coluna, célula, CSV) via useMesPlan"
```

---

## Task 14: InputDrawer — 2 células

**Files:**
- Modify: `frontend/src/components/InputDrawer.tsx`

- [ ] **Step 1: Remover `waveTag` local (linhas 8-12)**

Delete:

```tsx
const waveTag = (onda: string | null) => {
  if (!onda) return "—";
  if (/cicl/i.test(onda)) return "⟳";
  const m = onda.match(/\d+/);
  return m ? `O${m[0]}` : onda;
};
```

- [ ] **Step 2: Importar + chamar o hook**

Após `import type { InputRow } from "../types";` adicione:

```tsx
import { mesTag, useMesPlan } from "../mesPlan";
```

Logo após `export function InputDrawer({ row, onClose, onOpenEgp }: Props) {` adicione:

```tsx
  const { mesOf } = useMesPlan();
```

- [ ] **Step 3: Trocar as 2 células (produtores e usados-por)**

Há **duas** ocorrências idênticas — substitua ambas (use replace-all):

Replace (2×):

```tsx
              <span className="de-meta">{e.area ?? "?"} · {waveTag(e.onda)}</span>
```

With (2×):

```tsx
              <span className="de-meta">{e.area ?? "?"} · {mesTag(mesOf.get(e.projeto))}</span>
```

(O ⟳ já é mostrado separadamente na linha `de-name` via `Number(e.ciclo_id) > 0`.)

- [ ] **Step 4: Build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK.

- [ ] **Step 5: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/frontend/src/components/InputDrawer.tsx
git commit -m "feat(app): InputDrawer — Onda→Mês nas listas de EGPs via useMesPlan"
```

---

## Task 15: EgpDetailPanel — pill do nó + 2 listas de deps

**Files:**
- Modify: `frontend/src/components/EgpDetailPanel.tsx`

- [ ] **Step 1: Remover `waveTag` local (linhas 13-17)**

Delete:

```tsx
const waveTag = (onda: string | null) => {
  if (!onda) return "—";
  if (/cicl/i.test(onda)) return "⟳ ciclo";
  const m = onda.match(/\d+/);
  return m ? `onda ${m[0]}` : onda;
};
```

- [ ] **Step 2: Importar + chamar o hook**

Após o último `import` do topo, adicione:

```tsx
import { mesTag, useMesPlan } from "../mesPlan";
```

Junto dos hooks do topo do componente (ao lado de `const qc = useQueryClient();`, **antes de qualquer `return` condicional**), adicione:

```tsx
  const { mesOf } = useMesPlan();
```

- [ ] **Step 3: Pill do nó**

Replace:

```tsx
        <span className="pill">{waveTag(det.node.onda)}</span>
```

With:

```tsx
        <span className="pill">{mesTag(mesOf.get(det.node.projeto))}</span>
```

(O ⟳ do nó já aparece na linha seguinte via `Number(det.node.ciclo_id) > 0`.)

- [ ] **Step 4: Listas de deps (Depende de / Alimenta)**

Há **duas** ocorrências idênticas — substitua ambas (use replace-all):

Replace (2×):

```tsx
              <span className="dep-meta">{d.area ?? "?"} · {waveTag(d.onda)} {Number(d.ciclo_id) > 0 ? "· ⟳" : ""}</span>
```

With (2×):

```tsx
              <span className="dep-meta">{d.area ?? "?"} · {mesTag(mesOf.get(d.projeto))} {Number(d.ciclo_id) > 0 ? "· ⟳" : ""}</span>
```

- [ ] **Step 5: Build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK.

- [ ] **Step 6: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/frontend/src/components/EgpDetailPanel.tsx
git commit -m "feat(app): Detalhe do EGP — Onda→Mês (pill + deps) via useMesPlan"
```

---

## Task 16: LineageView — rótulo do nó + tooltip + patch ao vivo (cytoscape)

**Files:**
- Modify: `frontend/src/components/LineageView.tsx`

A linhagem é imperativa (cytoscape). Estratégia: `egpEl` recebe o mapa `mesOf`; os call-sites
passam `mesOfRef.current` (ref sempre atual, sem entrar em deps de `useCallback`); e um efeito
dependente de `mesOf` faz *patch* dos nós já renderizados (reflexo ao vivo ao fixar/mover).

- [ ] **Step 1: Remover `waveTag` local (linhas 19-24) e adicionar helper `applyMes`**

Replace:

```tsx
const waveTag = (onda: string) => {
  if (!onda) return "";
  if (/cicl/i.test(onda)) return "⟳ ciclo";
  const m = onda.match(/\d+/);
  return m ? `onda ${m[0]}` : onda;
};
```

With:

```tsx
// rótulo do nó = nome curto + tag do mês (Mn) + ⟳ se em ciclo. Usado no build e no patch ao vivo.
const nodeLabel = (projeto: string, mes: number | undefined, ciclo: number) => {
  const tag = (mes != null ? `M${mes}` : "") + (ciclo > 0 ? " ⟳" : "");
  return `${trunc(shortName(projeto))}${tag ? "\n" + tag : ""}`;
};

// aplica o mês do plano nos nós já renderizados (label + data.mes) — chamado quando mesOf muda.
function applyMes(cy: cytoscape.Core | null, mesOf: Map<string, number>) {
  if (!cy) return;
  cy.nodes().forEach((node) => {
    if (node.data("kind") !== "egp") return;
    const mt = mesOf.get(String(node.id()));
    node.data("mes", mt != null ? `M${mt}` : "—");
    node.data("label", nodeLabel(String(node.id()), mt, Number(node.data("ciclo_id")) || 0));
  });
}
```

- [ ] **Step 2: `egpEl` recebe `mesOf`**

Replace:

```tsx
const egpEl = (n: LineageNode, root: string | null, withParent: boolean): cytoscape.ElementDefinition => {
  const area = n.area || "—";
  const data: Record<string, unknown> = {
    id: n.projeto, kind: "egp", area, color: areaColor(area),
    label: `${trunc(shortName(n.projeto))}${waveTag(n.onda) ? "\n" + waveTag(n.onda) : ""}`,
    onda: n.onda || "—", indi: indiOf(n), ninputs: n.n_inputs, noutputs: n.n_outputs,
    ciclo_id: Number(n.ciclo_id) || 0,
  };
  if (withParent) data.parent = AREA_PREFIX + area;
  return { group: "nodes", data };
};
```

With:

```tsx
const egpEl = (n: LineageNode, root: string | null, withParent: boolean, mesOf: Map<string, number>): cytoscape.ElementDefinition => {
  const area = n.area || "—";
  const mt = mesOf.get(n.projeto);
  const ciclo = Number(n.ciclo_id) || 0;
  const data: Record<string, unknown> = {
    id: n.projeto, kind: "egp", area, color: areaColor(area),
    label: nodeLabel(n.projeto, mt, ciclo),
    mes: mt != null ? `M${mt}` : "—", indi: indiOf(n), ninputs: n.n_inputs, noutputs: n.n_outputs,
    ciclo_id: ciclo,
  };
  if (withParent) data.parent = AREA_PREFIX + area;
  return { group: "nodes", data };
};
```

- [ ] **Step 3: Importar o hook e criar a ref + efeito de patch**

Após `import { api } from "../api";` adicione:

```tsx
import { useMesPlan } from "../mesPlan";
```

Logo após `const [tip, setTip] = useState<{ x: number; y: number; lines: string[] } | null>(null);` adicione:

```tsx
  const { mesOf } = useMesPlan();
  const mesOfRef = useRef(mesOf);
  useEffect(() => { mesOfRef.current = mesOf; applyMes(cyRef.current, mesOf); }, [mesOf]);
```

- [ ] **Step 4: Passar `mesOfRef.current` nos 3 call-sites de `egpEl`**

Replace:

```tsx
      for (const n of p.nodes) els.push(egpEl(n, root, true));
```

With:

```tsx
      for (const n of p.nodes) els.push(egpEl(n, root, true, mesOfRef.current));
```

Replace:

```tsx
      cy.add([...p.nodes.map((n) => egpEl(n, root, false)), ...edges.map(edgeElDef)]);
```

With:

```tsx
      cy.add([...p.nodes.map((n) => egpEl(n, root, false, mesOfRef.current)), ...edges.map(edgeElDef)]);
```

Replace:

```tsx
      const newNodes = p.nodes.filter((n) => !have.has(n.projeto)).map((n) => egpEl(n, rootRef.current, false));
```

With:

```tsx
      const newNodes = p.nodes.filter((n) => !have.has(n.projeto)).map((n) => egpEl(n, rootRef.current, false, mesOfRef.current));
```

- [ ] **Step 5: Tooltip Onda→Mês**

Replace:

```tsx
        lines = [t.id(), `Área: ${t.data("area")}`, `Onda: ${t.data("onda")}`,
```

With:

```tsx
        lines = [t.id(), `Área: ${t.data("area")}`, `Mês: ${t.data("mes")}`,
```

- [ ] **Step 6: Build**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK (sem referências remanescentes a `waveTag`/`t.data("onda")`).

- [ ] **Step 7: Commit (só com OK do usuário)**

```bash
git add egps_analysis/app/frontend/src/components/LineageView.tsx
git commit -m "feat(app): Linhagem — Onda→Mês no rótulo/tooltip + patch ao vivo (useMesPlan)"
```

---

## Task 17: Verificação Fase 2

- [ ] **Step 1: Sem `waveTag`/`onda` remanescente exibido**

Run: `cd egps_analysis/app/frontend && grep -rn "waveTag" src/components; grep -rn "data(\"onda\")" src`
Expected: **nenhum** resultado (todas as abas migraram para `mesTag`/`mes`).

- [ ] **Step 2: Build verde**

Run: `cd egps_analysis/app/frontend && npm run build`
Expected: build OK.

- [ ] **Step 3: Verificação visual (skill `verify`)** — app local:
  - Em **Prontidão**, **Indicium**, **Escopo Migração**: a coluna "Onda" agora é "Mês" e mostra `M1..Mn` (ou "—" fora do recorte); ⟳ nos que têm ciclo. O filtro da Prontidão vira "Mês".
  - **Detalhe do EGP**, **InputDrawer**, **Linhagem**: mostram o mês no lugar da onda; ⟳ preservado.
  - **Dinâmico:** com um EGP aberto/visível em outra aba, fixe/mova esse EGP na aba **Priorização** → ao voltar, o mês reflete a mudança (React Query invalida `["priorizacao"]`). Na Linhagem, o patch atualiza o rótulo sem rebuild.
  - CSVs exportam a coluna "Mês".

---

## Self-review (cobertura vs spec)

- ✅ Filtros fixos (removidos + rótulo) → Tasks 6, 7.
- ✅ Capacidade fixa 400 → `CAP=400` (Task 7) + `capacidade=400` na URL (Task 6).
- ✅ Card "migrados neste mês" (calendário, só 'Migrado') → `_migrados_mes` (Task 2) + card (Task 7).
- ✅ Cards bloqueados/habilitados (complemento) → `resumo_counts` (Task 1) + endpoint (Task 3) + cards (Task 7).
- ✅ População = recorte indi+deps → `frontier` alimenta resumo e `_migrados_mes` (Task 3).
- ✅ Mover EGP (pin absoluto, teto guia, persistido, gated) → coluna (Task 2), algoritmo (Task 1/3), endpoint gated (Task 4), UI gestão (Task 7).
- ✅ Meses contíguos/renumerados → `plan_months` remove vazios + `mes=i+1` (Tasks 1, 3).
- ✅ Testes da lógica pura → Task 1; verificação visual/SQL → Task 9.
- ✅ Guardrails (sem commit/deploy/escrita-prod sem OK) → nota no topo + passos de commit gated.

**Fase 2 (Onda → Mês):**
- ✅ Substituir Onda→Mês nas 6 abas → Tasks 11-16 (remove `waveTag`, usa `mesTag`).
- ✅ Reflexo dinâmico → hook `useMesPlan` com queryKey `["priorizacao"]` compartilhada + invalidação no PATCH (Tasks 4, 7, 10); Linhagem com patch ao vivo (Task 16).
- ✅ Fora do recorte → "—" → `mesTag(undefined)` (Task 10).
- ✅ ⟳ preservado de `ciclo_id` → mantido em cada célula/rótulo (Tasks 11-16).
- ✅ Filtro da Prontidão Onda→Mês → Task 11.
- ✅ Sem sobra de `waveTag`/`onda` exibida → grep de verificação (Task 17 Step 1).
- ✅ Sem mudança de backend na Fase 2 → todas as tarefas são frontend.

## Tipos consistentes (auto-check)

- `mesTag(mes: number | null | undefined)` e `useMesPlan(): { mesOf: Map<string, number>, meses: number[], isFetching }` — usados de forma idêntica em Tasks 11-16.
- `mesOf.get(r.projeto)` retorna `number | undefined`; `mesTag` trata `undefined` como "—". Todas as 5 interfaces de linha têm `projeto: string` (confirmado em types.ts).
- `PrioEgp.mes_pin` (Task 5) e `resumo: PrioResumo` (Task 5) batem com o payload do endpoint (Task 3).
```
