# Escopo Indicium — Cobrança (os 167 projetos)

> **Data:** 2026-06-19 · **Recorte:** apenas os EGPs da área **Cobrança** que estão no **escopo Indicium (DOR1)**.
> **Fontes:** `indi_231_vs_extracao_06.csv` (escopo), `06_prontidao_tabela.csv` (inputs), `03_matriz_dependencias.csv` (dependências), `05_prontidao_egp.csv` (onda). Base extraída em 2026-06-19 (1.742 `.txt`).
> **Validação:** os números de dependência batem 100% com a aba Onda/Prontidão do app (6/6 linhas conferidas).

---

## 1. Definição do escopo

| | |
|---|---|
| EGPs de Cobrança na lista DOR1 Indicium | **169** |
| Resolvidos no inventário (chave `Cobranças__`) | **167** |
| Faltante (sem `.egp` em `received_egps`) | **1** — `ca_apagar_periodo` |
| Resolvido sob outra chave/área | 1 |

Este documento trata dos **167 resolvidos**. Eles representam **73% dos 230 EGPs DOR1** do escopo Indicium total (229 resolvidos), sendo de longe a maior área do escopo.

---

## 2. Big numbers

| | |
|---|---|
| **167** | projetos no escopo (Cobrança ∩ Indicium) |
| **2.572** | inputs distintos · **4.701** ocorrências (artefato×projeto) |
| **3.962 / 739** | ocorrências de **tabela** / **arquivo** |
| **~1.417** | ocorrências de input **já no BigQuery** (nativa/modernizada) |
| **~3.284** | ocorrências **"Não Encontrado"** (candidatas a ingestão) |
| **86 / 81** | projetos **com / sem** dependência mapeada |
| **138 + 59** | relações de dependência **internas + externas** |
| **21** | produtores **externos** ao escopo (precisam vir junto) |

---

## 3. Distribuição por onda de migração

| Onda | Projetos |
|---|---:|
| Onda 0 | **81** |
| Onda 1 | 27 |
| Onda 1 (ciclo — quebrar manual) | 8 |
| Onda 2 | 29 |
| Onda 3 | 17 |
| Onda 4 | 5 |
| **Total** | **167** |

Quase metade (81) está na **Onda 0** — a base inicial sem dependências a montante resolvidas no escopo.

---

## 4. Inputs — o esforço de ingestão

**4.701 ocorrências de input** (3.962 tabelas + 739 arquivos), **2.572 distintas**.

### Por situação no datalake (status de validação)
| Situação | Ocorrências |
|---|---:|
| 🔴 Não Encontrado (a ingerir) | **3.284** |
| 🟢 Nativa BigQuery (já no EGP) | 1.138 |
| 🟢 Modernizada (match direto Chameleon) | 173 |
| 🟢 Modernizada via réplica (RepMap) | 104 |
| 🟢 Identificado ajuste | 2 |
| **Já no BigQuery (subtotal)** | **~1.417** |

### Por origem (source_type, top)
| Origem | Ocorrências |
|---|---:|
| **SAS/Local → libname_in** | **2.196** |
| BigQuery (+ /GCP) | 1.138 |
| (arquivos) | 739 |
| Avaliar | 277 |
| SAS/Local (macro no membro) | 200 |
| Sybase IQ | 78 |
| SAS/Local | 62 |

**Leitura:** ~70% das ocorrências de input ainda **precisam ser ingeridas**, e o grosso é **SAS/Local** (datasets/libname SAS) — não banco transacional nem BQ. O caminho crítico de Cobrança é **materializar esses datasets SAS** no datalake; as ~1.417 já-no-BQ só precisam ser referenciadas (`source()`/`ref()`).

---

## 5. Dependências

- **86** projetos têm dependência mapeada · **81** aparecem sem dependência.
- **138** relações **internas** (produtor dentro do escopo Indicium) + **59** **externas** (produtor fora do escopo).
- **21 produtores externos distintos** — EGPs fora da lista DOR1 dos quais o escopo Cobrança depende. **O escopo não migra sozinho:** sem eles, as ligações quebram.

### Os 21 produtores externos (ranqueados por nº de projetos do escopo que dependem deles)

| #proj | Produtor externo | Área |
|---:|---|---|
| **14** | `20250918_darkpost_v15` | Cobranças |
| **8** | `ACORDO_AMIGAVEL_v1__v2` | Cobranças |
| 5 | `Carteira_CA_COMPLETA_GCP_2` | Cobranças |
| 4 | `CRIAR_MARCACAO_SEGMENTACAO_reap_1` | Cobranças |
| 4 | `Painel_Desconto_Perf_Solar` | Cobranças |
| 4 | `Apetite_Gerenciados_2025_v5__v2` | **Riscos** |
| 4 | `02. Classifica reg 3.1 - cdloja_Grupo` | **Crédito** |
| 2 | `Entrada_em_Cob_Geral_REAPONTADO_V2` | Cobranças |
| 2 | `COLCHAO_ACORDO_CL__v2` | Cobranças |
| 1 | `etl_bhrodas` | **SAS_UC4** |
| 1 | `RelatorioVFIN v8` | **Riscos** |
| 1 | `Ações Alçadas Apuração v3` | **Riscos** |
| 1 | (+9 demais, todos Cobranças) | Cobranças |

**Ação sugerida:** `20250918_darkpost_v15` (14 dependentes), `ACORDO_AMIGAVEL_v1__v2` (8) e `Carteira_CA_COMPLETA_GCP_2` (5) são os hubs — candidatos óbvios a **entrar no escopo** ou ter ingestão garantida. 5 dos 21 são de **outras áreas** (Riscos×3, Crédito×1, SAS_UC4×1) — exigem coordenação cross-área.

---

## 6. Prontidão (proxy automático)

Em ocorrências de input, **~30% já estão no BigQuery** (~1.417 de 4.701); o restante depende de ingestão. O **percentual por projeto e o status** (Bloqueado / Parcial / Quase pronto / Pronto p/ migrar / Em ciclo) são acompanhados **ao vivo na aba Onda/Prontidão do app** (que incorpora o status humano de ingestão, não refletido neste recorte estático).

---

## 7. Ressalvas

- ⚠️ **Números pré-fix de passthrough.** O extrator hoje subcaptura algumas leituras (`db..tabela` e tabelas cruas em JOIN de pass-through). Por isso os **81 "sem dependência"** e parte das relações estão **subestimados** — após a correção, dependências e inputs-tabela tendem a subir, e os "sem dependência" a cair. Re-rodar este recorte pós-fix mede o ganho.
- **1 faltante** (`ca_apagar_periodo`) sem `.egp` — fora do inventário.
- "Já no BigQuery / A ingerir" usa a **classificação automática** (Chameleon + RepMap + inventário transacional), não o status humano de ingestão.

---

## Anexos (dados de apoio, em `docs/analises/`)

- `escopo_cobranca_indicium_por_projeto_2026-06-19.csv` — os 167 projetos: onda, inputs (total / já-no-BQ / arquivos), dependências (total / internas / externas).
- `dependencias_cobrancas_indicium_2026-06-19.csv` — as arestas de dependência do escopo Cobrança (com origem do produtor).
