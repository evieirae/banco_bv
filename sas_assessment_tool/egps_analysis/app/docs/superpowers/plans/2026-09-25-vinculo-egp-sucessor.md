# Vínculo antecessor → sucessor (EGPs Atualizados) — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a versão nova de um EGP virar um projeto do corpus vinculado ao antecessor, de modo que o antecessor mostre status `Desatualizado` com a etapa espelhada do sucessor, e que o sucessor apareça no recorte sem inflar a contagem de EGPs.

**Architecture:** O vínculo mora no antecessor, em duas colunas novas de `sas_egp_pipeline` (`egp_vinculo_tipo`, `egp_sucessor`). Toda a regra é derivada em leitura — nada de status gravado, nada de cascata — e vive num módulo puro (`vinculos.py`) testável sem banco, no mesmo padrão de `priorizacao_logic.py`. O backend injeta a derivação no `/api/egp-readiness` e recusa no servidor a edição de etapa de um EGP espelhado. O front espelha o predicado, como já faz com `contaNoTotalEgp`.

**Tech Stack:** Python 3 + FastAPI + databricks-sdk (backend, `app/backend`), TypeScript + React + Vite (frontend, `app/frontend`), Delta/Databricks SQL (prod `bv_dev_db.monitoramento_sas`).

**Spec:** [`../specs/2026-09-24-egps-atualizados-unificacao-design.md`](../specs/2026-09-24-egps-atualizados-unificacao-design.md) — as regras numeradas citadas nas tarefas (§3.1.2, §3.2.7…) são desse documento.

---

## Estado da execução (25/09/2026)

**Tasks 1 a 7 executadas e verdes**, no worktree `cached-wiggling-hopper`, **não commitadas**.
Backend: 302 testes (289 pré-existentes + 13 novos). Frontend: 6 arquivos de teste, `tsc`
limpo, `vite build` ok. **Task 8 bloqueada**: os `.egp` atualizados não estão neste checkout
(nenhum posterior a 01/09; a pasta `versoes_atualizadas_egp_2026-09` só tem análises).

Três coisas que a execução mudou em relação ao plano escrito:

