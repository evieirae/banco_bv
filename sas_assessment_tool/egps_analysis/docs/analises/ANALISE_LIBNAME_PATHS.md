# Tabelas SAS/Local por path físico de libname

> **Data:** 2026-06-20 · **Base:** `text_egps/` (1.742 `.txt`) + `06_prontidao_tabela.csv` (pós-fix de passthrough).
> **Premissa:** agrupar por **path físico** do libname (absoluto), **não** pelo nome do alias — porque o nome é mutável por EGP e o mesmo nome aponta para diretórios diferentes.
> **Script:** `docs/analises/analise_libname_paths.py`. **Verificação:** workflow adversarial (5 agentes) — merges aprovados **42/42 (0 falso-merge)**; bugs de chaveamento e higiene de denominador corrigidos (v2).

---

## Por que path, não nome (evidência)

O instinto está correto e é mensurável nos nossos dados:

- **51 de 435 nomes de libname (12%) apontam para >1 path físico distinto** — o mesmo alias significa diretórios diferentes em EGPs diferentes:
  - `RENEG` → **7 paths** · `CART` → 6 · `CARTAO`/`STGPRG`/`TMPPRG` → 4 · `BASES`/`PROV2017`/`CARTEIRA` → 3 …
- E o inverso: **88 paths físicos são alcançados por >1 nome de alias** (nomes diferentes → mesmo diretório):
  - `/projetos/misv/data/bases` ← **11 aliases** (BASES, BV0, HOML, HOMOLOG, MIS, MIS2, …, PROJETOS)
  - `/riscosbvf/plan_mesas/comp_total` ← 8 · `/financas/cartoes` ← 5 · `/riscosbv/operacional/comp_infjur` ← 5 …

→ Agrupar por **nome** fundiria coisas distintas e separaria coisas iguais. Agrupar por **path** (com `&macro` resolvido via `%let`) é o correto. *(Verificado: 42/42 pares alias→path conferem contra o `LIBNAME` real.)*

---

## Big numbers

| | |
|---|---|
| `table_in` SAS/Local (após excluir 1.754 não-tabelas¹) | **12.173** |
| Resolvidos a um path físico | **9.490** |
| **Paths físicos distintos** | **366** |
| Paths alcançados por **>1 alias** (nome ≠, path =) | **88** |
| Aliases que apontam para **>1 path** (nome =, path ≠) | **51** |
| Membros com **mesmo nome em >1 path** | **512** → **202 literal-estável** + 310 snapshot datado |
| Não resolvidos (lib sem `LIBNAME` no `.txt`) | **3.211 (26%)** — libs via `%include`/autoexec fora da captura |

¹ excluídos placeholders `{macro}`, membros templados (`MODELO._{VARIAVEL}`), `DICTIONARY`, libs TEMP/WORK e engines não-disco (BD + XML/Excel).

---

## A) Análise: mesmo nome / nomes diferentes entre paths

### A.1 — Nomes de libname diferentes → mesmo path (88 paths)
Detalhe completo em `saslocal_tabelas_por_path.csv` (coluna `libname_aliases`). São o caso clássico de "o mesmo diretório recebeu apelidos diferentes em EGPs diferentes" — para migração, **é uma única biblioteca física**, não N.

### A.2 — Mesmo nome de tabela (membro) em paths distintos (512)
Segmentado para separar duplicação real de ruído:
- **202 `literal_estavel`** — duplicação lógica real (candidatos a consolidar/deduplicar na migração). Topo: `DIAS_UTEIS` (6 paths), `FIM_DE_SEMANA` (5), `DIA_UTIL` (4), `TBPESSOA`, `GARANTIAS`, `BASE_CONTABILIDADE`, `GERA_TRABA_FULL`…
  - Dois sub-padrões (verificados): **(a) tabelas de referência replicadas** em diretórios pessoais (`DIAS_UTEIS`, `FIM_DE_SEMANA` = calendários auxiliares copiados); **(b) homônimos distintos** (`TBPESSOA` em `insight` vs `seguros/dados` são tabelas diferentes que só compartilham o nome).
- **310 `snapshot_datado`** — colisão trivial de nomes datados (`PROVISAO_202002`, etc.); baixa relevância.

Lista completa (com segmento e paths) em `saslocal_mesmo_nome_paths_distintos.csv`.

