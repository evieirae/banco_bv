# Inputs a ingerir por área — escopo Indicium + dependentes (consolidado dedup)

> **Data:** 2026-06-19 · **Recorte:** inputs distintos *ainda a ingerir* do escopo Indicium
> inteiro + EGPs dependentes (transitivos), **atribuídos a uma única área** (sem dupla contagem).
> **Fonte:** estado **AO VIVO** do Databricks — `bv_dev_db.monitoramento_sas` (`sas_inputs_monitor`,
> `sas_lineage_nodes`/`_edges`, `sas_egp_inputs`/`sas_resumo_proj`).
> **Status considerado:** **EFETIVO** — `status_humano` (progresso humano de ingestão) prevalece
> sobre a classificação automática `modernizada_auto`, idêntico ao `/api/landing` do app.
> **Reprodução:** `egps_analysis/venv/bin/python docs/analises/build_inputs_a_ingerir_por_area.py`.

> ⚠️ **Snapshot vivo.** A tabela muda conforme as edições de status na aba Monitoramento. Este doc
> fixa o estado de 2026-06-19; reexecutar o `build_*` acima mede o estado atual.

---

## 1. Método

- **Universo** = **229** EGPs do escopo Indicium (DOR1, todas as áreas) **∪ 74** EGPs dependentes
  transitivos (produtores fora do escopo alcançados pelo grafo de linhagem) = **303 EGPs**.
- **"A ingerir"** = status efetivo ∉ {`Modernizado`, `Sanitizado`} (ou seja, `A receber` / `Recebido` / `Em ingestão`).
- **Atribuição a uma área** (dedup): cada input distinto (`chave_canonica`) vai para **uma** área —
  voto pelos EGPs que o leem, **priorizando leitores do escopo**; empate → ordem alfabética.
  Por isso **a soma das áreas == total**, sem a sobreposição das visões por-área isoladas.

---

## 2. Big numbers (status efetivo, ao vivo)

| | Distintos | **A ingerir** |
|---|---:|---:|
| Inputs do **escopo Indicium** | 3.205 | **2.703** |
| Inputs das **dependências** (disjunto) | 916 | **836** |
| **TOTAL (dedup)** | **4.121** | **3.539** |
| dos quais **tabelas** | — | **2.686** |

~**86%** dos inputs do universo ainda estão a ingerir (3.539 de 4.121).

---

## 3. Consolidado por área × origem (os 3.539)

Cada input contado **uma vez**, na sua área de atribuição. `SAS/Local (externo)` = dataset SAS sem
produtor conhecido (candidato real a ingestão); `SAS/Local (dependência)` = saída intermediária de
um EGP dependente (resolve via `ref()` quando o produtor migrar, não por ingestão de fonte).

| Área | SAS/Local (ext.) | SAS/Local (dep.) | Arquivo | Transacional | Script | **Total** | (tabelas) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Cobranças** | 1.218 | 373 | 601 | 10 | 0 | **2.202** | 1.601 |
| **Riscos** | 483 | 274 | 173 | 85 | 2 | **1.017** | 842 |
| **Atacado** | 59 | 95 | 14 | 2 | 0 | **170** | 156 |
| **Crédito** | 10 | 7 | 17 | 0 | 0 | **34** | 17 |
| **Jurídico** | 4 | 7 | 9 | 14 | 0 | **34** | 25 |
| **SAS_UC4** | 11 | 2 | 14 | 3 | 3 | **33** | 16 |
| **Finanças** | 3 | 13 | 0 | 0 | 0 | **16** | 16 |
| **Cartões** | 0 | 2 | 9 | 0 | 0 | **11** | 2 |
| **Banco Relacional** | 2 | 0 | 4 | 0 | 0 | **6** | 2 |
| **Operações** | 0 | 0 | 5 | 1 | 0 | **6** | 1 |
| **Negócios Transacionais Varejo e NaPista** | 3 | 1 | 1 | 0 | 0 | **5** | 4 |
| **Negócios e Produtos Relacional e Seguros** | 2 | 2 | 0 | 0 | 1 | **5** | 4 |
| **TOTAL** | **1.795** | **776** | **847** | **115** | **6** | **3.539** | **2.686** |

---

## 4. Leitura

- **Cobranças (2.202) + Riscos (1.017) = 3.219 (~91%)** de todo o esforço de ingestão. As demais 10
  áreas somam apenas **320**.
- **SAS/Local domina:** 1.795 + 776 = **2.571 (~73%)**. O caminho crítico é **materializar datasets
  SAS** no datalake, não banco transacional (`Transacional` = só 115, ~3%) nem arquivo.
- **Áreas fora da lista do escopo** (Crédito, SAS_UC4, Banco Relacional, Negócios e Produtos…)
  aparecem porque têm inputs lidos **apenas por EGPs dependentes** — não há leitor do escopo, então a
  atribuição recai na área do dependente. São o custo de "trazer junto" os produtores externos.
- **Diferença para as tabelas por-área não-dedup:** lá cada área carregava *todos* os seus
  dependentes (com sobreposição → não somavam). Aqui Cobranças cai de 2.764 → 2.202 porque inputs
  compartilhados que votam para outra área saem da conta dela.

---

## 5. Ressalvas

- **Snapshot vivo:** entre consultas o número muda (ex.: o escopo a ingerir caiu de 2.729 → 2.703 em
  poucos minutos durante a apuração, à medida que inputs eram marcados como resolvidos).
- ⚠️ **Pré-fix de passthrough:** o extrator ainda subcaptura leituras de tabela (`db..tabela`, cruas em
  JOIN de pass-through). Os distintos-tabela tendem a **subir** após a correção.
- A atribuição por **voto** resolve compartilhamento de forma determinística, mas um input lido por
  muitas áreas fica numa só — para ver todas as áreas/projetos leitores, use o CSV de detalhe.

---

## Anexos (em `docs/analises/`)

- **`inputs_a_ingerir_matriz_area_origem_2026-06-19.csv`** — a matriz da seção 3 (área × origem + total + tabelas).
- **`inputs_a_ingerir_por_area_2026-06-19.csv`** — detalhe por input (3.539 linhas):
  `area_principal, origem, categoria, chave_canonica, qtd_projetos, escopo_indi, projetos`
  (a coluna `projetos` lista todos os EGPs do universo que leem cada input, separados por ` | `).
- **`build_inputs_a_ingerir_por_area.py`** — gerador (lê o Databricks ao vivo).
