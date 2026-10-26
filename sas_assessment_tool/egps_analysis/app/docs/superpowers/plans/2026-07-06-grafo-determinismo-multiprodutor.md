# Grafo determinístico e completo (multi-produtor) — Implementation Plan

> **For agentic workers:** implementar tarefa a tarefa. `orchestrator_inventory.py` e `publish_to_databricks.py` estão **indexados/Read-bloqueados** pelo context-guard → editar via **patch scripts Python** (ler bytes, replace com anchor único + assert de contagem, escrever, `py_compile`). Fonte da verdade = `egps_analysis/*.py`; espelhar em `egps_analysis/app/pipeline/*.py` (hoje idênticos).

**Goal:** report 03 determinístico (invariante à ordem de `os.listdir`) e completo (todas as arestas candidatas por tabela multi-produtor), com `n_produtores` propagado até `sas_lineage_edges.max_produtores`. Sem tocar `main.py`/frontend nem prod.

**Architecture:** `table_to_generator` (escolha única, last-writer-wins) vira `table_to_producers` (conjunto). O bloco de arestas principal itera todos os produtores; os blocos de recuperação (`.sas7bdat`/path) idem, dentro dos guards existentes. Cada aresta carrega `n_produtores`. `publish` agrega `max_produtores` por `(alvo,dep)`.

**Tech Stack:** Python 3 (venv `egps_analysis/venv`, tem openpyxl/pandas), databricks-sdk (só dry-run aqui), csv.

---

### Task 1: Patch do orchestrator (source + vendored)

**Files:**
- Modify: `egps_analysis/orchestrator_inventory.py` (linhas ~665, ~726/762–771, ~789–810, ~811–828, ~833–869, ~890–899)
- Modify (espelho): `egps_analysis/app/pipeline/orchestrator_inventory.py`
- Create (efêmero): `scratchpad/patch_orch.py`

- [ ] **Step 1: Escrever o patch script** com 6 replaces anchor-únicos:

  1. **Sort listdir** (~665):
     - de: `txt_files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith('.txt')]`
     - para: `txt_files = sorted(f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith('.txt'))`
  2. **Declarar `table_to_producers`** — logo após `table_to_generator = {}` (~726):
     - inserir linha: `table_to_producers = defaultdict(set)`
  3. **Popular producers + derivar generator** — no bloco (~768–771):
     - de:
       ```
               k = _canonical_table_key(tb)
               table_to_generator[k] = proj
               proj_output_keys[proj].add(k)
               out_member_index[_member_key(tb)].add(proj)
       ```
     - para:
       ```
               k = _canonical_table_key(tb)
               table_to_producers[k].add(proj)
               proj_output_keys[proj].add(k)
               out_member_index[_member_key(tb)].add(proj)
       ```
     - e inserir, após o `for proj, data in project_catalog.items(): ... loop` de outputs (antes de `adj_list = defaultdict(list)`), a derivação:
       ```
       table_to_generator = {k: sorted(ps)[0] for k, ps in table_to_producers.items()}
       ```
  4. **Bloco de arestas principal** (~789–802) — de:
     ```
             k_in = _canonical_table_key(inp_table)
             generator = table_to_generator.get(k_in)
             if generator and generator != proj:
                 if k_in in proj_output_keys.get(proj, ()):
                     # leitor TAMBEM escreve a tabela: partilha/append, nao e produtor→consumidor
                     continue
                 if proj not in adj_list[generator]:
                     adj_list[generator].append(proj)
                     in_degree[proj] += 1
                 if (proj, generator, inp_table) not in seen_matrix:
                     seen_matrix.add((proj, generator, inp_table))
                     matrix_rows.append([proj, generator, inp_table])
     ```
     - para:
     ```
             k_in = _canonical_table_key(inp_table)
             if k_in in proj_output_keys.get(proj, ()):
                 # leitor TAMBEM escreve a tabela: partilha/append, nao e produtor→consumidor
                 continue
             producers = table_to_producers.get(k_in, ())
             n_prod = len(producers)
             for generator in sorted(producers):
                 if generator == proj:
                     continue
                 if proj not in adj_list[generator]:
                     adj_list[generator].append(proj)
                     in_degree[proj] += 1
                 if (proj, generator, inp_table) not in seen_matrix:
                     seen_matrix.add((proj, generator, inp_table))
                     matrix_rows.append([proj, generator, inp_table, n_prod])
     ```
  5. **Bloco `.sas7bdat`** (~816–828) — de:
     ```
                 producers = out_member_index.get(key)
                 if not producers or proj in producers or len(producers) > 3:
                     continue
                 generator = sorted(producers)[0]
                 if generator == proj:
                     continue
                 if proj not in adj_list[generator]:
                     adj_list[generator].append(proj)
                     in_degree[proj] += 1
                 rk = (proj, generator, fr)
                 if rk not in seen_matrix:
                     seen_matrix.add(rk)
                     matrix_rows.append([proj, generator, fr])
     ```
     - para (mantém guards; emite todos; anexa n_prod):
     ```
                 producers = out_member_index.get(key)
                 if not producers or proj in producers or len(producers) > 3:
                     continue
                 n_prod = len(producers)
                 for generator in sorted(producers):
                     if generator == proj:
                         continue
                     if proj not in adj_list[generator]:
                         adj_list[generator].append(proj)
                         in_degree[proj] += 1
                     rk = (proj, generator, fr)
                     if rk not in seen_matrix:
                         seen_matrix.add(rk)
                         matrix_rows.append([proj, generator, fr, n_prod])
     ```
  6. **Bloco path-recovery** (~842–869) — `gen_path` vira multimap e emite todos:
     - de: `gen_path = {}` → para: `gen_path = defaultdict(set)`
     - de: `gen_path[(p, member)] = proj` → para: `gen_path[(p, member)].add(proj)`
     - de:
       ```
                 g = gen_path.get(key)
                 if g and g != proj:
                     if proj not in adj_list[g]:
                         adj_list[g].append(proj)
                         in_degree[proj] += 1
                     rk = (proj, g, inp_table)
                     if rk not in seen_matrix:
                         seen_matrix.add(rk)
                         matrix_rows.append([proj, g, inp_table])
                         rec_path_edges += 1
       ```
     - para:
       ```
                 gs = gen_path.get(key, ())
                 n_prod = len(gs)
                 for g in sorted(gs):
                     if g == proj:
                         continue
                     if proj not in adj_list[g]:
                         adj_list[g].append(proj)
                         in_degree[proj] += 1
                     rk = (proj, g, inp_table)
                     if rk not in seen_matrix:
                         seen_matrix.add(rk)
                         matrix_rows.append([proj, g, inp_table, n_prod])
                         rec_path_edges += 1
       ```
  7. **Writer do report 03** (~890–899) — header + row:
     - de: `['Projeto_Alvo (Precisa Migrar)', 'Depende_Do_Projeto', 'Via_Tabela', 'project_extension', 'created_at']`
     - para: `['Projeto_Alvo (Precisa Migrar)', 'Depende_Do_Projeto', 'Via_Tabela', 'n_produtores', 'project_extension', 'created_at']`
     - o `writer.writerow(row + [ext, created_at])` **não muda** (row agora tem 4 elementos).

  Cada replace: `assert src.count(anchor) == 1, anchor`. Aplicar o mesmo conjunto aos dois arquivos (source + vendored).

