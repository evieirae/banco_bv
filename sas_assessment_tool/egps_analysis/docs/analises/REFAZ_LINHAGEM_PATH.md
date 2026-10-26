# Linhagem refeita por (path físico, membro) — SAS/Local

> **Data:** 2026-06-20 · **Base:** `06_prontidao_tabela.csv` + resolução libname→path (`ANALISE_LIBNAME_PATHS.md`).
> **Mudança:** casar `table_in`↔`table_out` de SAS/Local pela chave **(path físico, membro)** em vez de **(nome do libname, membro)**. BQ/Transacional/arquivo mantêm chave de nome.
> **Verificação:** workflow adversarial (4 agentes) — **pegou um bug grave** na 1ª versão e exigiu 3 correções (P0) antes de confiar nos números. Versão atual (v2) já corrigida.

---

## O que a verificação adversarial mudou

A 1ª versão reportava "+353 líquido (843 recuperadas, 490 falsas)". A verificação reprovou:
- as **490 "falsas" eram 99,4% bug** (fallback assimétrico: quando o libref do consumidor não resolvia — vive em autoexec/`%include` fora do `.egp` — caía na chave de nome enquanto o produtor usava chave de path; as chaves nunca casavam e a aresta caía **sem provar que os paths diferiam**). Só **3** eram false-merge reais.
- as **843 recuperadas** estavam corretas no critério (895/895 duplas confirmadas: nomes de lib diferentes → mesmo path físico), mas **82% passavam por hubs multi-produtor** (ambiguidade, não dependência 1:1).

**Correções aplicadas (v2):** (1) só remove aresta quando o libref resolve nos **dois** lados a paths **disjuntos**; (2) marca o **fan-out** (nº de produtores no path) nas recuperadas; (3) expõe os **hubs compartilhados**.

---

## Resultado (v2, confiável)

| | |
|---|---|
| Arestas **recuperadas LIMPAS** (1 produtor no path) | **155** |
| Arestas recuperadas via **hub multi-produtor** | **688** |
| **Falsas genuínas** removidas (ambos resolvem, paths disjuntos) | **3** |
| **Hubs compartilhados** (path+membro escrito por >1 EGP) | **407** |

### As 155 LIMPAS — dependências reais antes perdidas
Conexões que o casamento por nome perdia porque o **mesmo path físico tinha nomes de libname diferentes** no produtor e no consumidor (ex.: `INSIGHT` vs `_INSIGHT` em `/riscosbvf/insight`; `BASES` vs `HOMOLOG2`/`PROJETOS` em `/projetos/misv/data/bases`; `MOVTO` vs `CARTAO`). **Verificadas 100%.** → devem **entrar** na linhagem. CSV: `linhagem_arestas_recuperadas.csv` (tipo=`limpa`).

### As 688 via HUB — reais mas com produtor ambíguo
O par (path, membro) tem >1 produtor: a ligação existe (todos escrevem fisicamente o mesmo arquivo), mas **não dá pra saber qual job alimentou cada consumidor** só por path+membro. → tratar como **dependência de tabela compartilhada multi-produtor** (não 1:1); desambiguar por timestamp/ordem se necessário. CSV: tipo=`hub_multiprodutor` (com `n_produtores`).

### Os 407 HUBS — o achado estrutural
Arquivos físicos escritos por **vários EGPs** (contenção/base compartilhada). Topo:

| nº produtores | membro | path |
|---:|---|---|
| 15 | `CONTROL_TEMP_REGUAS` | `/riscosbv/cobranca/brsouza/reguas/historico` |
| 11 | `PERF_AMIGAVEL` | `/riscosbv/cobranca/erocha/cartao/movto` |
| 10 | `BASE_CYBER` | `/riscosbv/cobranca/ksilvestre` |
| 9 | `TBBRUTA` | `/riscosbvf/insight` |
| 8 | `TBPRODUCAO` | `/projetos/misv/data/bases` |
| 8 | `LOG_PROC_JOBS` | `/projetos/ctrcredito/pepr/datamart` |