### A.3 — Aprofundamento: replicada (consolidar) vs distinta (não mesclar)
Usando o sinal **produtor↔consumidor** (resolvendo também `table_out` a path), os 236 membros literal-estável em >1 path classificam-se em (script `aprofunda_saslocal_homonimos.py`, CSV `saslocal_homonimos_classificados.csv`):

| Classe | Qtd | Significado | Ação |
|---|---:|---|---|
| **multi_produtor** | **141** | produzido (`CREATE`/`DATA`) em ≥2 paths → tabelas independentes que só compartilham nome | **DISTINTAS — não mesclar** |
| **externa_replicada** | **70** | produzido em 0 paths do corpus, lido em N → referência externa copiada em vários libnames | **CONSOLIDAR** (ingerir 1×, apontar todos) |
| **fonte_unica_replicada** | **25** | produzido em 1 path, lido em outros → fonte única replicada | **CONSOLIDAR** (usar a fonte única) |

→ **95 candidatos a consolidação** (70 + 25) vs **141 distintas**. Spot-check confirmou os 3 padrões: `TBPESSOA` (4 produtores → distinta), `FIM_DE_SEMANA` (1 path produtor `ATIVAE`, 21 leituras → fonte única), `DIA_UTIL` (0 produtor, 12 leituras → externa). *Caveat: `multi_produtor` é conservador (sinaliza "olhar antes de mesclar"); `DIAS_UTEIS` p.ex. tem 6 cópias mas 2 produtores — replicação parcial que merece revisão humana.*

---

## B) Análise: quantidade de tabelas por path físico

366 paths em `saslocal_tabelas_por_path.csv` (path, nº de tabelas, nº de aliases, aliases, amostra). Topo:

| nº tabelas | path físico | aliases |
|---:|---|---|
| 252 | `/riscosbvf/pol_empcr/manut_limites` | MANUTLIM |
| 250 | `/riscosbv/cobranca/grimaldi` | GRIMALDI |
| 230 | `/riscosbv/mro/modelos/provconttrab/rotinacalculo` | PROV2017, TRAB |
| 203 | `…/rotinacalculo/tombamento` | PROV2017, TRAB |
| 189 | `/riscosbv/cobranca/leonardo_trinchinato` | TRINCHI |
| 154 | `/riscosbv/cobranca/csaure/dist_consg/pj_privado/nova_carga` | PRIVADO |
| 149 | `/riscosbvf/planejamento/comp_total/ale` | ALE |
| 119 | `/riscosbv/credito/miscredito` | MISCRED, _MISCRED |

Concentração em diretórios pessoais (`/cobranca/<usuário>`) e de modelos (`/mro/modelos/...`) — sinal de bases mantidas localmente por analista.

---

## Cobertura & ressalvas (verificadas adversarialmente)

- **366 paths é um PISO.** **26% dos `table_in` SAS/Local (3.211) não resolvem** porque o libref é definido via `%include`/autoexec **fora dos `.txt` capturados**; na maioria o mesmo alias é **ambíguo** (ex.: `BASES` → 6 paths), então **não dá para inferir o path com segurança**. Resolver mais exigiria capturar os autoexec/`%include` na extração.
- **`n_paths` da análise A.2 é teto superior:** o script credita o membro a todos os paths que o libref assume no EGP; não rastreia qual binding está ativo no ponto exato da leitura (SAS usa o `LIBNAME` mais recente). Infla levemente casos com sub-paths transitórios.
- **Paths normalizados em minúsculas** (Linux é case-sensitive, mas o mesmo diretório é escrito de forma consistente; merge validado em 42/42).
- Falsos-positivos residuais a montante (aliases SQL `B`/`T1` classificados como libref pelo extractor) são pequenos e não afetam os agrupamentos por path.

## Anexos
- `analise_libname_paths.py` — script principal (v2, pós-verificação).
- `aprofunda_saslocal_homonimos.py` — aprofundamento replicada vs distinta (produtor↔consumidor).
- `saslocal_tabelas_por_path.csv` — 366 paths × (nº tabelas, aliases, amostra).
- `saslocal_mesmo_nome_paths_distintos.csv` — 512 membros homônimos × (segmento, paths).
- `saslocal_homonimos_classificados.csv` — 236 literal-estável × (n_paths, produtor/consumidor, classe).