- [ ] **Step 2: Rodar o patch + `py_compile`**
  Run: `python3 scratchpad/patch_orch.py && python3 -m py_compile orchestrator_inventory.py app/pipeline/orchestrator_inventory.py`
  Expected: "OK" + compile limpo.

- [ ] **Step 3: Confirmar paridade source/vendored**
  Run: `diff -q orchestrator_inventory.py app/pipeline/orchestrator_inventory.py`
  Expected: idênticos.

- [ ] **Step 4: Commit** — NÃO (regra do usuário: sem commit sem pedido). Pular.

---

### Task 2: Patch do publish (source + vendored)

**Files:**
- Modify: `egps_analysis/publish_to_databricks.py` (~458–472, DDL ~821, `ed_cols` ~693)
- Modify (espelho): `egps_analysis/app/pipeline/publish_to_databricks.py`
- Create (efêmero): `scratchpad/patch_publish.py`

- [ ] **Step 1: Escrever o patch script** com 3 replaces:
  1. **Agregação de edges** (~458–472) — de:
     ```
         edges = collections.defaultdict(set)
         with open(R03, newline="", encoding="utf-8") as f:
             rd = csv.DictReader(f)
             c = rd.fieldnames
             for r in rd:
                 alvo = r[c[0]].strip()
                 dep = r[c[1]].strip()
                 t = r[c[2]].strip()
                 if alvo and dep and alvo != dep:
                     edges[(alvo, dep)].add(t)
         edges_rows = [{
             "projeto_alvo": a, "depende_do": d,
             "via_tabelas": " | ".join(sorted(ts)), "qtd_via": len(ts),
         } for (a, d), ts in edges.items()]
     ```
     - para:
     ```
         edges = collections.defaultdict(set)
         edge_maxprod = collections.defaultdict(int)
         with open(R03, newline="", encoding="utf-8") as f:
             rd = csv.DictReader(f)
             c = rd.fieldnames
             for r in rd:
                 alvo = r[c[0]].strip()
                 dep = r[c[1]].strip()
                 t = r[c[2]].strip()
                 try:
                     np_ = int(r.get("n_produtores") or 1)
                 except (TypeError, ValueError):
                     np_ = 1
                 if alvo and dep and alvo != dep:
                     edges[(alvo, dep)].add(t)
                     if np_ > edge_maxprod[(alvo, dep)]:
                         edge_maxprod[(alvo, dep)] = np_
         edges_rows = [{
             "projeto_alvo": a, "depende_do": d,
             "via_tabelas": " | ".join(sorted(ts)), "qtd_via": len(ts),
             "max_produtores": edge_maxprod[(a, d)] or 1,
         } for (a, d), ts in edges.items()]
     ```
  2. **`ed_cols`** (~693) — de: `ed_cols = ["projeto_alvo", "depende_do", "via_tabelas", "qtd_via"]`
     - para: `ed_cols = ["projeto_alvo", "depende_do", "via_tabelas", "qtd_via", "max_produtores"]`
  3. **DDL do CREATE** (~821) — de:
     `run(f"CREATE TABLE {T_ED} (projeto_alvo STRING, depende_do STRING, via_tabelas STRING, qtd_via INT) USING DELTA")`
     - para:
     `run(f"CREATE TABLE {T_ED} (projeto_alvo STRING, depende_do STRING, via_tabelas STRING, qtd_via INT, max_produtores INT) USING DELTA")`