- **A Task 5 virou refactor amplo.** O plano a descrevia como local ("troque o `return` do
  `_frontier_egps`"), mas `len(frontier)` é usado como contagem de EGP em **6 lugares** —
  coorte e denominador do funil `+deps`, `n_egps` do funil de ingestão por mês,
  `/api/scope-egps`, e `dep_count`/`total` da aba EGPs. Todos passaram a usar um helper
  `_contaveis()`, e o mapa de vínculos virou **fonte única cacheada**
  (`_vinculos_por_antecessor`) — o readiness tinha uma query própria, o que deixaria recorte
  e card discordando entre si.
- **A Task 7 exigiu uma extração.** `buildKanbanColunas`/`kanbanColKeyOf` viviam num `.tsx`, e
  `node --experimental-strip-types` não processa JSX: o teste do plano não rodaria. Foram
  para `src/kanbanColunas.ts`, com `GestaoKanban` re-exportando — os três importadores seguem
  intocados.
- **A verificação de regressão precisou ser refeita.** Comparar contadores contra um snapshot
  gravado antes dá **falso positivo**: prod deriva sozinha (medido: +10 inputs em ~20 min).
  E, pior, daria **falso negativo**: sem nenhum vínculo em prod, o conjunto de espelhados é
  vazio e qualquer ponto de contagem esquecido passaria batido. O verificador final captura
  base e injeção **no mesmo processo**, injeta 5 vínculos falsos na fonte única e compara só
  contagem de EGP (funis de ingestão acompanham os inputs por definição). Resultado: recorte
  180 → 185, lista 209 → 214, **18 contagens de EGP idênticas**.

---

## Regras deste repositório (valem em todas as tarefas)

- **Nunca rodar `git commit` / `git push` sem o usuário pedir.** Os passos de commit abaixo ficam prontos, mas o executor **para e pede autorização** antes de rodar. Mensagem de commit em português.
- **Nunca usar o trailer `Co-Authored-By`** neste repo.
- **Nunca escrever em produção** (`bv_dev_db.monitoramento_sas`) sem consentimento explícito. Todo teste deste plano roda offline, com `run_sql` stubado.
- `frontend/src/pipeline.ts` é **espelho** de `backend/main.py` para status/etapa — mexeu num, mexa no outro.
- Backend: `cd egps_analysis/app/backend` e rode os testes com **`egps_analysis/venv/bin/python3`**, não com `app/venv` — o `app/venv` não tem `httpx`, e sem ele o `TestClient` do FastAPI nem coleta: **9 arquivos de teste do backend ficam inertes**, 8 deles anteriores a este plano. Medido em 25/09/2026. Com o venv certo a suíte roda inteira (289 testes antes deste plano).
- Frontend: `cd egps_analysis/app/frontend`; se não houver `node_modules`, faça o symlink para o do repo principal.

## Escopo deste plano

Cobre o **núcleo**: entrada do sucessor no corpus, o vínculo, o status derivado, o espelhamento com bloqueio e a regra do denominador. Produz software funcionando e testável por si só.

O §3.4.13 (inputs do sucessor entrando junto com o recorte) sai de graça na Task 5: ao entrar no `indi_deps`, os inputs dele passam a contar pela maquinaria que já existe.

**Fora deste plano** (cada um pede o seu, depois deste rodar): aposentar a aba EGPs Atualizados e mover a comparação para o drawer (§5 da spec), o funil de sucessores no Resumo (§3.1.3), a sanitização derivada dos inputs exclusivos (§3.4.15–18), a cópia de mês/Jira/responsável e a sugestão de fechar o antecessor no Substituído (§2 etapa 3, §3.3.11) e o contador "aguardando entrada no corpus" (§5).

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `app/backend/vinculos.py` *(novo)* | Lógica pura do vínculo: tipos válidos, quem espelha, status/etapa exibidos, quais sucessores ficam fora do denominador. Sem DB, sem FastAPI. |
| `app/backend/test_vinculos.py` *(novo)* | Testes do módulo puro. |
| `app/backend/test_vinculo_endpoint.py` *(novo)* | Testes do `PATCH /api/egp-pipeline`: validação de tipo, guardas e bloqueio da etapa. |
| `app/backend/main.py` | Colunas novas (lazy migration), aceite no PATCH, guardas, derivação no readiness, frontier e denominador. |
| `app/frontend/src/pipeline.ts` | `Desatualizado` no vocabulário de status + predicado do denominador. |
| `app/frontend/src/types.ts` | Campos novos de `ReadinessRow`. |
| `app/frontend/src/components/ReadinessView.tsx` | Coluna/filtro do vínculo e etapa read-only quando espelhada. |
| `app/frontend/src/components/GestaoKanban.tsx` | Coluna `Desatualizado` pela precedência já existente. |
| `app/frontend/pipeline.test.mts` | Teste do predicado no front. |
| `egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md` | Documenta a pasta irmã e a regra de nomeação. |

---

## Task 1: Módulo puro do vínculo

**Files:**
- Create: `egps_analysis/app/backend/vinculos.py`
- Test: `egps_analysis/app/backend/test_vinculos.py`

- [x] **Step 1: Escrever o teste que falha**

Crie `egps_analysis/app/backend/test_vinculos.py`:

```python
# -*- coding: utf-8 -*-
"""Testes da lógica pura do vínculo antecessor -> sucessor (sem DB, sem rede)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import vinculos as v


def test_tipo_valido():
    assert v.tipo_valido("Atualizado")
    assert v.tipo_valido("Substituído")
    assert v.tipo_valido("Unificado")
    assert not v.tipo_valido("atualizado")      # case-sensitive de propósito
    assert not v.tipo_valido("Desatualizado")   # status, não tipo de vínculo
    assert not v.tipo_valido("")
    assert not v.tipo_valido(None)


def test_espelha_so_atualizado_e_unificado():
    # Substituído NÃO espelha: o antecessor fecha e o sucessor começa do zero.
    assert v.espelha("Atualizado")
    assert v.espelha("Unificado")
    assert not v.espelha("Substituído")
    assert not v.espelha(None)


def test_mapa_vinculos_exige_tipo_e_sucessor():
    rows = [
        {"projeto": "A__x", "egp_vinculo_tipo": "Atualizado", "egp_sucessor": "A__x__ATU20260923"},
        {"projeto": "A__y", "egp_vinculo_tipo": "Atualizado", "egp_sucessor": ""},      # sem sucessor
        {"projeto": "A__z", "egp_vinculo_tipo": "", "egp_sucessor": "A__z__ATU20260923"},  # sem tipo
        {"projeto": "A__w", "egp_vinculo_tipo": "Invalido", "egp_sucessor": "A__q"},    # tipo inválido
        {"projeto": "", "egp_vinculo_tipo": "Atualizado", "egp_sucessor": "A__k"},      # sem projeto
    ]
    m = v.mapa_vinculos(rows)
    assert set(m) == {"A__x"}
    assert m["A__x"] == {"tipo": "Atualizado", "sucessor": "A__x__ATU20260923"}


def test_mapa_vinculos_tolera_none_e_espacos():
    assert v.mapa_vinculos(None) == {}
    m = v.mapa_vinculos([
        {"projeto": " A__x ", "egp_vinculo_tipo": " Unificado ", "egp_sucessor": " A__novo "}])
    assert m == {"A__x": {"tipo": "Unificado", "sucessor": "A__novo"}}


def test_sucessores_espelhados_ficam_fora_do_denominador():
    vin = {
        "A__um": {"tipo": "Atualizado", "sucessor": "A__novo"},
        "A__dois": {"tipo": "Unificado", "sucessor": "A__novo"},      # N:1, mesmo sucessor
        "A__tres": {"tipo": "Substituído", "sucessor": "A__outro"},
    }
    # Substituído conta (o antecessor saiu do fluxo); Atualizado/Unificado não.
    assert v.sucessores_espelhados(vin) == {"A__novo"}


def test_status_exibido_despriorizado_vence():
    # Decisão de gestão não é sobrescrita por fato derivado.
    assert v.status_exibido("Despriorizado e Contabilizado", "Atualizado") \
        == "Despriorizado e Contabilizado"


def test_status_exibido_vira_desatualizado_quando_espelha():
    assert v.status_exibido("Em Andamento", "Atualizado") == "Desatualizado"
    assert v.status_exibido("Block", "Unificado") == "Desatualizado"


def test_status_exibido_intacto_sem_vinculo_e_em_substituido():
    assert v.status_exibido("Em Andamento", None) == "Em Andamento"
    assert v.status_exibido("Em Andamento", "Substituído") == "Em Andamento"


def test_etapa_exibida_espelha_a_do_sucessor():
    assert v.etapa_exibida("Pré-conversão", "Atualizado", "Validação em DES") == "Validação em DES"
    assert v.etapa_exibida("Pré-conversão", "Unificado", None) is None
    assert v.etapa_exibida("Pré-conversão", "Substituído", "Validação em DES") == "Pré-conversão"
    assert v.etapa_exibida("Pré-conversão", None, "Validação em DES") == "Pré-conversão"


def test_pode_editar_etapa():
    assert not v.pode_editar_etapa("Atualizado")
    assert not v.pode_editar_etapa("Unificado")
    assert v.pode_editar_etapa("Substituído")
    assert v.pode_editar_etapa(None)
```

- [x] **Step 2: Rodar o teste e confirmar que falha**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculos.py -q
```

Esperado: `ModuleNotFoundError: No module named 'vinculos'`.

- [x] **Step 3: Escrever o módulo**

Crie `egps_analysis/app/backend/vinculos.py`:

```python
# -*- coding: utf-8 -*-
"""Lógica pura do vínculo antecessor -> sucessor (EGPs Atualizados).

Sem DB e sem FastAPI, no padrão de priorizacao_logic.py / prioridades_logic.py: dá para
testar offline e o main.py só injeta os dados. As regras vivem em
app/docs/superpowers/specs/2026-09-24-egps-atualizados-unificacao-design.md.

Tudo aqui é DERIVADO. Nada de status gravado: o status real do antecessor fica intacto no
banco e reaparece se o vínculo for desfeito (§3.2.6 da spec).
"""

TIPOS_VINCULO = ("Atualizado", "Substituído", "Unificado")
# Atualizado/Unificado: o trabalho migrou para o sucessor, então o antecessor herda a etapa
# dele e para de editá-la. Substituído não espelha — o antecessor fecha como Despriorizado
# e Contabilizado e o sucessor começa do zero, trajetórias independentes (§3.2).
TIPOS_QUE_ESPELHAM = ("Atualizado", "Unificado")

STATUS_DESATUALIZADO = "Desatualizado"
STATUS_DESPRIORIZADO = "Despriorizado e Contabilizado"


def tipo_valido(tipo):
    return tipo in TIPOS_VINCULO


def espelha(tipo):
    return tipo in TIPOS_QUE_ESPELHAM


def mapa_vinculos(pipe_rows):
    """{antecessor: {"tipo", "sucessor"}} a partir das linhas de sas_egp_pipeline.

    Vínculo pela metade não é vínculo: sem tipo válido OU sem sucessor, a linha é ignorada
    — senão um tipo salvo antes do ponteiro já espelharia etapa de lugar nenhum.
    """
    mapa = {}
    for r in pipe_rows or []:
        projeto = (r.get("projeto") or "").strip()
        tipo = (r.get("egp_vinculo_tipo") or "").strip()
        sucessor = (r.get("egp_sucessor") or "").strip()
        if projeto and sucessor and tipo_valido(tipo):
            mapa[projeto] = {"tipo": tipo, "sucessor": sucessor}
    return mapa


def sucessores_espelhados(vinculos):
    """Sucessores que ficam FORA do denominador de EGPs (§3.1.2).

    O trabalho deles já conta na linha do antecessor, via etapa espelhada — somar os dois
    contaria o mesmo trabalho duas vezes. Sucessor de Substituído não entra aqui: ali o
    antecessor saiu do fluxo, então o sucessor conta normalmente.
    """
    return {v["sucessor"] for v in (vinculos or {}).values() if espelha(v["tipo"])}


def status_exibido(status_real, tipo):
    """Status que a tela mostra. Despriorizado VENCE: é decisão de gestão e não pode ser
    apagada por um fato derivado (§3.2.9)."""
    if status_real == STATUS_DESPRIORIZADO:
        return status_real
    if espelha(tipo):
        return STATUS_DESATUALIZADO
    return status_real


def etapa_exibida(etapa_real, tipo, etapa_sucessor):
    """Etapa que a tela mostra: espelho do sucessor quando o tipo espelha (§3.2.7)."""
    return etapa_sucessor if espelha(tipo) else etapa_real


def pode_editar_etapa(tipo):
    """Falso quando a etapa é espelho — o backend recusa a escrita, não só a tela."""
    return not espelha(tipo)
```

- [x] **Step 4: Rodar o teste e confirmar que passa**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculos.py -q
```

Esperado: `10 passed`.

- [ ] **Step 5: Commit (peça autorização antes de rodar)**

```bash
git add egps_analysis/app/backend/vinculos.py egps_analysis/app/backend/test_vinculos.py
git commit -m "feat(app): lógica pura do vínculo antecessor→sucessor"
```

---

## Task 2: Colunas do vínculo em `sas_egp_pipeline`

`egp_atualizado_key` **não é reaproveitada**: ela aponta para `sas_egp_atualizados.egp_key` (a sugestão da chegada, etapa 1 da spec) e tem 10 valores em prod. O vínculo real aponta para o **projeto do corpus** (`Área__nome__ATU<data>`), que é outra chave — por isso colunas novas.

**Files:**
- Modify: `egps_analysis/app/backend/main.py` (`_ensure_pipe_table`, classe `EgpPipe` em `main.py:4078`, endpoint em `main.py:4131`)

- [x] **Step 1: Escrever o teste que falha**

Crie `egps_analysis/app/backend/test_vinculo_endpoint.py`:

```python
# -*- coding: utf-8 -*-
"""Testes do vínculo no PATCH /api/egp-pipeline. run_sql stubado — sem credencial, sem rede."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from backend import main as m


def _mk_client(pipe_rows=None, projetos_corpus=("Cobranças__X__ATU20260923",)):
    """TestClient com run_sql stubado. `pipe_rows` é o que o SELECT de sas_egp_pipeline
    devolve; `projetos_corpus` é quem existe em sas_lineage_nodes (para a guarda do sucessor)."""
    calls = {"sql": []}

    def fake_run_sql(stmt, want_rows=True):
        calls["sql"].append(stmt)
        s = " ".join(stmt.split()).lower()
        if s.startswith("select") and "sas_egp_pipeline" in s and "limit 0" not in s:
            return list(pipe_rows or [])
        if s.startswith("select") and "sas_lineage_nodes" in s:
            return [{"projeto": p} for p in projetos_corpus]
        return []

    patches = [
        patch.object(m, "run_sql", side_effect=fake_run_sql),
        patch.object(m, "_require_gestao", lambda: None),
        patch.object(m, "_ensure_pipe_table", lambda: True),
    ]
    for p in patches:
        p.start()
    return TestClient(m.app), calls, patches


def _stop(patches):
    for p in patches:
        p.stop()


def test_patch_aceita_tipo_e_sucessor():
    client, calls, patches = _mk_client()
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Atualizado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 200, r.text
        gravado = " ".join(" ".join(calls["sql"]).split())
        assert "egp_vinculo_tipo" in gravado
        assert "egp_sucessor" in gravado
    finally:
        _stop(patches)


def test_patch_recusa_tipo_invalido():
    client, _calls, patches = _mk_client()
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Trocado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 400
        assert "tipo de vínculo" in r.text.lower()
    finally:
        _stop(patches)
```

- [x] **Step 2: Rodar e confirmar que falha**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculo_endpoint.py -q
```

Esperado: falha — o PATCH ignora os campos (o assert de `egp_vinculo_tipo` no SQL não encontra nada) e o tipo inválido devolve 200 em vez de 400.

- [x] **Step 3: Adicionar as colunas e o aceite no modelo**

Em `main.py`, na classe `EgpPipe` (`main.py:4078`), logo abaixo de `egp_atualizado_key`:

```python
    egp_atualizado_key: str | None = None  # vínculo manual p/ sas_egp_atualizados.egp_key ("" limpa)
    # Vínculo REAL antecessor -> sucessor (spec 2026-09-24 §1). Aponta para o PROJETO do
    # corpus (Área__nome__ATU<data>), não para a chave da aba — são chaves diferentes, e a
    # egp_atualizado_key acima segue sendo a sugestão da chegada.
    egp_vinculo_tipo: str | None = None    # Atualizado | Substituído | Unificado ("" limpa)
    egp_sucessor: str | None = None        # projeto do corpus ("" limpa)
```

Em `_ensure_pipe_table`, ao lado das outras migrações preguiçosas:

```python
    for _col in ("egp_vinculo_tipo", "egp_sucessor"):
        try:
            run_sql(f"SELECT {_col} FROM {T_PIPE} LIMIT 0")
        except HTTPException:
            run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS ({_col} STRING)", want_rows=False)
```

No corpo do `PATCH /api/egp-pipeline`, junto da validação dos outros campos (antes do MERGE):

```python
    if p.egp_vinculo_tipo:
        if not vinculos.tipo_valido(p.egp_vinculo_tipo):
            raise HTTPException(400, f"tipo de vínculo inválido: {p.egp_vinculo_tipo}")
```

E no topo do arquivo, junto dos outros imports locais:

```python
import vinculos
```

Inclua as duas colunas no MERGE (`main.py:4172` para o `UPDATE SET`, `main.py:4175` para a lista do `INSERT`), no `SELECT` que monta `old` (`main.py:4251`) e na lista de campos auditados — os três pontos onde `egp_atualizado_key` já aparece. As três edições seguem a forma:

```python
    # no UPDATE SET (main.py:4172)
    f"t.egp_vinculo_tipo = {sql_lit(tipo_new)}, t.egp_sucessor = {sql_lit(suc_new)}, "
    # na lista de colunas do INSERT (main.py:4175)
    "egp_vinculo_tipo, egp_sucessor, "
    # no SELECT de `old` (main.py:4251)
    "egp_vinculo_tipo, egp_sucessor, status_migracao, "
```

Calcule `tipo_new`/`suc_new` no mesmo padrão do `atukey_new` já existente (valor enviado quando não é `None`, senão o atual).

- [x] **Step 4: Rodar e confirmar que passa**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculo_endpoint.py -q
```

Esperado: `2 passed`.

- [ ] **Step 5: Commit (peça autorização antes de rodar)**

```bash
git add egps_analysis/app/backend/main.py egps_analysis/app/backend/test_vinculo_endpoint.py
git commit -m "feat(app): colunas do vínculo (tipo + sucessor) em sas_egp_pipeline"
```

---

## Task 3: Guardas do vínculo no servidor

Quatro recusas, todas com mensagem: quem não é da gestão (§3.5.19), sucessor que não existe no corpus (§2, etapa 3), antecessor já `Migrado` (§4) e edição de etapa espelhada (§3.2.7).

**Atenção:** `PATCH /api/egp-pipeline` (`main.py:4131`) **não** chama `_require_gestao` hoje — etapa/status são editáveis por qualquer usuário autenticado, e isso continua. A guarda vale **só para os campos do vínculo**: gatear o endpoint inteiro tiraria de todo mundo uma edição que hoje é aberta.

**Files:**
- Modify: `egps_analysis/app/backend/main.py` (corpo do `PATCH /api/egp-pipeline`)
- Test: `egps_analysis/app/backend/test_vinculo_endpoint.py`

- [x] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `test_vinculo_endpoint.py`:

```python
def test_recusa_vinculo_de_quem_nao_e_gestao():
    # Classificar como Substituído faz um EGP entrar no escopo e outro fechar: é decisão de
    # escopo, com o mesmo peso de um DOR1 (spec §3.5.19).
    from fastapi import HTTPException

    def nega():
        raise HTTPException(403, "Restrito ao grupo de gestão (bv_users).")

    client, _calls, patches = _mk_client()
    patch_g = patch.object(m, "_require_gestao", side_effect=nega)
    patch_g.start()
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Atualizado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 403
    finally:
        patch_g.stop()
        _stop(patches)


def test_etapa_e_status_seguem_abertos_sem_gestao():
    # A guarda é SÓ dos campos de vínculo: editar etapa/status continua aberto, como hoje.
    from fastapi import HTTPException

    def nega():
        raise HTTPException(403, "Restrito ao grupo de gestão (bv_users).")

    client, _calls, patches = _mk_client(pipe_rows=[
        {"projeto": "Cobranças__X", "status_migracao": "Em Andamento",
         "etapa_migracao": "Pré-conversão"}])
    patch_g = patch.object(m, "_require_gestao", side_effect=nega)
    patch_g.start()
    try:
        r = client.patch("/api/egp-pipeline",
                         json={"projeto": "Cobranças__X", "etapa": "Validação em DES"})
        assert r.status_code == 200, r.text
    finally:
        patch_g.stop()
        _stop(patches)


def test_recusa_sucessor_fora_do_corpus():
    # O ponteiro só pode apontar para projeto que já existe: antes disso o espelhamento
    # agiria sobre o vazio (spec §2, etapa 3).
    client, _calls, patches = _mk_client(projetos_corpus=("Cobranças__Outro",))
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Atualizado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 404
        assert "corpus" in r.text.lower()
    finally:
        _stop(patches)


def test_recusa_vincular_egp_migrado():
    client, _calls, patches = _mk_client(pipe_rows=[
        {"projeto": "Cobranças__X", "status_migracao": "Migrado", "etapa_migracao": "Migrado"}])
    try:
        r = client.patch("/api/egp-pipeline", json={
            "projeto": "Cobranças__X",
            "egp_vinculo_tipo": "Atualizado",
            "egp_sucessor": "Cobranças__X__ATU20260923"})
        assert r.status_code == 409
        assert "migrado" in r.text.lower()
    finally:
        _stop(patches)


def test_recusa_editar_etapa_espelhada():
    client, _calls, patches = _mk_client(pipe_rows=[
        {"projeto": "Cobranças__X", "status_migracao": "Em Andamento",
         "etapa_migracao": "Pré-conversão", "egp_vinculo_tipo": "Atualizado",
         "egp_sucessor": "Cobranças__X__ATU20260923"}])
    try:
        r = client.patch("/api/egp-pipeline",
                         json={"projeto": "Cobranças__X", "etapa": "Validação em DES"})
        assert r.status_code == 409
        assert "espelh" in r.text.lower()
    finally:
        _stop(patches)


def test_permite_editar_etapa_em_substituido():
    # Substituído não espelha: a etapa do antecessor continua editável.
    client, _calls, patches = _mk_client(pipe_rows=[
        {"projeto": "Cobranças__X", "status_migracao": "Em Andamento",
         "etapa_migracao": "Pré-conversão", "egp_vinculo_tipo": "Substituído",
         "egp_sucessor": "Cobranças__Novo"}])
    try:
        r = client.patch("/api/egp-pipeline",
                         json={"projeto": "Cobranças__X", "etapa": "Validação em DES"})
        assert r.status_code == 200, r.text
    finally:
        _stop(patches)
```

- [x] **Step 2: Rodar e confirmar que falham**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculo_endpoint.py -q
```

Esperado: os 6 novos falham — o endpoint devolve 200 onde deveria 403/404/409.

- [x] **Step 3: Implementar as guardas**

No `PATCH /api/egp-pipeline`, depois de ler a linha atual (`old`) e antes do MERGE:

```python
    # Guardas do vínculo (spec §2 etapa 3, §3.2.7, §3.5.19 e §4). Tudo aqui RECUSA — nunca
    # decide sozinho: o estado que o app não sabe reconciliar é melhor falhar alto do que
    # adivinhar.
    #
    # O gate de gestão é SÓ dos campos de vínculo: este endpoint é aberto para etapa/status
    # desde sempre, e fechá-lo inteiro tiraria de todo mundo uma edição que hoje funciona.
    if p.egp_vinculo_tipo is not None or p.egp_sucessor is not None:
        _require_gestao()

    _tipo_atual = (old.get("egp_vinculo_tipo") or "") if old else ""
    _tipo_novo = p.egp_vinculo_tipo if p.egp_vinculo_tipo is not None else _tipo_atual

    if p.egp_sucessor:
        _no_corpus = {r["projeto"] for r in run_sql(
            f"SELECT projeto FROM {T_ND} WHERE projeto = {sql_lit(p.egp_sucessor)}")}
        if p.egp_sucessor not in _no_corpus:
            raise HTTPException(404, f"sucessor '{p.egp_sucessor}' não está no corpus — "
                                     "rode o pipeline (extrator + orquestrador + publish) antes de vincular")
        # Migrado é terminal: um EGP em produção e validado não recebe sucessor. Não deve
        # acontecer (em 24/09/2026 nenhum antecessor estava nesse status); se acontecer, o
        # app recusa em vez de inventar regra.
        if (old or {}).get("status_migracao") == "Migrado":
            raise HTTPException(409, "EGP com status Migrado não recebe sucessor — "
                                     "reabra o status antes de vincular")

    # Etapa espelhada é read-only no SERVIDOR, não só na tela: só o front deixaria a
    # próxima integração escrever por baixo.
    if p.etapa is not None and not vinculos.pode_editar_etapa(_tipo_novo):
        raise HTTPException(409, "etapa espelhada do sucessor — edite a etapa no EGP sucessor")
```

Garanta que o `SELECT` que monta `old` traga `egp_vinculo_tipo`, `egp_sucessor` e `status_migracao`.

- [x] **Step 4: Rodar e confirmar que passam**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculo_endpoint.py -q
```

Esperado: `8 passed`.

- [ ] **Step 5: Commit (peça autorização antes de rodar)**

```bash
git add egps_analysis/app/backend/main.py egps_analysis/app/backend/test_vinculo_endpoint.py
git commit -m "feat(app): guardas do vínculo (gestão, sucessor no corpus, Migrado, etapa espelhada)"
```

---

## Task 4: Derivação no `/api/egp-readiness`

**Files:**
- Modify: `egps_analysis/app/backend/main.py` (`_egp_readiness_rows`)
- Test: `egps_analysis/app/backend/test_vinculos.py`

- [x] **Step 1: Escrever o teste que falha**

Acrescente a `test_vinculos.py`:

```python
def test_anexa_vinculo_espelha_etapa_e_status():
    """A função que o main injeta nas linhas do readiness: etapa vem do sucessor,
    status vira Desatualizado, e o sucessor é marcado como tal."""
    linhas = [
        {"projeto": "A__velho", "etapa": "Pré-conversão", "status": "Em Andamento"},
        {"projeto": "A__novo", "etapa": "Validação em DES", "status": "Em Andamento"},
        {"projeto": "A__solto", "etapa": "Pré-conversão", "status": "Block"},
    ]
    vin = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__novo"}}
    v.anexa_vinculo(linhas, vin)
    velho, novo, solto = linhas
    assert velho["etapa"] == "Validação em DES"      # espelhada
    assert velho["status"] == "Desatualizado"
    assert velho["etapa_editavel"] is False
    assert velho["vinculo_tipo"] == "Atualizado"
    assert velho["sucessor"] == "A__novo"
    assert novo["e_sucessor"] is True
    assert novo["etapa"] == "Validação em DES"       # o sucessor é quem tem a etapa de verdade
    assert solto["status"] == "Block"                # sem vínculo, nada muda
    assert solto["etapa_editavel"] is True
    assert solto.get("e_sucessor") is False


def test_anexa_vinculo_sucessor_ausente_nao_espelha_etapa_fantasma():
    """Sucessor fora do recorte carregado: a etapa espelhada fica vazia em vez de manter a
    velha — mostrar a etapa antiga como se fosse a nova é a falha silenciosa a evitar."""
    linhas = [{"projeto": "A__velho", "etapa": "Pré-conversão", "status": "Em Andamento"}]
    v.anexa_vinculo(linhas, {"A__velho": {"tipo": "Atualizado", "sucessor": "A__fora"}})
    assert linhas[0]["etapa"] is None
    assert linhas[0]["status"] == "Desatualizado"
```

- [x] **Step 2: Rodar e confirmar que falha**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculos.py -q
```

Esperado: `AttributeError: module 'vinculos' has no attribute 'anexa_vinculo'`.

- [x] **Step 3: Implementar `anexa_vinculo`**

Acrescente a `vinculos.py`:

```python
def anexa_vinculo(linhas, vinculos_por_antecessor):
    """Aplica o vínculo IN-PLACE nas linhas do readiness.

    Escreve em cada linha: vinculo_tipo, sucessor, e_sucessor, etapa_editavel — e
    SOBRESCREVE etapa/status pelos valores exibidos. É derivação de leitura: o banco segue
    com o status real.
    """
    etapa_por_projeto = {r.get("projeto"): r.get("etapa") for r in linhas}
    espelhados = sucessores_espelhados(vinculos_por_antecessor)
    for r in linhas:
        projeto = r.get("projeto")
        vinc = (vinculos_por_antecessor or {}).get(projeto)
        tipo = vinc["tipo"] if vinc else None
        r["vinculo_tipo"] = tipo
        r["sucessor"] = vinc["sucessor"] if vinc else None
        r["e_sucessor"] = projeto in espelhados
        r["etapa_editavel"] = pode_editar_etapa(tipo)
        if vinc:
            # .get sem default: sucessor fora do recorte carregado vira None, e a tela
            # mostra "sem etapa" em vez de exibir a etapa VELHA como se fosse a nova.
            r["etapa"] = etapa_exibida(r.get("etapa"), tipo,
                                       etapa_por_projeto.get(vinc["sucessor"]))
            r["status"] = status_exibido(r.get("status"), tipo)
    return linhas
```

- [x] **Step 4: Rodar e confirmar que passa**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculos.py -q
```

Esperado: `12 passed`.

- [x] **Step 5: Ligar no readiness**

Em `main.py`, dentro de `_egp_readiness_rows`, depois de montar `rows` e antes do `rows.sort(...)`:

```python
    # Vínculo antecessor -> sucessor: derivação de leitura (spec §3.2). Falhar aqui não
    # pode derrubar a aba — sem vínculo, as linhas seguem com etapa/status reais.
    _vinc = {}   # inicializado ANTES do try: a Task 5 usa `_vinc` no return, e sem isto
                 # uma falha na leitura viraria NameError no lugar de degradar.
    try:
        _vinc = vinculos.mapa_vinculos(run_sql(
            f"SELECT projeto, egp_vinculo_tipo, egp_sucessor FROM {T_PIPE}"))
        vinculos.anexa_vinculo(rows, _vinc)
    except HTTPException as e:
        print(f"[readiness] vínculos não carregados ({e.detail}); linhas sem espelhamento",
              file=sys.stderr)
```

- [x] **Step 6: Rodar a suíte inteira do backend**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest -q
```

Esperado: tudo verde; nenhum teste existente quebrado.

- [ ] **Step 7: Commit (peça autorização antes de rodar)**

```bash
git add egps_analysis/app/backend/vinculos.py egps_analysis/app/backend/test_vinculos.py egps_analysis/app/backend/main.py
git commit -m "feat(app): deriva etapa espelhada e status Desatualizado no readiness"
```

---

## Task 5: Sucessor no recorte, fora do denominador

Duas metades da mesma regra (§3.1.2): o sucessor **entra** no `indi_deps` (senão ele e os inputs dele não aparecem em lugar nenhum) e **sai** do total de EGPs quando o tipo espelha.

**Files:**
- Modify: `egps_analysis/app/backend/main.py` (`_frontier_egps`, retorno de `_egp_readiness_rows`)
- Test: `egps_analysis/app/backend/test_vinculos.py`

- [x] **Step 1: Escrever o teste que falha**

Acrescente a `test_vinculos.py`:

```python
def test_total_desconta_sucessor_espelhado():
    frontier = {"A__velho", "A__novo", "A__solto"}
    vin = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__novo"}}
    # A__novo está no recorte (aparece na lista e traz os inputs dele) mas não no total:
    # o avanço dele já conta na linha de A__velho, via etapa espelhada.
    assert v.total_egps(frontier, vin) == 2


def test_total_conta_sucessor_de_substituido():
    frontier = {"A__velho", "A__novo"}
    vin = {"A__velho": {"tipo": "Substituído", "sucessor": "A__novo"}}
    # Aqui o antecessor saiu do fluxo (fecha como Despriorizado e Contabilizado) e o
    # sucessor entra no escopo: contam os dois, sem dupla contagem.
    assert v.total_egps(frontier, vin) == 2


def test_total_ignora_sucessor_fora_do_recorte():
    frontier = {"A__velho"}
    vin = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__fora"}}
    assert v.total_egps(frontier, vin) == 1
```

- [x] **Step 2: Rodar e confirmar que falha**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculos.py -q
```

Esperado: `AttributeError: module 'vinculos' has no attribute 'total_egps'`.

- [x] **Step 3: Implementar**

Acrescente a `vinculos.py`:

```python
def total_egps(frontier, vinculos_por_antecessor):
    """Tamanho do recorte para o CARD de total: o recorte menos os sucessores espelhados.

    Regra numa frase (§3.1.2): quem espelha não conta duas vezes; quem substitui, conta.
    """
    return len(set(frontier) - sucessores_espelhados(vinculos_por_antecessor))
```

- [x] **Step 4: Rodar e confirmar que passa**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest test_vinculos.py -q
```

Esperado: `15 passed`.

- [x] **Step 5: Ligar no `_frontier_egps` e no card**

Em `main.py`, dentro de `_frontier_egps`, no ramo `indi_deps`, troque o `return set(level), base` por:

```python
        # Sucessores entram no recorte POR REGRA (§3.1.2): não são dependência de ninguém,
        # então o grafo nunca os traria — e sem eles os inputs da versão nova não aparecem.
        # Só entram os sucessores de antecessores que já estão no recorte.
        try:
            vinc = vinculos.mapa_vinculos(run_sql(
                f"SELECT projeto, egp_vinculo_tipo, egp_sucessor FROM {T_PIPE}"))
        except HTTPException:
            vinc = {}
        suc = {v["sucessor"] for p, v in vinc.items() if p in level}
        return set(level) | suc, base
```

No `return` de `_egp_readiness_rows`, troque a linha do total por:

```python
        "total": vinculos.total_egps(frontier, _vinc) + len(ex_contab),
```

- [x] **Step 6: Verificar que o cache invalida no vínculo**

`_frontier_egps` é cacheado por geração (`_cache_lineage`). O PATCH que grava vínculo precisa bumpar `_lineage_gen`, como os outros endpoints que mexem em recorte já fazem — sem isso o recorte só muda no próximo restart. Confirme que o `PATCH /api/egp-pipeline` bumpa; se não, acrescente o bump ao lado da invalidação existente.

- [x] **Step 7: Rodar a suíte inteira**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest -q
```

Esperado: tudo verde.

- [ ] **Step 8: Commit (peça autorização antes de rodar)**

```bash
git add egps_analysis/app/backend/vinculos.py egps_analysis/app/backend/test_vinculos.py egps_analysis/app/backend/main.py
git commit -m "feat(app): sucessor entra no recorte e fica fora do denominador"
```

---

> **Pendente, aprovado em 25/09 (fora das Tasks 1–7):** a **etapa** também é copiada para o
> sucessor no ato do vínculo, junto de mês/Jira/responsável — senão o antecessor passa a
> espelhar a etapa vazia do sucessor recém-criado e some da distribuição do funil `+deps`,
> sem que trabalho algum tenha sido desfeito. Ver §3.3.11 da spec e o ticket 07.

## Task 6: Frontend — status, coluna e etapa read-only

**Files:**
- Modify: `egps_analysis/app/frontend/src/pipeline.ts`
- Modify: `egps_analysis/app/frontend/src/types.ts`
- Modify: `egps_analysis/app/frontend/src/components/ReadinessView.tsx`
- Test: `egps_analysis/app/frontend/pipeline.test.mts`

- [x] **Step 1: Escrever o teste que falha**

Acrescente a `egps_analysis/app/frontend/pipeline.test.mts`:

```typescript
test("sucessor espelhado não conta no total de EGPs", () => {
  // Espelha _prio_contabiliza/total_egps no backend: o avanço do sucessor já conta na
  // linha do antecessor, então somar os dois seria contar o mesmo trabalho duas vezes.
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "Validação em DES", e_sucessor: true }), false);
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "Validação em DES", e_sucessor: false }), true);
  assert.equal(contaNoTotalEgp({ tipo: "escopo", etapa: "Validação em DES" }), true);
});

test("Desatualizado é status conhecido e não é Migrado", () => {
  assert.ok(STATUS_PROJETO.includes("Desatualizado"));
  assert.ok(SEG["Desatualizado"], "precisa de cor no SEG, senão a banda sai sem estilo");
  assert.notEqual("Desatualizado", "Migrado");
});
```

Garanta que o `import` no topo do arquivo traga `contaNoTotalEgp`, `STATUS_PROJETO` e `SEG`.

- [x] **Step 2: Rodar e confirmar que falha**

```bash
cd egps_analysis/app/frontend && node --test --experimental-strip-types pipeline.test.mts
```

Esperado: falha — `contaNoTotalEgp` ignora `e_sucessor` e `Desatualizado` não está em `STATUS_PROJETO`.

- [x] **Step 3: Implementar em `pipeline.ts`**

Acrescente `"Desatualizado"` a `STATUS_PROJETO`, uma entrada em `SEG` (tom próprio, distinto de `Migrado`) e uma linha em `STATUS_HELP`:

```typescript
// Derivado do vínculo, nunca gravado: o EGP tem sucessor e a etapa dele é espelho.
// Conta nos totais e nunca conta como migrado (spec §3.2.5).
Desatualizado: "Desatualizado: existe versão nova (sucessor) e a etapa é espelho dela — edite no sucessor.",
```

E estenda o predicado do denominador:

```typescript
export function contaNoTotalEgp(r: { tipo?: string; etapa?: string | null; e_sucessor?: boolean }): boolean {
  // Sucessor espelhado: listado, filtrável, com inputs contando — mas fora do total,
  // porque o avanço dele já conta na linha do antecessor (spec §3.1.2).
  if (r.e_sucessor) return false;
  if (r.tipo !== "ex_dependencia") return true;
  return !!r.etapa && !PHANTOM_ETAPAS_MIGRACAO.includes(r.etapa);
}
```

- [x] **Step 4: Rodar e confirmar que passa**

```bash
cd egps_analysis/app/frontend && node --test --experimental-strip-types pipeline.test.mts
```

Esperado: todos passam.

- [x] **Step 5: Campos novos em `types.ts`**

Em `ReadinessRow`:

```typescript
  vinculo_tipo?: string | null;   // Atualizado | Substituído | Unificado
  sucessor?: string | null;       // projeto do corpus que substitui este
  e_sucessor?: boolean;           // esta linha É o sucessor de alguém (fora do total)
  etapa_editavel?: boolean;       // false = etapa é espelho; o backend recusa a escrita
```

- [x] **Step 6: Coluna e etapa read-only em `ReadinessView.tsx`**

No `<select>` de etapa da linha, desabilite quando a etapa for espelho:

```tsx
<select value={r.etapa ?? ""} disabled={r.etapa_editavel === false}
  title={r.etapa_editavel === false
    ? `Etapa espelhada de "${r.sucessor}" — edite no EGP sucessor`
    : undefined}
  onChange={(e) => pipeMut.mutate({ projeto: r.projeto, etapa: e.target.value })}>
```

Acrescente `"sucessor"` ao `TIPO_LABEL` (4º valor do filtro Tipo, que já só aparece em `indi_deps`):

```typescript
const TIPO_LABEL: Record<string, string> = {
  escopo: "escopo", dependencia: "dependência", ex_dependencia: "ex-dependência",
  sucessor: "sucessor",
};
```

E marque a linha do sucessor: onde `tipo` é calculado para exibição, use `r.e_sucessor ? "sucessor" : r.tipo`.

- [x] **Step 7: Typecheck e testes**

```bash
cd egps_analysis/app/frontend && ./node_modules/.bin/tsc -b --noEmit && node --test --experimental-strip-types *.test.mts
```

Esperado: `tsc` sem saída (exit 0) e todos os testes passando.

- [ ] **Step 8: Commit (peça autorização antes de rodar)**

```bash
git add egps_analysis/app/frontend/src/pipeline.ts egps_analysis/app/frontend/src/types.ts egps_analysis/app/frontend/src/components/ReadinessView.tsx egps_analysis/app/frontend/pipeline.test.mts
git commit -m "feat(app): status Desatualizado, coluna de vínculo e etapa read-only na aba EGPs"
```

---

## Task 7: Coluna `Desatualizado` no Kanban

Reusa a precedência que `separarDespriorizados` já implementa: o status vira chave de coluna e sobrepõe a etapa (§3.2.10).

**Files:**
- Modify: `egps_analysis/app/frontend/src/components/GestaoKanban.tsx`

- [x] **Step 1: Escrever o teste que falha**

Crie `egps_analysis/app/frontend/kanban-coluna.test.mts`:

```typescript
import { test } from "node:test";
import assert from "node:assert/strict";
import { kanbanColKeyOf, buildKanbanColunas, STATUS_DESPRIORIZADO, STATUS_DESATUALIZADO }
  from "./src/components/GestaoKanban";

test("desatualizado vira coluna própria, sobrepondo a etapa", () => {
  const r = { id: "A__x", etapa: "Validação em DES", status: STATUS_DESATUALIZADO } as never;
  assert.equal(kanbanColKeyOf(r, "egp", ["Validação em DES"], { separarDespriorizados: true }),
    STATUS_DESATUALIZADO);
});

test("despriorizado vence desatualizado", () => {
  // Só cabe um status; a despriorização é decisão de gestão e não é apagada pelo vínculo.
  const r = { id: "A__x", etapa: "Validação em DES", status: STATUS_DESPRIORIZADO } as never;
  assert.equal(kanbanColKeyOf(r, "egp", ["Validação em DES"], { separarDespriorizados: true }),
    STATUS_DESPRIORIZADO);
});

test("a coluna Desatualizado existe no board de EGP", () => {
  assert.ok(buildKanbanColunas("egp", { separarDespriorizados: true }).includes(STATUS_DESATUALIZADO));
});
```

- [x] **Step 2: Rodar e confirmar que falha**

```bash
cd egps_analysis/app/frontend && node --test --experimental-strip-types kanban-coluna.test.mts
```

Esperado: falha no import — `STATUS_DESATUALIZADO` não é exportado.

- [x] **Step 3: Implementar**

Em `GestaoKanban.tsx`, ao lado de `STATUS_DESPRIORIZADO`:

```typescript
// Coluna própria para o EGP com sucessor: ele sai da trilha de etapas porque o trabalho
// está acontecendo no sucessor. Mesma mecânica do despriorizado — status como chave de
// coluna —, e NÃO uma etapa nova. Não colide com nenhuma etapa real.
export const STATUS_DESATUALIZADO = "Desatualizado";
```

Em `buildKanbanColunas` (o bloco `if (opts?.separarDespriorizados)`, por volta de `GestaoKanban.tsx:98`), acrescente `STATUS_DESATUALIZADO` **antes** de `STATUS_DESPRIORIZADO` na lista de colunas. Em `kanbanColKeyOf` (por volta de `GestaoKanban.tsx:114`), a checagem fica:

```typescript
  if (opts?.separarDespriorizados && entity === "egp") {
    // Despriorizado PRIMEIRO: só cabe um status, e a despriorização é decisão de gestão —
    // o vínculo não a apaga (spec §3.2.9).
    if (r.status === STATUS_DESPRIORIZADO) return STATUS_DESPRIORIZADO;
    if (r.status === STATUS_DESATUALIZADO) return STATUS_DESATUALIZADO;
  }
```

- [x] **Step 4: Rodar e confirmar que passa**

```bash
cd egps_analysis/app/frontend && node --test --experimental-strip-types kanban-coluna.test.mts && ./node_modules/.bin/tsc -b --noEmit
```

Esperado: 3 testes passando e `tsc` limpo.

- [ ] **Step 5: Commit (peça autorização antes de rodar)**

```bash
git add egps_analysis/app/frontend/src/components/GestaoKanban.tsx egps_analysis/app/frontend/kanban-coluna.test.mts
git commit -m "feat(app): coluna Desatualizado no Kanban de EGPs"
```

---

## Task 8: Entrada do sucessor no corpus (processo, sem código)

A chave do corpus é `Área__nome`, derivada do **nome do arquivo** (`egps_extractor.py:3174`: `project_id = sanitize(f"{business_area}__{base_name}")`), e a área vem do nome da subpasta de 1º nível. Isso significa que **não há código a escrever**: basta nomear o arquivo com o sufixo e apontar o extrator para a pasta irmã.

**Files:**
- Modify: `egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md`

- [ ] **Step 1: Validar o caminho com um arquivo real**

Coloque um `.egp` de teste em `egps_analysis/received_egps_atualizados/Cobranças/` nomeado com o sufixo (ex.: `COLCHAO_ACORDO_CL__ATU20260923.egp`) e rode:

```bash
cd egps_analysis && python egps_extractor.py received_egps_atualizados
```

Esperado: nasce `text_egps/COLCHAO_ACORDO_CL__ATU20260923.txt` com o cabeçalho
`PROJECT: Cobranças__COLCHAO_ACORDO_CL__ATU20260923` e `BUSINESS_AREA: Cobranças`.

- [ ] **Step 2: Conferir o cabeçalho**

```bash
cd egps_analysis && head -8 "text_egps/COLCHAO_ACORDO_CL__ATU20260923.txt"
```

Esperado: as duas linhas acima, com o sufixo presente no `PROJECT` — é o que garante que o sucessor não colide com o antecessor de mesmo nome.

- [ ] **Step 3: Documentar o procedimento**

Em `egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md`, acrescente uma seção:

```markdown
### Versões atualizadas: pasta irmã `received_egps_atualizados/`

`.egp` reenviado pelo cliente vai para `received_egps_atualizados/<AREA>/`, com a mesma
estrutura de `received_egps/` (a área sai do nome da subpasta de 1º nível — subpasta mais
funda não é varrida para `.egp`).

**O arquivo precisa chegar já nomeado com o sufixo de recebimento**: `<NOME>__ATU<AAAAMMDD>.egp`.
A chave do corpus é `Área__nome` derivada do nome do arquivo, e 12 versões têm nome idêntico
ao antecessor — sem o sufixo, o sucessor sobrescreve o antecessor. Não use `__v2`/`__v3`:
no corpus isso já significa homônimo de outra pasta.

Para incorporar, rode o extrator nas DUAS pastas antes do orquestrador (os dois escrevem
no mesmo `text_egps/`):

```bash
python egps_extractor.py received_egps
python egps_extractor.py received_egps_atualizados
python orchestrator_inventory.py
```
```

- [ ] **Step 4: Limpar o arquivo de teste**

```bash
cd egps_analysis && rm -f "text_egps/COLCHAO_ACORDO_CL__ATU20260923.txt"
```

Remova também o `.egp` de teste da pasta, se ele não for uma versão real a incorporar.

- [ ] **Step 5: Commit (peça autorização antes de rodar)**

```bash
git add egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md
git commit -m "docs: pasta irmã e regra de nomeação das versões atualizadas"
```

---

## Verificação final (depois das 8 tarefas)

- [ ] **Suíte do backend**

```bash
cd egps_analysis/app/backend && ../../venv/bin/python3 -m pytest -q
```

Esperado: tudo verde.

- [ ] **Suíte e typecheck do frontend**

```bash
cd egps_analysis/app/frontend && ./node_modules/.bin/tsc -b --noEmit && node --test --experimental-strip-types *.test.mts
```

Esperado: `tsc` sem saída e todos os testes passando.

- [ ] **Regressão dos quatro funis (critério de aceite da spec)**

Com o app rodando localmente contra prod em leitura, compare `/api/funis` antes e depois da mudança:

```bash
cd egps_analysis/app && ./local_app.sh
```

Esperado: `migracao`, `ingestao`, `migracao_deps` e `ingestao_deps` devolvem **exatamente os mesmos números**. Se algum mudou, o sucessor vazou para o denominador — o bug que a §3.1.2 existe para impedir.

- [ ] **Conferência do card da aba EGPs**

No recorte `indi_deps`, sem nenhum vínculo criado, o card de total e a contagem de linhas devem ficar como estão hoje (192 e 192, com o chip de ex-dependência desligado). Criar o primeiro vínculo `Atualizado` deve **manter** o total e acrescentar 1 linha (a do sucessor, marcada como `sucessor` no filtro Tipo).