Esses são pontos críticos de migração: como vários jobs escrevem o mesmo arquivo, a linhagem não atribui produtor único — precisam de decisão (job canônico, ou tabela versionada por job). CSV completo: `linhagem_hubs_multiprodutor.csv`.

---

## Implicação para a migração

1. **Adicionar as 155 arestas limpas** à linhagem (deps reais que o name-keying perdia).
2. **Remover só as 3 falsas genuínas** (o "490" era artefato — preservar arestas com lado não-resolvido).
3. **Marcar os 407 hubs** como tabelas compartilhadas multi-produtor — entram no plano de consolidação (`PLANO_CONSOLIDACAO_SASLOCAL.md`) como casos que exigem job canônico/desambiguação.

## Integração no orquestrador (FEITO — 2026-06-20, commit `1d7a0e0`)

A chave por path **foi integrada** ao `orchestrator_inventory.py`: ele agora lê o **corpo** do `.txt` (não só o header) via `parse_libmap_from_txt` (`libname_resolver.py`), resolve `libref → path físico` por projeto e roda uma **passada de recuperação** que casa `table_in ↔ table_out` por `(path físico, membro)`. Três decisões de implementação que costumam virar dúvida:

- **(a) A passada é 100% aditiva.** Ela **só adiciona** arestas (`adj_list[g].append(proj)` + `in_degree[proj] += 1`); **nunca remove** nada do grafo de nome / `.sas7bdat`. Inclusive **não remove** as 3 falsas-genuínas — a lógica de disjunção de paths ficou só no protótipo (`linhagem_path_aware.py`), não foi portada. **Por quê:** o "490 falsas" original era 99,4% bug de fallback assimétrico (ver acima); o risco de remover indevidamente supera o ganho de eliminar 3 arestas. Linhagem que só cresce é segura; remoção exige prova nos dois lados.
- **(b) Por que o orquestrador reporta `+335` e o protótipo reportava `843`.** O protótipo standalone comparou **só** name-key vs path-key → 843 recuperadas (155 limpas + 688 hub). O orquestrador deduplica contra **todas** as arestas já existentes (name-key **+** match por basename `.sas7bdat`, via `seen_matrix`), então o **incremento líquido** sobre o grafo real é **+335** arestas genuinamente novas (+12 ciclos novos). Os dois números medem coisas diferentes (universo recuperável total vs. delta sobre o grafo já existente) e **ambos estão corretos**.
- **(c) Por que a recuperação por path NÃO replica o guard de membro-genérico do bloco `.sas7bdat`.** O match por `.sas7bdat` casa por **basename** (frouxo, colide fácil), então tem guards defensivos: `GENERIC_MEMBER` (BASE/TEMP/AUX/…), `len(membro) < 6`, `isdigit()` e cap de `len(produtores) > 3`. A passada por path **não** tem esses guards, **de propósito**: a chave `(path físico, membro)` já é muito mais restritiva (só casa quando dois EGPs compartilham o **mesmo diretório físico absoluto**), então o ruído que o guard combate praticamente não ocorre. Quantificação das 335 recuperadas: **0** membro genérico, **0** numérico, **8** membro curto (<6: `BU_CP`×6, `TBVNP`×2 — tabelas reais). Aplicar o guard aqui só introduziria **falso-negativo** (derrubaria essas 8 arestas legítimas). O cap de fan-out (`>3`) também é dispensável: `gen_path[(path,membro)]` guarda **um** produtor (*last-writer-wins*), não um conjunto — um hub de 8 writers vira **1** aresta, não 8. ⚠️ **Não "simetrize" esse guard** sem refazer a quantificação: hoje ele só causaria perda de dependência real.

## Anexos
- `linhagem_path_aware.py` (v2, pós-verificação).
- `linhagem_arestas_recuperadas.csv` — 843 (155 limpas + 688 hub), com `n_produtores`.
- `linhagem_falsas_genuinas.csv` — as 3 false-merge reais.
- `linhagem_hubs_multiprodutor.csv` — 407 hubs (path,membro,n_produtores).