- [ ] **Step 2: patch + py_compile + diff paridade**
  Run: `python3 scratchpad/patch_publish.py && python3 -m py_compile publish_to_databricks.py app/pipeline/publish_to_databricks.py && diff -q publish_to_databricks.py app/pipeline/publish_to_databricks.py`
  Expected: OK + idênticos.

---

### Task 3: Validação local — determinismo

**Files:** Create (efêmero): `scratchpad/test_determinism.py`

- [ ] **Step 1: Guardar o report 03 committed (baseline 201)**
  Run: `git show HEAD:egps_analysis/03_matriz_dependencias.csv > scratchpad/03_committed.csv; wc -l scratchpad/03_committed.csv`

- [ ] **Step 2: Rodar orchestrator (ordem normal/sorted)** → salvar report 03 como A.
  Run (background, ~5min): orchestrator; depois `cp 03_matriz_dependencias.csv scratchpad/03_A.csv`

- [ ] **Step 3: Rodar orchestrator com `os.listdir` REVERTIDO** (monkeypatch) → salvar como B.
  `test_determinism.py`: importa o módulo, faz `import os; _real=os.listdir; os.listdir=lambda p, _r=_real: list(reversed(_r(p)))`, chama `generate_reports()`, `cp 03 → scratchpad/03_B.csv`.
- [ ] **Step 4: Assert A == B** (byte a byte)
  Run: `diff -q scratchpad/03_A.csv scratchpad/03_B.csv`
  Expected: idênticos (determinismo provado).

---

### Task 4: Validação local — completude, flag, frontier

**Files:** Create (efêmero): `scratchpad/analyze_new_graph.py`

- [ ] **Step 1: Coluna + completude**
  Assert: header do 03_A tem `n_produtores` na posição 3; escolher uma tabela com 2–3 produtores (do report 02) e confirmar que o 03 agora tem uma aresta por produtor.
- [ ] **Step 2: Frontier completo**
  Reusar a lógica do pré-flight (`_dep_of_map`+`_transitive_upstream`) com as arestas de `03_A.csv` + base de prod (read-only) → imprimir o novo frontier `indi_deps`, total de arestas distintas, nº de arestas ambíguas (`n_produtores>1`), nº de tabelas ambíguas.
- [ ] **Step 3: Diff vs baseline 201**
  Comparar frontier novo vs 201; listar EGPs que entram/saem.

---

### Task 5: Validação local — publish dry-run

- [ ] **Step 1: Rodar publish sem `--apply`**
  Run (from `egps_analysis/`, sem conectar): `python3 publish_to_databricks.py` (dry-run) → confere que imprime `sas_lineage_edges` com `max_produtores` e contagens coerentes; nenhuma conexão a prod.
  Expected: dry-run imprime esquema com `max_produtores`; sem erro.

---

## Self-review
- Cobertura do spec: §3.1→T1.1, §3.2→T1.2-3, §3.3→T1.4, §3.4→T1.5-6, §3.5→T1.7+T2, §7→T3-5. OK.
- Sem placeholders (código real em cada replace).
- Consistência de nomes: `table_to_producers`, `n_produtores`, `max_produtores`, `edge_maxprod` usados igual em todas as tarefas.
- Escopo: 2 arquivos (×2 cópias) + validação local. Nada de main.py/frontend/prod.
