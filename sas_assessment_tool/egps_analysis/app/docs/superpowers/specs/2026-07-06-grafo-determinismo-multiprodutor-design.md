# Grafo de dependências determinístico e completo (multi-produtor) — Design Spec

- **Data:** 2026-07-06
- **Sub-projeto:** 1 de 2 (fundação). O 2 (revisão humana da dependência) vem depois, em cima deste.
- **Camada:** pipeline (`orchestrator_inventory.py` + `publish_to_databricks.py` e as cópias vendored em `egps_analysis/app/pipeline/`). **Zero** mudança em `main.py`/frontend.
- **Status:** design aprovado pelo usuário ("Pode seguir").

## 1. Problema

O recorte `indi_deps` (frontier upstream) oscilou de **201** para **256** EGPs sem mudança de corpus nem de lógica. Causa-raiz: o grafo projeto→projeto (report 03) é **não-determinístico** e **incompleto** para tabelas com mais de um produtor.

- `orchestrator_inventory.py:665` lê `os.listdir(INPUT_FOLDER)` **sem ordenar** → a ordem depende do filesystem (ext4 local vs. FS do container).
- `table_to_generator[k] = proj` (linha ~769) é **last-writer-wins**: quando N EGPs escrevem a mesma tabela, sobra 1 produtor arbitrário, decidido pela ordem de listagem.
- O bloco de arestas principal (linha ~791) usa esse único produtor → cada tabela multi-produtor vira **1 aresta arbitrária**. Ordem diferente ⇒ produtor diferente ⇒ frontier diferente.

Medição (report 02 committed, 25.728 tabelas de saída): **26,9% (6.911) são multi-produtor** — 4.651 com 2 produtores, 1.116 com 3, e uma cauda de fan-out alto dominada por ruído de captura (`OUT`=96, `NOPRINT`=61, `TESTE`=81, `WORK.ETLS_CONTENTS`=43…).

Nem 201 nem 256 é "correto" — são dois sorteios arbitrários do mesmo grafo mal-definido.

## 2. Decisão

Para migrar os EGPs na ordem certa, precisamos saber **qual** produtor é a dependência real. Como o dado não permite decidir isso automaticamente na maioria dos casos (só 2 tabelas do corpus são desambiguáveis por path físico), a decisão do usuário foi:

**Emitir TODAS as arestas candidatas (sem corte de fan-out) e marcar as tabelas ambíguas para revisão humana.** A revisão (escolher o produtor real por tabela, persistido) é o **sub-projeto 2**. Este sub-projeto (1) entrega o grafo **determinístico, completo e com a ambiguidade visível**.

"Sem corte" foi escolha explícita do usuário, ciente de que isso traz ruído (ex.: `NOPRINT`/`OUT` viram muitas arestas) que polui o frontier/ondas até a revisão humana podar. O filtro é humano, não heurístico.

## 3. Mudanças

Todas em `orchestrator_inventory.py` e `publish_to_databricks.py`, **replicadas** nas cópias vendored `egps_analysis/app/pipeline/orchestrator_inventory.py` e `.../publish_to_databricks.py` (fonte da verdade = `egps_analysis/*.py`).

### 3.1 Determinismo (rede de segurança)

`orchestrator_inventory.py:665`:
```python
txt_files = sorted(f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith('.txt'))
```
Estabiliza os valores que continuam sendo escolha única (o `table_to_generator` de display e o `gen_path` do path-recovery), independente da ordem do filesystem.

### 3.2 Conjunto completo de produtores (linhas ~762–771)

Novo mapa `table_to_producers = defaultdict(set)`. No loop de outputs:
```python
k = _canonical_table_key(tb)
table_to_producers[k].add(proj)
proj_output_keys[proj].add(k)
out_member_index[_member_key(tb)].add(proj)
```
Depois do loop, deriva o valor único **determinístico** só para display (report 01 usa `table_to_generator` na linha ~875 para o rótulo "Gerado Internamente (X)"):
```python
table_to_generator = {k: sorted(ps)[0] for k, ps in table_to_producers.items()}
```
Remove o `table_to_generator[k] = proj` por iteração.

### 3.3 Bloco de arestas principal emite todas as candidatas (linhas ~789–810)

Substitui a escolha única por iteração sobre todos os produtores. Preserva o invariante **"leitor que também escreve a tabela → não é aresta produtor→consumidor"** (share/append), e ordena para saída estável:
```python
producers = table_to_producers.get(k_in, ())
if k_in in proj_output_keys.get(proj, ()):
    continue  # proj também escreve k_in: partilha/append
n_prod = len(producers)
for generator in sorted(producers):
    if generator == proj:
        continue
    if proj not in adj_list[generator]:
        adj_list[generator].append(proj)
        in_degree[proj] += 1
    rk = (proj, generator, inp_table)
    if rk not in seen_matrix:
        seen_matrix.add(rk)
        matrix_rows.append([proj, generator, inp_table, n_prod])
```
`n_prod` = nº de EGPs que produzem `k_in` (propriedade da tabela; igual em todas as linhas dela). Como o `continue` já filtra o caso em que `proj` produz `k_in`, nenhum produtor iterado é o próprio `proj`.

**Sem corte de fan-out e sem guard de nome** neste bloco (casamento é por nome canônico completo `lib.member`, que é exato).

### 3.4 Blocos de recuperação — uniformidade + coerência

- **`.sas7bdat` (linhas ~811–828):** passa a emitir **todas** as arestas (dentro dos guards existentes), em vez de só `sorted(producers)[0]`. **Mantém** os guards (`len<6`/numérico/`GENERIC_MEMBER`/fan-out>3) — são invariante documentado: o casamento por *basename* é frouxo e sem guard gera falso-positivo (ver `docs/analises/REFAZ_LINHAGEM_PATH.md`). A assimetria com o bloco 3.3 (que não tem guard) é **deliberada**. Cada aresta anexa `[proj, generator, fr, len(producers)]`.
- **Path-recovery (linhas ~833–869):** `gen_path` vira `defaultdict(set)`; emite todos os produtores do mesmo `(path, member)`. Continua aditivo. Anexa `[proj, g, inp_table, len(producers_do_path)]`.

Os três blocos anexam 4-tuplos uniformes, então o writer do report 03 fica consistente. Como `seen_matrix` deduplica por `(proj, generator, via)` e o bloco principal (3.3) roda **antes** dos de recuperação, arestas sobrepostas ficam com o `n_produtores` canônico; uma aresta encontrada **só** por um bloco de recuperação carrega o `n_produtores` do espaço de chave daquele bloco (contagem por membro, ou por `(path, member)`). O flag `> 1` continua correto em qualquer caso.

### 3.5 Report 03 + `sas_lineage_edges`

- **Report 03** (`orchestrator_inventory.py`, writer ~890–899): header ganha `n_produtores` na **posição 3** (antes de `project_extension`):
  ```
  Projeto_Alvo (Precisa Migrar), Depende_Do_Projeto, Via_Tabela, n_produtores, project_extension, created_at
  ```
  `writer.writerow(row + [ext, created_at])` continua válido (row agora tem 4 elementos → 6 colunas).
- **`publish_to_databricks.py`** (bloco de edges ~458–472): agrega por `(alvo, dep)` um `max_produtores = max(n_produtores das via-tables da aresta)`, lendo `n_produtores` **por nome** com fallback `1` (retrocompatível com report 03 antigo). A tabela `sas_lineage_edges` (full-replace, DDL ~821) ganha coluna `max_produtores INT`; `ed_cols` ganha `"max_produtores"`.

## 4. Semântica do flag

`n_produtores` numa aresta do report 03 = quantos EGPs produzem aquela `Via_Tabela`.
- `= 1` → dependência inequívoca (esta aresta É a resposta).
- `> 1` → ambígua (uma de N candidatas; alvo da revisão humana).

Em `sas_lineage_edges`, `max_produtores > 1` marca a aresta como ambígua — insumo pronto e inerte para o sub-projeto 2 (o backend/frontend só passam a lê-lo lá).

## 5. Compatibilidade

- `publish` lê as 3 primeiras colunas do report 03 **por posição** (`c[0..2]`); inserir `n_produtores` na posição 3 **não desloca** essas leituras.
- `sas_lineage_edges` é **full-replace** (DROP+CREATE) e **não tem colunas humanas** (o status humano vive em `sas_egp_pipeline`/nós, via MERGE) → adicionar coluna é trivial e não destrói nada.
- **`main.py` não muda.** As queries do backend selecionam colunas nomeadas; a coluna nova é ignorada. O frontier `indi_deps` (`_frontier_egps`/`_transitive_upstream` sobre `sas_lineage_edges`) passa a refletir o grafo completo automaticamente após o republish — número **único, maior e estável** (nem 201 nem 256).

## 6. Fora de escopo (sub-projeto 2)

Tabela de override da escolha humana `(consumidor, tabela) → produtor confirmado`; endpoints; UI de revisão; e a **poda** das arestas candidatas pela escolha confirmada (frontier/ondas/bloqueio/priorização respeitando o produtor escolhido). Nada de `main.py`/frontend aqui.

## 7. Verificação (tudo local, sem tocar prod)

1. **Determinismo:** rodar o orchestrator 2× embaralhando a ordem dos `.txt` de entrada → `03_matriz_dependencias.csv` idêntico byte a byte.
2. **Completude:** para uma tabela multi-produtor real conhecida (2–3 produtores), o report 03 passa a conter uma aresta por produtor (antes: 1).
3. **Coluna `n_produtores`:** presente, correta (= contagem de produtores da `Via_Tabela`), consistente entre linhas da mesma tabela.
4. **`publish` dry-run** (sem `--apply`): imprime `sas_lineage_edges` com `max_produtores`; contagens coerentes; sem conectar em prod.
5. **Frontier local:** recomputar `indi_deps` a partir das arestas novas + base (168) → registrar o número completo, o total de arestas e quantas tabelas ambíguas surgem, **antes** de qualquer publish.

## 8. Critérios de aceitação

- `03_matriz_dependencias.csv` é determinístico (invariante à ordem de listagem) e tem a coluna `n_produtores`.
- Tabelas multi-produtor geram todas as arestas candidatas; nada de corte de fan-out no bloco principal; guards do `.sas7bdat` preservados.
- `publish` dry-run gera `sas_lineage_edges` com `max_produtores`, retrocompatível com report 03 sem a coluna.
- Cópias vendored idênticas às fontes.
- `main.py`/frontend intocados. Nenhuma escrita em prod neste sub-projeto.

## 9. Riscos / notas

- **Ruído de captura** (`NOPRINT`, `OUT`) infla o frontier até a revisão do sub-projeto 2 — aceito explicitamente. Sinaliza a importância de o sub-projeto 2 priorizar a revisão por impacto (nº de consumidores / se afeta o recorte Indicium).
- **Republish reintroduz o número completo** (não o 201 do stopgap atual). O stopgap `sas_lineage_edges_bak_pre201` é descartável após este sub-projeto entrar.
- O extrator capturar `NOPRINT`/opções como tabela é bug separado (qualidade de extração), não resolvido aqui.
